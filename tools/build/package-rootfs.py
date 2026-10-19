#!/usr/bin/env python3
"""Prepare the complete ARM64 desktop in a disposable Linux mount namespace."""
import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile


def prepare(seed, output):
    if os.geteuid() != 0:
        raise RuntimeError('Rootfs package preparation requires root on the Linux runner')
    if str(output.resolve()).startswith('/mnt/'):
        raise ValueError('Rootfs build directories must use the Linux filesystem')
    framework = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location('bundle', framework / 'tools/bundle.py')
    bundle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bundle)
    bundle.verify(seed)
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='package-rootfs-', dir=output.parent) as temporary:
        root = Path(temporary) / 'rootfs'
        root.mkdir()
        compressed = Path(temporary) / 'rootfs.tar.zst'
        with zipfile.ZipFile(seed) as archive:
            with archive.open('rootfs.tar.zst') as source, compressed.open('wb') as dest:
                shutil.copyfileobj(source, dest)
            subprocess.run(['tar', '--zstd', '-xf', str(compressed), '-C', str(root)], check=True)
            guest = root / 'usr/lib/arlinux/guest'
            guest.mkdir(parents=True, exist_ok=True)
            for name in archive.namelist():
                if name.startswith('guest/') and not name.endswith('/'):
                    relative = Path(name).relative_to('guest')
                    if '..' in relative.parts:
                        raise ValueError('Unsafe guest helper path')
                    target = guest / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(name))
        resolver = root / 'etc/resolv.conf'
        resolver.unlink(missing_ok=True)
        resolver.write_bytes(Path('/etc/resolv.conf').read_bytes())
        policy = root / 'usr/sbin/policy-rc.d'
        policy.parent.mkdir(parents=True, exist_ok=True)
        policy.write_text('#!/bin/sh\nexit 101\n')
        policy.chmod(0o755)
        # Hosted runners should not cross continents to use the consumer mirror.
        # The guest recipe copies this file on each libc-restart pass. Change
        # only the disposable build copy, then restore both copies before export.
        debian_sources = guest / 'debian.sources'
        consumer_sources = debian_sources.read_bytes() if debian_sources.is_file() else None
        if consumer_sources is not None:
            debian_sources.write_bytes(consumer_sources.replace(
                b'https://mirrors.tuna.tsinghua.edu.cn/debian', b'https://deb.debian.org/debian'))
            print('Package preparation uses deb.debian.org; consumer sources are restored before export', flush=True)
        subprocess.run(['unshare', '--mount', '--propagation', 'private', '--',
                        'bash', str(framework / 'tools/build/package-rootfs.sh'), str(root)], check=True)
        if consumer_sources is not None:
            debian_sources.write_bytes(consumer_sources)
            (root / 'etc/apt/sources.list.d/debian.sources').write_bytes(consumer_sources)
        policy.unlink(missing_ok=True)
        subprocess.run(['tar', '--numeric-owner', '-cf', str(output / 'snapshot.tar'),
                        '-C', str(root), '.'], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('seed', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    prepare(args.seed, args.output)
