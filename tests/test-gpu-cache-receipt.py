"""Exercise the actual GPU receipt verifier against corrupted cached output."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/build'))
from pipeline_cache import inventory
ROOT=Path(__file__).resolve().parents[1]


class GpuReceiptTest(unittest.TestCase):
    def test_missing_wrong_and_modified_cache_is_rejected(self):
        code=(ROOT/'tools/build/linux-gpu.sh').read_text().split("<<'CACHE'\n",1)[1].split('\nCACHE',1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary); mesa=base/'mesa'; hybris=base/'hybris'
            mesa.mkdir(); hybris.mkdir()
            (mesa/'libGL.so').write_bytes(b'current GL')
            (hybris/'compat.so').write_bytes(b'current adapter')
            receipt=base/'receipt.json'
            def verify(identity='current'):
                return subprocess.run([sys.executable,'-c',code,str(ROOT),identity,
                                       str(receipt),str(mesa),str(hybris)],check=False).returncode
            self.assertEqual(verify(),1)
            receipt.write_text(json.dumps({'format':1,'inputs':'current',
                'outputs':{str(p):inventory(p) for p in (mesa,hybris)}}))
            self.assertEqual(verify(),0)
            self.assertEqual(verify('different source'),1)
            (hybris/'compat.so').write_bytes(b'corrupted')
            self.assertEqual(verify(),1)


if __name__ == '__main__':
    unittest.main()
