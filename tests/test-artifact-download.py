"""Exercise resumable SHA-256 downloads against a deliberately truncated server."""
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/build'))
from artifact_download import download


class DownloadTest(unittest.TestCase):
    def test_truncated_response_resumes_and_corrupt_cache_is_replaced(self):
        data=b'validated immutable build input\n'*1000
        expected=hashlib.sha256(data).hexdigest()
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                range_=self.headers.get('Range','')
                requests.append(range_)
                start=int(range_[6:-1]) if range_ else 0
                self.send_response(206 if range_ else 200)
                self.send_header('Content-Length',str(len(data)-start))
                if range_:self.send_header('Content-Range',f'bytes {start}-{len(data)-1}/{len(data)}')
                self.end_headers()
                self.wfile.write(data[start:start+10000] if len(requests)==1 else data[start:])
                self.close_connection=True
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temporary,patch('artifact_download.time.sleep'):
                output=Path(temporary)/'vendor.deb'
                url=f'http://127.0.0.1:{server.server_port}/vendor.deb'
                download(url,output,expected)
                self.assertEqual(requests,['','bytes=10000-'])
                self.assertEqual(output.read_bytes(),data)
                download(url,output,expected)
                self.assertEqual(len(requests),2)
                output.write_bytes(b'corrupt')
                download(url,output,expected)
                self.assertEqual(requests[-2:],['bytes=7-',''])
                self.assertEqual(output.read_bytes(),data)
        finally:
            server.shutdown()
            server.server_close()


if __name__=='__main__':unittest.main()
