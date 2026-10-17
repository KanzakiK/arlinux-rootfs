import json
import hashlib
from pathlib import Path
import sys
import tempfile
import subprocess
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime/tools'))
import windows


class LatestRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.selection = Path(self.directory.name)/'rootfs/var/lib/arlinux/windows-runtime-latest.json'
        selector = patch.object(windows, 'LATEST_SELECTION', self.selection)
        selector.start()
        self.addCleanup(selector.stop)

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

    def test_api_rate_limit_uses_web_asset_digest(self):
        checksum = 'c' * 64
        html = ('<a href="/taowen/wine/releases/download/latest/arlinux-wine-bionic.tar.gz">runtime</a>'
                '<clipboard-copy aria-label="Copy to clipboard digest for arlinux-wine-bionic.tar.gz" '
                'value="sha256:' + checksum + '"></clipboard-copy>')
        with patch.object(windows.subprocess, 'run', side_effect=[
                subprocess.CalledProcessError(22, ['curl']),
                subprocess.CompletedProcess(['curl'], 0, stdout=html)]) as request:
            self.assertEqual(windows.latest_runtime(), (checksum,
                'https://github.com/taowen/wine/releases/download/latest/arlinux-wine-bionic.tar.gz'))
            self.assertIn('https://github.com/taowen/wine/releases/expanded_assets/latest',
                          request.call_args.args[0])

    def test_web_fallback_rejects_missing_wrong_or_ambiguous_digest(self):
        for html in ('', '<clipboard-copy value="sha256:' + 'a'*64 + '">',
                     '<a href="/taowen/wine/releases/download/latest/arlinux-wine-bionic.tar.gz">'
                     '<clipboard-copy aria-label="Copy to clipboard digest for arlinux-wine-bionic.tar.gz" value="bad">'):
            with patch.object(windows.subprocess, 'run') as request:
                request.return_value.stdout = html
                with self.assertRaises(ValueError):
                    windows.latest_runtime_web()

    def test_installed_latest_does_not_query_network_on_every_launch(self):
        self.selection.parent.mkdir(parents=True)
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / 'windows-downloads.tsv'
            manifest.write_text('Wine Bionic latest\t' + 'a' * 64 +
                '\thttps://github.com/taowen/wine/releases/download/latest/arlinux-wine-bionic.tar.gz\n')
            self.selection.write_text(json.dumps({'sha256': 'b' * 64,
                'checkedAt': time.time(), 'manifestSHA256': windows.digest(manifest)}))
            with patch.object(windows, 'MANIFEST', manifest), \
                 patch.object(windows, 'runtime', return_value=Path('/runtime/' + 'b' * 64)), \
                 patch.object(windows, 'latest_runtime') as request:
                windows.ensure_runtime()
                request.assert_not_called()

    def test_fresh_rootfs_replaces_stale_shared_runtime(self):
        old, current = 'a' * 64, 'b' * 64
        manifest = Path(self.directory.name)/'windows-downloads.tsv'
        manifest.write_text(f'Wine Bionic latest\t{old}\thttps://github.com/taowen/wine/releases/download/latest/arlinux-wine-bionic.tar.gz\n')
        with patch.object(windows, 'MANIFEST', manifest), \
             patch.object(windows, 'runtime', side_effect=[Path('/runtime')/old, Path('/runtime')/current]), \
             patch.object(windows, 'latest_runtime', return_value=(current, 'https://api.github.com/repos/taowen/wine/releases/assets/42')) as resolve, \
             patch.object(windows.shared, 'download', return_value=Path('/archive')), \
             patch.object(windows, 'install') as install:
            self.assertEqual(windows.ensure_runtime(), Path('/runtime')/current)
            resolve.assert_called_once()
            install.assert_called_once_with(Path('/archive'), current)
            selected = json.loads(self.selection.read_text())
            self.assertEqual(selected['sha256'], current)
            self.assertEqual(selected['manifestSHA256'], windows.digest(manifest))
            self.assertLess(abs(selected['checkedAt'] - time.time()), 5)

    def test_expired_or_changed_manifest_cache_rechecks_release(self):
        current = 'b' * 64
        self.selection.parent.mkdir(parents=True)
        manifest = Path(self.directory.name) / 'windows-downloads.tsv'
        manifest.write_text('Wine Bionic latest\t' + 'a' * 64 +
            '\thttps://github.com/taowen/wine/releases/download/latest/arlinux-wine-bionic.tar.gz\n')
        for checked, fingerprint in ((time.time() - 3601, windows.digest(manifest)),
                                     (time.time(), 'c' * 64)):
            self.selection.write_text(json.dumps({'sha256': current,
                'checkedAt': checked, 'manifestSHA256': fingerprint}))
            with patch.object(windows, 'MANIFEST', manifest), \
                 patch.object(windows, 'runtime', return_value=Path('/runtime') / current), \
                 patch.object(windows, 'validate'), \
                 patch.object(windows, 'latest_runtime', return_value=(current, 'https://example.test/runtime')) as request:
                self.assertEqual(windows.ensure_runtime(), Path('/runtime') / current)
                request.assert_called_once()

    def test_selected_instance_does_not_follow_other_instances_shared_pointer(self):
        selected = 'b' * 64
        self.selection.parent.mkdir(parents=True)
        manifest = Path(self.directory.name)/'windows-downloads.tsv'
        manifest.write_text('Wine Bionic latest\t'+'a'*64+'\thttps://github.com/taowen/wine/releases/download/latest/arlinux-wine-bionic.tar.gz\n')
        self.selection.write_text(json.dumps({'sha256': selected,
            'checkedAt': time.time(), 'manifestSHA256': windows.digest(manifest)}))
        with patch.object(windows, 'MANIFEST', manifest), \
             patch.object(windows, 'runtime', return_value=Path('/runtime')/selected) as runtime, \
             patch.object(windows, 'latest_runtime') as resolve:
            self.assertEqual(windows.ensure_runtime(), Path('/runtime')/selected)
            runtime.assert_called_once_with(selected)
            resolve.assert_not_called()

    def test_network_failure_on_fresh_rootfs_never_accepts_stale_shared_runtime(self):
        manifest = Path(self.directory.name)/'windows-downloads.tsv'
        manifest.write_text('Wine Bionic latest\t'+'a'*64+'\thttps://github.com/taowen/wine/releases/download/latest/arlinux-wine-bionic.tar.gz\n')
        with patch.object(windows, 'MANIFEST', manifest), \
             patch.object(windows, 'latest_runtime', side_effect=RuntimeError('offline')), \
             patch.object(windows, 'runtime') as runtime:
            with self.assertRaisesRegex(RuntimeError, 'offline'):
                windows.ensure_runtime()
            runtime.assert_not_called()
            self.assertFalse(self.selection.exists())

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
