#!/usr/bin/env python3
"""Replace Spark's Electron payload in a sealed offline desktop, preserving its CLI backend.

Run on Linux with zstd. Input remains immutable; all bundle hashes are regenerated.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import zipfile


def keep(name):
    name = name.removeprefix('./').rstrip('/')
    return not (name == 'opt/spark-store/bin' or name.startswith('opt/spark-store/bin/'))


def build(source, output):
    removed = 0
    with tempfile.TemporaryDirectory(prefix='arlinux-webview-store-') as directory:
        original, compressed = Path(directory) / 'old.zst', Path(directory) / 'new.zst'
        with zipfile.ZipFile(source) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            if 'offline-desktop' not in manifest['files']:
                raise ValueError('Expected a sealed offline desktop')
            for name, expected in manifest['files'].items():
                with archive.open(name) as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                        raise ValueError('Bundle checksum mismatch: ' + name)
            with archive.open('rootfs.tar.zst') as stream, original.open('wb') as target:
                import shutil
                shutil.copyfileobj(stream, target)
        with original.open('rb') as src, compressed.open('wb') as dst:
            reader = subprocess.Popen(['zstd', '-dc'], stdin=src, stdout=subprocess.PIPE)
            writer = subprocess.Popen(['zstd', '-T4', '-19', '-c'], stdin=subprocess.PIPE, stdout=dst)
            try:
                with tarfile.open(fileobj=reader.stdout, mode='r|') as archive, tarfile.open(fileobj=writer.stdin, mode='w|') as target:
                    for member in archive:
                        if not keep(member.name):
                            removed += member.size
                            continue
                        data = archive.extractfile(member).read() if member.isfile() else None
                        name = member.name.removeprefix('./')
                        if name == 'var/lib/dpkg/info/spark-store.list':
                            data = ('\n'.join(line for line in data.decode().splitlines() if keep(line.lstrip('/'))) + '\n').encode()
                        elif name == 'var/lib/dpkg/info/spark-store.md5sums':
                            data = ('\n'.join(line for line in data.decode().splitlines() if keep(line.split(None, 1)[1])) + '\n').encode()
                        elif name == 'usr/bin/arlinux-spark-store':
                            data = b'#!/bin/sh\necho "Open Spark Store using ARLinux Android host" >&2\nexit 1\n'
                        elif name == 'var/lib/dpkg/status':
                            blocks = data.decode().split('\n\n')
                            for i, block in enumerate(blocks):
                                if block.startswith('Package: spark-store\n'):
                                    import re
                                    block = re.sub(r'^Installed-Size: .*$', 'Installed-Size: 1024', block, flags=re.M)
                                    blocks[i] = block
                            data = '\n\n'.join(blocks).encode()
                        if data is not None:
                            member.size = len(data)
                        target.addfile(member, io.BytesIO(data) if data is not None else None)
                writer.stdin.close()
                if reader.wait() or writer.wait():
                    raise RuntimeError('Rootfs transformation failed')
            finally:
                for process in (reader, writer):
                    if process.poll() is None:
                        process.kill()
                        process.wait()
        with compressed.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        replacements = {'rootfs.tar.zst': compressed, 'rootfs-seed-id': (digest + '\n').encode()}
        output.parent.mkdir(parents=True, exist_ok=True)
        pending = output.with_suffix('.zip.part')
        with zipfile.ZipFile(source) as archive, zipfile.ZipFile(pending, 'w') as target:
            for name in manifest['files']:
                value = replacements.get(name)
                stream = value.open('rb') if isinstance(value, Path) else io.BytesIO(value) if isinstance(value, bytes) else archive.open(name)
                hasher = hashlib.sha256()
                with stream, target.open(name, 'w', force_zip64=True) as dest:
                    while block := stream.read(1024 * 1024):
                        dest.write(block)
                        hasher.update(block)
                manifest['files'][name] = hasher.hexdigest()
            target.writestr('manifest.json', json.dumps(manifest, indent=2) + '\n')
        pending.replace(output)
    print(f'Removed Electron payload: {removed / 2**20:.2f} MiB')
    print(f'Bundle: {source.stat().st_size / 2**20:.2f} -> {output.stat().st_size / 2**20:.2f} MiB')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    build(args.source, args.output)
