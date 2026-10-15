import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime/tools'))
import shared
import steam


class DownloadTests(unittest.TestCase):
    def test_client_manifest_falls_back_to_official_cdn(self):
        with patch.object(steam.subprocess, 'run', side_effect=[
                subprocess.CalledProcessError(22, 'curl'), None]) as request:
            steam.fetch(steam.CDN + 'steam_client_linuxarm64', Path('/manifest'))
            self.assertEqual(request.call_args_list[0].args[0][-1], steam.CLIENT_CDNS[0] + 'steam_client_linuxarm64')
            self.assertEqual(request.call_args_list[1].args[0][-1], steam.CLIENT_CDNS[1] + 'steam_client_linuxarm64')

    def test_fastest_valid_transfer_wins_over_fast_error(self):
        urls = steam.client_sources(steam.CDN + 'client.zip')
        with patch.object(shared.Path, 'is_file', return_value=True), \
             patch.object(shared.Path, 'read_text', return_value='zh'), \
             patch.object(shared.subprocess, 'run') as request:
            def probe(command, **kwargs):
                response = {urls[0]: (0, '200 262144 20000'),
                            urls[1]: (28, '206 60000 30000'),
                            urls[2]: (22, '403 262144 90000')}
                code, output = response[command[-1]]
                return subprocess.CompletedProcess(command, code, output, '')
            request.side_effect = probe
            self.assertEqual(shared.ranked_sources(urls), [urls[1], urls[0], urls[2]])

    def test_corrupt_cdn_payload_does_not_enter_cache(self):
        data = b'valid Valve package'
        checksum = hashlib.sha256(data).hexdigest()
        urls = steam.client_sources(steam.CDN + 'client.zip')[:2]
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(shared, 'ROOT', Path(directory)), \
             patch.object(shared, 'ranked_sources', side_effect=lambda sources: sources), \
             patch.object(shared.subprocess, 'run') as request:
            def fetch(command, **kwargs):
                Path(command[command.index('-o') + 1]).write_bytes(
                    b'bad CDN response' if command[-1] == urls[0] else data)
            request.side_effect = fetch
            target = shared.download(urls, checksum, '.zip')
            self.assertEqual(target.read_bytes(), data)
            self.assertEqual(request.call_count, 2)
            self.assertFalse(Path(str(target) + '.part').exists())


if __name__ == '__main__':
    unittest.main()
