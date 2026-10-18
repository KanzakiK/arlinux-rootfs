import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
import json
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('publish', Path(__file__).resolve().parents[1] / 'tools/publish-wine-latest.py')
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.metadata = {'originalSources': {}}
        for name in ('wine', 'fex', 'dxvk', 'support'):
            path = self.directory / (name + '-source.tar.gz')
            path.write_bytes(name.encode())
            self.metadata['originalSources'][name] = {
                'asset': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def test_complete_sources_are_returned_for_upload(self):
        self.assertEqual(len(publish.component_source_archives(self.metadata, self.directory)), 4)

    def test_missing_or_corrupt_source_blocks_publication(self):
        path = self.directory / 'fex-source.tar.gz'
        path.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'mismatched'):
            publish.component_source_archives(self.metadata, self.directory)
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'mismatched'):
            publish.component_source_archives(self.metadata, self.directory)

    def test_source_path_cannot_escape_release_directory(self):
        self.metadata['originalSources']['dxvk']['asset'] = '../dxvk-source.tar.gz'
        with self.assertRaisesRegex(ValueError, 'source record'):
            publish.component_source_archives(self.metadata, self.directory)

    def test_upload_digest_delay_is_rechecked(self):
        pending = json.dumps({'assets': [{'name': 'runtime', 'digest': None, 'size': 42}]})
        ready = json.dumps({'assets': [{'name': 'runtime', 'digest': 'sha256:abc', 'size': 42}]})
        with patch.object(publish.subprocess, 'check_output', side_effect=[pending, ready]) as read, \
             patch.object(publish.time, 'sleep') as sleep:
            publish.verify_uploaded_asset(['gh', 'release'], 'runtime', 'abc', 42)
            self.assertEqual(read.call_count, 2)
            self.assertEqual(read.call_args.args[0], ['gh', 'api',
                'repos/taowen/wine/releases/tags/latest'])
            sleep.assert_called_once_with(2)

    def test_mismatched_upload_never_passes_verification(self):
        wrong = json.dumps({'assets': [{'name': 'runtime', 'digest': 'sha256:wrong', 'size': 42}]})
        with patch.object(publish.subprocess, 'check_output', return_value=wrong) as read, \
             patch.object(publish.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'pin unchanged'):
                publish.verify_uploaded_asset(['gh', 'release'], 'runtime', 'abc', 42)
            self.assertEqual(read.call_count, 6)


unittest.main()
