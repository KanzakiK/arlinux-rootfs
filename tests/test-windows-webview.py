import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'runtime/tools'))
import windows_webview as webview


class WebViewTests(unittest.TestCase):
    def test_missing_browser_is_an_error_not_a_test_shortcut(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(webview, 'ensure_runtime', return_value=Path(temp)/'missing'):
                with self.assertRaisesRegex(RuntimeError, 'directory is missing'):
                    webview.install_into_prefix(Path(temp)/'prefix')

    def test_concurrent_prefix_publication_and_corrupt_copy_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            browser = base/'vendor/runtime'
            browser.mkdir(parents=True)
            (browser/'msedgewebview2.exe').write_bytes(b'vendor executable')
            (browser/'resource.pak').write_bytes(b'resources')
            prefix = base/'prefix'
            with patch.object(webview, 'ensure_runtime', return_value=browser):
                with ThreadPoolExecutor(max_workers=2) as workers:
                    installed = list(workers.map(webview.install_into_prefix, [prefix, prefix]))
                self.assertEqual(installed[0], installed[1])
                self.assertEqual((installed[0]/'resource.pak').read_bytes(), b'resources')
                self.assertFalse(list(installed[0].parent.glob('.install-*')))
                (installed[0]/'resource.pak').unlink()
                with self.assertRaisesRegex(RuntimeError, 'damaged'):
                    webview.install_into_prefix(prefix)

    def test_global_preparation_is_independent_of_game_identity(self):
        with patch.object(webview, 'install_into_prefix', return_value=Path('/prefix/pfx/drive_c/Program Files/Microsoft/EdgeWebView/Application/runtime')), \
             patch.object(webview.windows, 'run') as run:
            outputs = []
            for env in ({}, {'SteamAppId': '2758540'}, {'SteamAppId': '42'}):
                before = dict(env)
                prepared = webview.prepare(Path('/wine'), Path('/prefix'), env)
                outputs.append({key: value for key, value in prepared.items() if key.startswith('WEBVIEW2_')})
                self.assertEqual(env, before)
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(outputs[1], outputs[2])
            self.assertEqual(prepared['WEBVIEW2_BROWSER_EXECUTABLE_FOLDER'], r'C:\Program Files\Microsoft\EdgeWebView\Application\runtime')
            self.assertIn('--use-angle=vulkan', prepared['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'])
            self.assertNotIn('--disable-gpu ', prepared['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'])
            self.assertEqual(run.call_count, 12)
            self.assertTrue(all(c.kwargs['check'] for c in run.call_args_list))
            policy_calls = [call.args[3] for call in run.call_args_list if 'Policies' in call.args[3][1]]
            self.assertTrue(all(args[args.index('/v') + 1] == '*' for args in policy_calls))
            self.assertEqual({args[-1] for args in policy_calls}, {'/reg:64', '/reg:32'})
            run.side_effect = RuntimeError('registry failed')
            with self.assertRaises(RuntimeError):
                webview.prepare(Path('/wine'), Path('/prefix'), {})

    def test_browser_path_does_not_expose_long_android_prefix(self):
        prefix = Path('/data/user/0/io.taowen.arlinux.dev/files/instances/yibu-test/home/'
                      '.local/share/arlinux/windows-bionic/prefix')
        browser = prefix / 'pfx/drive_c/Program Files/Microsoft/EdgeWebView/Application/runtime'
        self.assertEqual(webview.browser_windows_path(prefix, browser),
                         r'C:\Program Files\Microsoft\EdgeWebView\Application\runtime')
        with self.assertRaises(ValueError):
            webview.browser_windows_path(prefix, Path('/outside/runtime'))

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
