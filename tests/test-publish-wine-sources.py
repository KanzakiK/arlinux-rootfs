import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('publish', Path(__file__).resolve().parents[1] / 'tools/publish-wine-latest.py')
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.metadata = {'originalSources': {}}
        for name in ('wine', 'fex', 'dxvk'):
            path = self.directory / (name + '-source.tar.gz')
            path.write_bytes(name.encode())
            self.metadata['originalSources'][name] = {
                'asset': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def test_complete_sources_are_returned_for_upload(self):
        self.assertEqual(len(publish.component_source_archives(self.metadata, self.directory)), 3)

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


unittest.main()
