"""Compiler aliases are hashed once, while later edits still invalidate caches."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools/build'))
import pipeline_cache as cache


class InventoryAliasTest(unittest.TestCase):
    def test_aliases_do_not_repeat_hashing_or_hide_later_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root/'clang'
            binary.write_bytes(b'compiler version one')
            os.link(binary, root/'clang-hardlink')
            (root/'clang++').symlink_to('clang')
            with patch.object(cache, 'digest', wraps=cache.digest) as hashes:
                first = cache.inventory(root)
                self.assertEqual(hashes.call_count, 1)
            binary.write_bytes(b'compiler version two')
            second = cache.inventory(root)
            self.assertNotEqual(first, second)
            self.assertEqual(second['clang']['sha256'], second['clang++']['target']['sha256'])
            self.assertEqual(second['clang']['sha256'], second['clang-hardlink']['sha256'])


if __name__ == '__main__':
    unittest.main()
