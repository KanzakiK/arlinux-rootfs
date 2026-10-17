import subprocess
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime/tools'))
import shared

class GithubRoutes(unittest.TestCase):
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
                self.assertNotIn('-k',command)
                self.assertNotIn('--insecure',command)
                self.assertIn('Accept: application/octet-stream',command)
                if '--connect-to' not in command:
                    output,code='206 262144 1000',0
                elif 'api.github.com:443:2.ghapi.steam302.xyz:443' in command:
                    output,code='206 262144 9000',0
                elif 'api.github.com:443:3.ghapi.steam302.xyz:443' in command:
                    output,code='403 262144 900000',22
                else:
                    output,code='000 0 0',60
                return subprocess.CompletedProcess(command,code,output,'')
            run.side_effect=probe
            routes=shared.github_routes(url,headers)
            self.assertIn('api.github.com:443:2.ghapi.steam302.xyz:443',routes[0])
            self.assertEqual(routes[1],headers)
            self.assertEqual(len(routes),5)
            self.assertEqual(run.call_count,5)

if __name__=='__main__':unittest.main()
