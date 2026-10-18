"""FEX provenance follows the pinned source, never a stale hardcoded revision."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
spec=importlib.util.spec_from_file_location('package',ROOT/'tools/package-wine-bionic.py')
package=importlib.util.module_from_spec(spec);spec.loader.exec_module(package)


class FexPinTest(unittest.TestCase):
    def test_matching_source_is_required_after_revision_updates(self):
        expected='b'*40
        with patch.object(package.subprocess,'check_output',return_value='160000 commit '+expected+'\tFEX\n'):
            self.assertEqual(package.verify_fex_revision({'fex_commit':expected}),expected)
            with self.assertRaisesRegex(RuntimeError,'pinned FEX source'):
                package.verify_fex_revision({'fex_commit':'a'*40})


if __name__ == '__main__':
    unittest.main()
