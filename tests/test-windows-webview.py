import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'runtime/tools'))
import windows_webview as webview


class WebViewTests(unittest.TestCase):
    def test_unrelated_game_and_redistributable_skip_browser(self):
        with patch.object(webview, 'ensure_runtime') as install:
            for app, exe in [('42', '/games/我的小鲨鱼.exe'), ('2758540', '/redist/setup.exe')]:
                env = {'SteamAppId': app}
                self.assertEqual(webview.prepare_game(Path('/wine'), Path('/prefix'), exe, env), env)
            install.assert_not_called()

    def test_game_preparation_keeps_identity_and_checks_registry_failures(self):
        env = {'SteamAppId': '2758540'}
        with patch.object(webview, 'ensure_runtime', return_value=Path('/browser')), \
             patch.object(webview.windows, 'host_path', return_value=Path('/private/browser')), \
             patch.object(webview.windows, 'run') as run:
            prepared = webview.prepare_game(Path('/wine'), Path('/prefix'), '/games/我的小鲨鱼.exe', env)
            self.assertEqual(prepared['SteamAppId'], '2758540')
            self.assertEqual(env, {'SteamAppId': '2758540'})
            self.assertEqual(prepared['WEBVIEW2_BROWSER_EXECUTABLE_FOLDER'], r'Z:\private\browser')
            self.assertIn('--use-angle=vulkan', prepared['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'])
            self.assertNotIn('--disable-gpu ', prepared['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'])
            self.assertEqual(run.call_count, 2)
            self.assertTrue(all(c.kwargs['check'] for c in run.call_args_list))
            run.side_effect = RuntimeError('registry failed')
            with self.assertRaises(RuntimeError):
                webview.prepare_game(Path('/wine'), Path('/prefix'), '/games/我的小鲨鱼.exe', env)

    def test_corrupted_cached_runtime_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'browser').mkdir()
            exe = root/'browser/msedgewebview2.exe'
            exe.write_bytes(b'vendor binary')
            record = dict(protocol=1, sha256='a'*64, browser='browser',
                          files={'browser/msedgewebview2.exe': webview.shared.digest(exe)})
            (root/'arlinux-runtime.json').write_text(json.dumps(record))
            self.assertEqual(webview.verified_browser(root, 'a'*64), root/'browser')
            exe.write_bytes(b'changed binary')
            with self.assertRaises(RuntimeError):
                webview.verified_browser(root, 'a'*64)


unittest.main()
