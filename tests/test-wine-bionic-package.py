"""Reject stale Zink builds and verify reproducible, checksum-checked archives."""
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

    def graphics(self, xmlconfig='enabled'):
        prefix = self.base / 'graphics'
        libraries = {}
        for name in ['lib/dri/zink_dri.so', 'lib/dri/libdril_dri.so']:
            path = prefix / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
            libraries[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        (prefix / 'arlinux-bionic-graphics.json').write_text(json.dumps({
            'protocol': 1, 'openglDriver': 'zink', 'xmlconfig': xmlconfig,
            'libraries': libraries,
        }))
        return prefix

    def runtime(self):
        root = self.base / 'runtime'
        binary = root / 'files/bin/wine'
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b'tested runtime')
        (root / 'bionic-runtime.json').write_text(json.dumps({
            'files': {'files/bin/wine': hashlib.sha256(binary.read_bytes()).hexdigest()},
        }))
        return root, binary

    def test_missing_build_record_requires_rebuild(self):
        with self.assertRaisesRegex(RuntimeError, 'Rebuild graphics'):
            package.verify_zink(self.base)

    def test_disabled_xmlconfig_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'xmlconfig=enabled'):
            package.verify_zink(self.graphics('disabled'))

    def test_replaced_library_rejected(self):
        prefix = self.graphics()
        (prefix / 'lib/dri/zink_dri.so').write_bytes(b'stale build')
        with self.assertRaisesRegex(RuntimeError, 'does not match'):
            package.verify_zink(prefix)

    def test_enabled_matching_build_accepted(self):
        self.assertEqual(package.verify_zink(self.graphics())['xmlconfig'], 'enabled')

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
