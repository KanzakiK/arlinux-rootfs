"""Verify reproducible, checksum-checked runtime archives."""
import hashlib
import importlib.util
import json
from pathlib import Path
import os
import sys
import tarfile
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('package_wine_bionic', TOOLS / 'package-wine-bionic.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def runtime(self):
        root = self.base / 'runtime'
        binary = root / 'files/bin/wine'
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b'tested runtime')
        (root / 'bionic-runtime.json').write_text(json.dumps({
            'files': {'files/bin/wine': hashlib.sha256(binary.read_bytes()).hexdigest()},
        }))
        return root, binary

    def test_archive_reproducible_and_extractable(self):
        root, binary = self.runtime()
        first, second = self.base / 'first.tar.gz', self.base / 'second.tar.gz'
        checksum = package.archive_runtime(root, first)
        os.utime(binary, (1234567890, 1234567890))
        self.assertEqual(package.archive_runtime(root, second), checksum)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with tarfile.open(first) as bundle:
            self.assertEqual(bundle.extractfile('files/bin/wine').read(), binary.read_bytes())
        self.assertEqual(first.with_name(first.name + '.sha256').read_text(),
                         checksum + '  first.tar.gz\n')

    def test_tampered_runtime_never_archived(self):
        root, binary = self.runtime()
        binary.write_bytes(b'changed after manifest')
        archive = self.base / 'bad.tar.gz'
        with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
            package.archive_runtime(root, archive)
        self.assertFalse(archive.exists())

    def test_existing_archive_preserved(self):
        root, _ = self.runtime()
        archive = self.base / 'existing.tar.gz'
        archive.write_bytes(b'previous release')
        with self.assertRaises(FileExistsError):
            package.archive_runtime(root, archive)
        self.assertEqual(archive.read_bytes(), b'previous release')


if __name__ == '__main__':
    unittest.main()
