import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root/'runtime/tools'))
spec = importlib.util.spec_from_file_location('steamworks', root/'runtime/tools/steamworks.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SteamworksTest(unittest.TestCase):
    def test_launch_lifetime_and_fresh_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            payload = base/'payload'
            for name in ['aarch64-windows/steam.exe', 'aarch64-unix/lsteamclient.so',
                         'i386-windows/lsteamclient.dll', 'x86_64-windows/lsteamclient.dll']:
                file = payload/name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(name.encode())
            server = payload/'lsteambridge-server'
            server.write_text('#!/usr/bin/python3\nimport os,socket\n'
                              's=socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET)\n'
                              's.bind(os.environ["LSTEAM_BRIDGE_SOCKET"])\n'
                              'os.chmod(os.environ["LSTEAM_BRIDGE_SOCKET"],0o600)\n'
                              's.listen(8)\n'
                              'while True:\n c,_=s.accept();c.close()\n')
            server.chmod(0o755)
            library = base/'steam/steamrtarm64/steamclient.so'
            library.parent.mkdir(parents=True)
            library.touch()
            runtime = base/'runtime'
            runtime.mkdir()
            prefix = base/'fresh-prefix'
            calls = []
            with patch.object(module, 'PAYLOAD', payload), patch.object(module.windows, 'initialize',
                    side_effect=lambda *args: calls.append(args)), patch.dict(os.environ, {
                        'XDG_RUNTIME_DIR': str(runtime),
                        'STEAM_COMPAT_CLIENT_INSTALL_PATH': str(base/'steam')}):
                with module.session(base/'wine', prefix, {'SteamAppId': '891040'}) as launcher:
                    self.assertEqual(launcher.read_bytes(), b'aarch64-windows/steam.exe')
                    self.assertTrue((runtime/'steamworks/891040.sock').is_socket())
                    self.assertEqual((launcher.parent/'steamclient.dll').read_bytes(), b'i386-windows/lsteamclient.dll')
                    self.assertEqual((launcher.parent/'steamclient64.dll').read_bytes(), b'x86_64-windows/lsteamclient.dll')
                self.assertFalse((runtime/'steamworks/891040.sock').exists())
                self.assertEqual(len(calls), 1)
                with self.assertRaisesRegex(RuntimeError, 'game failed'):
                    with module.session(base/'wine', prefix, {'SteamAppId': '891040'}):
                        raise RuntimeError('game failed')
                self.assertFalse((runtime/'steamworks/891040.sock').exists())

    def test_invalid_identity_never_starts_a_service(self):
        for appid in ['', '0', '../891040', '１２３']:
            with self.assertRaises(ValueError):
                with module.session(Path('/wine'), Path('/prefix'), {'SteamAppId': appid}):
                    self.fail('invalid identity accepted')


unittest.main()
