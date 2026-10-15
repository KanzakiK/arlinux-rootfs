import json
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime/tools'))
import windows


class LatestRuntimeTests(unittest.TestCase):
    def test_clean_store_resolves_current_release_instead_of_apk_pin(self):
        old, current = 'a' * 64, 'b' * 64
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / 'windows-downloads.tsv'
            manifest.write_text(f'Wine Bionic latest\t{old}\thttps://github.com/taowen/wine/releases/download/latest/arlinux-wine-bionic.tar.gz\n')
            asset = f'https://api.github.com/repos/taowen/wine/releases/assets/42'
            response = json.dumps({'assets': [{'name': 'arlinux-wine-bionic.tar.gz',
                'id': 42, 'digest': 'sha256:' + current, 'state': 'uploaded'}]})
            with patch.object(windows, 'MANIFEST', manifest), \
                 patch.object(windows, 'runtime', side_effect=[FileNotFoundError(), Path('/runtime')]), \
                 patch.object(windows.subprocess, 'run') as request, \
                 patch.object(windows.shared, 'download', return_value=Path('/archive')) as download, \
                 patch.object(windows, 'install') as install:
                request.return_value.stdout = response
                self.assertEqual(windows.ensure_runtime(), Path('/runtime'))
                download.assert_called_once_with(asset, current, '.tar.gz')
                install.assert_called_once_with(Path('/archive'), current)

    def test_incomplete_latest_does_not_fall_back_to_old_pin(self):
        with patch.object(windows.subprocess, 'run') as request:
            for asset in ({}, {'name': 'arlinux-wine-bionic.tar.gz', 'id': 42,
                              'state': 'uploaded', 'digest': None}):
                request.return_value.stdout = json.dumps({'assets': [asset]})
                with self.assertRaises(ValueError):
                    windows.latest_runtime()

    def test_installed_latest_does_not_query_network_on_every_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / 'windows-downloads.tsv'
            manifest.write_text('Wine Bionic latest\t' + 'a' * 64 +
                '\thttps://github.com/taowen/wine/releases/download/latest/arlinux-wine-bionic.tar.gz\n')
            with patch.object(windows, 'MANIFEST', manifest), \
                 patch.object(windows, 'runtime', return_value=Path('/runtime/' + 'b' * 64)), \
                 patch.object(windows, 'latest_runtime') as request:
                windows.ensure_runtime()
                request.assert_not_called()

    def test_asset_api_download_requests_binary_and_checks_digest(self):
        data = b'tested runtime archive'
        checksum = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            def fetch(command, **kwargs):
                self.assertIn('Accept: application/octet-stream', command)
                Path(command[command.index('-o') + 1]).write_bytes(data)
            with patch.object(windows.shared, 'ROOT', Path(directory)), \
                 patch.object(windows.shared.subprocess, 'run', side_effect=fetch):
                result = windows.shared.download(
                    'https://api.github.com/repos/taowen/wine/releases/assets/42', checksum, '.tar.gz')
                self.assertEqual(result.read_bytes(), data)


if __name__ == '__main__':
    unittest.main()
