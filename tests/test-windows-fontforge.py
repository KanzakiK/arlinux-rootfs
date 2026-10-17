import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime/tools'))
import windows_apps as apps


class FontForgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.storage = Path(self.temp.name) / 'windows'
        self.prefix = self.storage / 'prefix'
        self.application = self.prefix / 'pfx/drive_c/Program Files (x86)/FontForgeBuilds'
        for target, value in [('storage', self.storage), ('instance_prefix', self.prefix),
                              ('ensure_runtime', Path('/runtime')), ('environment', {})]:
            mock = patch.object(apps.windows, target, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        mock = patch.dict('os.environ', {'XDG_CACHE_HOME': str(Path(self.temp.name) / 'cache')})
        mock.start()
        self.addCleanup(mock.stop)

    def installed(self, *args, **kwargs):
        (self.application / 'bin').mkdir(parents=True, exist_ok=True)
        (self.application / 'bin/fontforge.exe').write_bytes(b'fontforge')
        wrapper = self.application / 'run_fontforge.exe'
        wrapper.write_bytes(b'wrapper')
        return wrapper

    def test_first_click_installs_without_prompt_and_next_click_skips_setup(self):
        with patch.object(apps, 'consent') as consent, \
             patch.object(apps, 'download', return_value=Path('/cache/setup.exe')) as download, \
             patch.object(apps.windows, 'initialize'), \
             patch.object(apps.windows, 'run', side_effect=self.installed) as run:
            executable, prefix, _ = apps.prepare('fontforge')
            self.assertEqual(executable, self.application / 'run_fontforge.exe')
            self.assertEqual(prefix, self.prefix)
            run.assert_called_once()
            self.assertEqual(run.call_args.args[3],
                             ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-'])
            download.assert_called_once_with('fontforge')
            consent.assert_not_called()
            marker = self.storage / 'apps/fontforge/installed.json'
            self.assertTrue((self.storage / json.loads(marker.read_text())['executable']).is_file())
            self.assertEqual(apps.prepare('fontforge')[0], executable)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(download.call_count, 1)

    def test_manual_install_launches_without_marker_or_download(self):
        wrapper = self.installed()
        with patch.object(apps, 'download') as download:
            self.assertEqual(apps.prepare('fontforge')[0], wrapper)
            download.assert_not_called()

    def test_incomplete_install_is_not_marked_ready_and_retries(self):
        self.application.mkdir(parents=True)
        (self.application / 'run_fontforge.exe').write_bytes(b'wrapper only')
        with patch.object(apps, 'download', return_value=Path('/cache/setup.exe')), \
             patch.object(apps.windows, 'initialize'), \
             patch.object(apps.windows, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'did not create'):
                apps.prepare('fontforge')
            self.assertFalse((self.storage / 'apps/fontforge/installed.json').exists())
            run.side_effect = self.installed
            self.assertTrue(apps.prepare('fontforge')[0].is_file())

    def test_removed_application_reinstalls_even_with_old_marker(self):
        marker = self.storage / 'apps/fontforge/installed.json'
        marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({'executable': 'no-longer-installed.exe'}))
        with patch.object(apps, 'download', return_value=Path('/cache/setup.exe')), \
             patch.object(apps.windows, 'initialize'), \
             patch.object(apps.windows, 'run', side_effect=self.installed) as run:
            self.assertTrue(apps.prepare('fontforge')[0].is_file())
            run.assert_called_once()


unittest.main()
