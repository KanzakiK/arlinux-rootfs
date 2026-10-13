#!/usr/bin/env python3
"""Refresh Bionic Windows launchers in an already sealed offline desktop."""
import argparse
import hashlib
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
import zipfile
import importlib.util
spec = importlib.util.spec_from_file_location('device_desktop', Path(__file__).with_name('device-desktop.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
rewrite = module.rewrite


def refresh(bundle, output):
    root = Path(__file__).resolve().parents[1]
    names = ['windows.py', 'windows_apps.py', 'windows_a11y.py', 'shared.py']
    replacements = {'usr/lib/arlinux/'+name: root/'runtime/tools'/name for name in names}
    for name in ['windows-downloads.tsv', 'windows-app-downloads.tsv']:
        replacements['usr/lib/arlinux/guest/'+name] = root/'runtime/tools'/name
    replacements['usr/lib/arlinux/guest/yibu-launcher.py'] = root/'runtime/tools/apps.py'
    replacements['usr/bin/arlinux-windows-app'] = root/'runtime/tools/arlinux-windows-app'
    for app in ['paintnet', 'powerbi']:
        replacements[f'usr/share/applications/arlinux-{app}.desktop'] = root/f'runtime/tools/arlinux-{app}.desktop'
        replacements[f'usr/share/pixmaps/arlinux-{app}.png'] = root/f'runtime/tools/{app}.png'
    with tempfile.TemporaryDirectory(prefix='bionic-desktop-') as temporary:
        temp = Path(temporary)
        original, compressed = temp/'original.zst', temp/'rootfs.tar.zst'
        with zipfile.ZipFile(bundle) as archive:
            if 'offline-desktop' not in archive.namelist():
                raise ValueError('Expected a sealed offline desktop')
            with archive.open('rootfs.tar.zst') as source, original.open('wb') as target:
                import shutil
                shutil.copyfileobj(source, target)
        with original.open('rb') as source, compressed.open('wb') as dest:
            reader = subprocess.Popen(['zstd', '-dc'], stdin=source, stdout=subprocess.PIPE)
            writer = subprocess.Popen(['zstd', '-T4', '-10', '-c'], stdin=subprocess.PIPE, stdout=dest)
            try:
                with tarfile.open(fileobj=reader.stdout, mode='r|') as old, tarfile.open(fileobj=writer.stdin, mode='w|', format=tarfile.PAX_FORMAT) as new:
                    for member in old:
                        name = member.name.removeprefix('./')
                        if name in replacements or (name.startswith('usr/lib/arlinux/__pycache__/') and
                                any(name.split('/')[-1].startswith(n[:-3]+'.') for n in names)):
                            continue
                        new.addfile(member, old.extractfile(member) if member.isfile() else None)
                    for name, path in replacements.items():
                        data = path.read_bytes()
                        member = tarfile.TarInfo('./'+name)
                        member.mode, member.size = (0o755 if name.startswith('usr/bin/') else 0o644), len(data)
                        new.addfile(member, io.BytesIO(data))
                writer.stdin.close()
                if reader.wait() or writer.wait():
                    raise RuntimeError('Desktop compression failed')
            finally:
                for process in (reader, writer):
                    if process.poll() is None:
                        process.kill()
                        process.wait()
        with compressed.open('rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        rewrite(bundle, output, {'rootfs.tar.zst': compressed,
                                'rootfs-seed-id': (checksum+'\n').encode()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    refresh(args.bundle, args.output)
