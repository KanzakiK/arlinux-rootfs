"""Exercise schema compilation while sealing the package cache with new settings."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
spec = importlib.util.spec_from_file_location('device', Path(sys.path[0]) / 'seal-rootfs.py')
device = importlib.util.module_from_spec(spec)
spec.loader.exec_module(device)


def tar_bytes(files):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w') as tar:
        for name, data in files.items():
            item = tarfile.TarInfo(name)
            item.mode = 0o644
            item.size = len(data)
            tar.addfile(item, io.BytesIO(data))
    return out.getvalue()


class SchemaSealTest(unittest.TestCase):
    def test_current_override_keeps_installed_package_schemas(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix = 'usr/share/glib-2.0/schemas/'
            override = b"[org.freedesktop.ibus.general]\npreload-engines=['arlinux-hosted']\n"
            applications = {
                'usr/lib/arlinux/shared.py': b'storage = "files/arlinux-shared"\n',
                'usr/lib/arlinux/windows.py': b'host_shared = "files/arlinux-shared"\n',
                'usr/lib/arlinux/guest/windows-downloads.tsv': b'current vendor pin\n',
            }
            seed_tar = tar_bytes({
                **applications,
                'usr/bin/arlinux-opencode': b'launcher',
                prefix + '90-arlinux-ibus.gschema.override': override,
                prefix + 'gschemas.compiled': b'incomplete seed database',
            })
            entries = {
                'rootfs.tar.zst': subprocess.check_output(['zstd', '-q', '-c'], input=seed_tar),
                'rootfs-seed-id': b'old\n',
                'guest/first-boot.sh': b'#!/bin/sh\n',
                'gpu-qualcomm.tar.zst': subprocess.check_output(['zstd', '-q', '-c'], input=tar_bytes({})),
                'gpu-generic.tar.zst': subprocess.check_output(['zstd', '-q', '-c'], input=tar_bytes({})),
            }
            seed, snapshot, output = root/'seed.zip', root/'packages.tar', root/'output.zip'
            with zipfile.ZipFile(seed, 'w') as z:
                for name, data in entries.items():
                    z.writestr(name, data)
                z.writestr('manifest.json', json.dumps({'distributionId': 'yibu', 'files': {
                    name: hashlib.sha256(data).hexdigest() for name, data in entries.items()}}))
            snapshot.write_bytes(tar_bytes({
                **{name: b'obsolete application runtime\n' for name in applications},
                'usr/lib/arlinux/removed-backend.py': b'obsolete backend\n',
                prefix + 'org.freedesktop.ibus.gschema.xml': b'''<schemalist><schema id="org.freedesktop.ibus.general" path="/desktop/ibus/general/"><key name="preload-engines" type="as"><default>[]</default></key></schema></schemalist>''',
                prefix + 'org.arlinux.package.gschema.xml': b'''<schemalist><schema id="org.arlinux.package" path="/arlinux/package/"><key name="enabled" type="b"><default>true</default></key></schema></schemalist>''',
                prefix + '90-arlinux-ibus.gschema.override': b'[org.freedesktop.ibus.general]\npreload-engines=[]\n',
                prefix + 'gschemas.compiled': b'outdated cache database',
            }))
            with patch.object(device, 'verify'), patch.object(device, 'validate_snapshot'), patch.object(device, 'required_snapshot_files', return_value=set()):
                device.seal(seed, snapshot, output)
            with zipfile.ZipFile(output) as z:
                raw = subprocess.check_output(['zstd', '-q', '-dc'], input=z.read('rootfs.tar.zst'))
            with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
                compiled = tar.extractfile('./' + prefix + 'gschemas.compiled').read()
                self.assertEqual(tar.extractfile('./' + prefix + '90-arlinux-ibus.gschema.override').read(), override)
                for name, content in applications.items():
                    self.assertEqual(tar.extractfile('./' + name).read(), content)
                self.assertNotIn('./usr/lib/arlinux/removed-backend.py', tar.getnames())
            (root/'gschemas.compiled').write_bytes(compiled)
            env = dict(os.environ, GSETTINGS_BACKEND='memory')
            def get(schema, name):
                return subprocess.check_output(['gsettings', '--schemadir', str(root), 'get', schema, name], env=env, text=True).strip()
            self.assertEqual(get('org.freedesktop.ibus.general', 'preload-engines'), "['arlinux-hosted']")
            self.assertEqual(get('org.arlinux.package', 'enabled'), 'true')


if __name__ == '__main__':
    unittest.main()
