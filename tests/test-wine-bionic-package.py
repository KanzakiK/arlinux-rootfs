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

    def components(self):
        pe = self.base / 'pe'
        pe.mkdir()
        patch = TOOLS / 'patches/wine-dcomp-content-lifetime.patch'
        (pe/'arlinux-dcomp.json').write_text(json.dumps({
            'commit': '318eda0d8fa08ee94faadf6dc5ad85870339b327',
            'patchSHA256': hashlib.sha256(patch.read_bytes()).hexdigest()}))
        (pe/'arlinux-vkd3d.json').write_bytes(
            (TOOLS/'patches/wine-staging-vkd3d/manifest.json').read_bytes())
        for arch in ('aarch64', 'i386', 'x86_64'):
            directory = pe/'files/lib/wine'/(arch+'-windows')
            directory.mkdir(parents=True)
            for name in ('dcomp', 'd3d12', 'd3d12core'):
                (directory/(name+'.dll')).write_bytes(b'MZ')
        return pe

    def test_complete_component_build_accepted(self):
        self.assertIn('arlinux-dcomp.json', package.verify_components(self.components()))

    def test_old_pe_package_without_dcomp_rejected(self):
        pe = self.components()
        (pe/'arlinux-dcomp.json').unlink()
        with self.assertRaisesRegex(RuntimeError, 'missing required component'):
            package.verify_components(pe)

    def test_stale_dcomp_patch_record_rejected(self):
        pe = self.components()
        (pe/'arlinux-dcomp.json').write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'DirectComposition fixes'):
            package.verify_components(pe)

    def test_missing_architecture_module_rejected(self):
        pe = self.components()
        (pe/'files/lib/wine/i386-windows/dcomp.dll').unlink()
        with self.assertRaisesRegex(RuntimeError, 'i386/dcomp'):
            package.verify_components(pe)

    def test_stale_vkd3d_record_rejected(self):
        pe = self.components()
        (pe/'arlinux-vkd3d.json').write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'VKD3D refresh'):
            package.verify_components(pe)

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
