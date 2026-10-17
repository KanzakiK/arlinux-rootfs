import subprocess
import hashlib
import json
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime/tools'))
import shared

class GithubRoutes(unittest.TestCase):
    def test_opencode_metadata_uses_chinese_routes_and_validates_digest(self):
        url = 'https://github.com/anomalyco/opencode/releases/download/v1.18.31/opencode-desktop-linux-arm64.deb'
        checksum = 'a' * 64
        def request(command, **kwargs):
            self.assertNotIn('--insecure', command)
            self.assertEqual(command[command.index('--max-time') + 1], '5')
            # A fast but wrong direct response must not beat a verified route.
            accelerated = '--connect-to' in command
            payload = {'assets': [{'name': 'opencode-desktop-linux-arm64.deb',
                'id': 123, 'digest': 'sha256:' + (checksum if accelerated else 'b' * 64)}]}
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), '')
        with patch.object(shared.Path, 'is_file', return_value=True), \
             patch.object(shared.Path, 'read_text', return_value='zh'), \
             patch.object(shared.subprocess, 'run', side_effect=request):
            self.assertEqual(shared.github_asset(url, checksum),
                'https://api.github.com/repos/anomalyco/opencode/releases/assets/123')
        with patch.object(shared.Path, 'is_file', return_value=True), \
             patch.object(shared.Path, 'read_text', return_value='other'), \
             patch.object(shared.subprocess, 'run', side_effect=request) as run:
            self.assertIsNone(shared.github_asset(url, checksum))
            self.assertEqual(run.call_count, 1)

    def test_successful_asset_does_not_probe_unused_web_fallback(self):
        data = b'opencode vendor package'
        checksum = hashlib.sha256(data).hexdigest()
        url = 'https://github.com/anomalyco/opencode/releases/download/v1/app.deb'
        api = 'https://api.github.com/repos/anomalyco/opencode/releases/assets/123'
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(shared, 'ROOT', Path(directory)), \
             patch.object(shared, 'github_asset', return_value=api), \
             patch.object(shared, 'github_routes', return_value=[[]]) as routes, \
             patch.object(shared.subprocess, 'run') as run:
            run.side_effect = lambda command, **kwargs: Path(command[command.index('-o') + 1]).write_bytes(data)
            self.assertEqual(shared.download(url, checksum, '.deb').read_bytes(), data)
            routes.assert_called_once_with(api, ['-H', 'Accept: application/octet-stream'])

    def test_non_chinese_and_non_github_do_not_probe(self):
        with patch.object(shared.Path,'is_file',return_value=True), patch.object(shared.Path,'read_text',return_value='en'), patch.object(shared.subprocess,'run') as run:
            self.assertEqual(shared.github_routes('https://api.github.com/release',[]),[[]])
            self.assertFalse(run.called)
        with patch.object(shared.subprocess,'run') as run:
            self.assertEqual(shared.github_routes('https://official.example/download',[]),[[]])
            self.assertFalse(run.called)

    def test_rank_real_transfer_keep_tls_host_and_direct_fallback(self):
        url='https://api.github.com/repos/owner/repo/releases/assets/123'
        headers=['-H','Accept: application/octet-stream']
        with patch.object(shared.Path,'is_file',return_value=True), patch.object(shared.Path,'read_text',return_value='zh'), patch.object(shared.subprocess,'run') as run:
            def probe(command,**kwargs):
                self.assertEqual(command[-1],url)
                self.assertNotIn('--range', command)
                self.assertEqual(command[command.index('--max-time') + 1], '4')
                self.assertEqual(kwargs['timeout'], 5)
                self.assertNotIn('-k',command)
                self.assertNotIn('--insecure',command)
                self.assertIn('Accept: application/octet-stream',command)
                if '--connect-to' not in command:
                    output,code='206 262144 1000',0
                elif 'api.github.com:443:2.ghapi.steam302.xyz:443' in command:
                    # A bounded full-response probe normally ends with curl 28.
                    output,code='200 262144 900000',28
                elif 'api.github.com:443:3.ghapi.steam302.xyz:443' in command:
                    output,code='403 262144 900000',22
                else:
                    output,code='000 0 0',60
                return subprocess.CompletedProcess(command,code,output,'')
            run.side_effect=probe
            routes=shared.github_routes(url,headers)
            self.assertIn('api.github.com:443:2.ghapi.steam302.xyz:443',routes[0])
            self.assertEqual(routes[1],headers)
            self.assertEqual(routes[0][routes[0].index('--speed-limit') + 1], '225000')
            self.assertEqual(routes[0][routes[0].index('--speed-time') + 1], '15')
            self.assertEqual(routes[0][routes[0].index('--retry') + 1], '0')
            self.assertEqual(routes[-1], headers)
            self.assertEqual(len(routes),6)
            self.assertEqual(run.call_count,5)

if __name__=='__main__':unittest.main()
