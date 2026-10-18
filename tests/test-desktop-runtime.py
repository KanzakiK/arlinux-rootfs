"""Regression coverage for current-source and build-cache receipt rejection."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile

import zstandard


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1]/'tools/build'/(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime = load('desktop-runtime')
audit = load('verify-webview-store-bundle')


class SnapshotTest(unittest.TestCase):
    def test_current_sources_and_exact_receipt_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            framework = root / 'framework'
            sources = {
                'runtime/tools/shared.py': b'current downloader',
                'runtime/tools/opencode.py': b'current opencode',
                'runtime/tools/windows_apps.py': b'current fontforge installer',
                'runtime/tools/fontforge.png': b'icon',
                'runtime/tools/arlinux-fontforge.desktop': b'desktop entry',
                'runtime/tools/windows-downloads.tsv': b'current public wine pin',
                'distributions/yibu/guest/first-boot.sh': b'current first boot',
                'distributions/yibu/guest/icons/test.svg': b'guest icon',
                'tools/arlinux-app-data/hosted-ime.py': b'current hosted input',
                'tools/arlinux-app-data/accessibility-session.sh': b'current accessibility session',
                'tools/arlinux-app-data/arlinux-hosted.xml': b'current IBus component',
            }
            for name, contents in sources.items():
                path = framework / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(contents)
            files = {name: b'compiled runtime' for name in audit.REQUIRED_RUNTIME |
                     {'usr/bin/apt-get', 'usr/bin/dpkg', 'usr/bin/dpkg-deb', 'usr/bin/python3'}}
            files.update({name: path.read_bytes() for name, path in runtime.runtime_files(framework).items()})
            content = io.BytesIO()
            with tarfile.open(fileobj=content, mode='w') as archive:
                for name, data in files.items():
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
            entries = {'rootfs.tar.zst': zstandard.ZstdCompressor().compress(content.getvalue()),
                       'offline-desktop': b'1\n', 'rootfs-seed-id': b'current\n'}
            entries.update({name: path.read_bytes() for name, path in runtime.bundle_files(framework).items()})
            for name, path in runtime.runtime_files(framework).items():
                if name.startswith('usr/lib/arlinux/guest/'):
                    entries[name.removeprefix('usr/lib/arlinux/')] = path.read_bytes()
            manifest = {'files': {name: hashlib.sha256(data).hexdigest() for name, data in entries.items()}}
            output = root / 'default.zip'
            with zipfile.ZipFile(output, 'w') as bundle:
                for name, data in entries.items(): bundle.writestr(name, data)
                bundle.writestr('manifest.json', json.dumps(manifest))
            with contextlib.redirect_stdout(io.StringIO()): audit.verify(output, framework)
            receipt = root / 'default.json'
            checksum = hashlib.sha256(output.read_bytes()).hexdigest()
            record = {'format': 1, 'desktopSha256': checksum, 'stages': {
                'desktop': {'inputs': 'a' * 64, 'outputs': {'default.zip': {'sha256': checksum}}}}}
            receipt.write_text(json.dumps(record))
            with contextlib.redirect_stdout(io.StringIO()):
                audit.verify(output, framework, receipt)
            record['stages']['desktop']['outputs']['default.zip']['sha256'] = 'wrong artifact'
            receipt.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, 'build-cache receipt'):
                audit.verify(output, framework, receipt)
            with self.assertRaises(FileNotFoundError):
                audit.verify(output, framework, root / 'missing-receipt.json')
            session = framework / 'tools/arlinux-app-data/accessibility-session.sh'
            session.write_bytes(b'newer session')
            with self.assertRaisesRegex(ValueError, 'stale installation asset'):
                audit.verify(output, framework)
            session.write_bytes(sources['tools/arlinux-app-data/accessibility-session.sh'])
            (framework / 'runtime/tools/opencode.py').write_bytes(b'newer change')
            with self.assertRaisesRegex(ValueError, 'Stale runtime source.*opencode.py'):
                audit.verify(output, framework)


if __name__ == '__main__':
    unittest.main()
