#!/usr/bin/env python3
"""Stage a locally rebuilt Proton core; retain matching source in build output."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def install(pack, destination):
    data = json.loads((pack/'pack.json').read_text())
    expected = {'files/lib/wine/aarch64-unix/ntdll.so', 'files/bin-arm64/wineserver'}
    if data.get('format') != 1 or set(data.get('files', {})) != expected:
        raise RuntimeError('Invalid Proton core pack')
    sources = {'wine-source.tar.gz', 'execmod.patch'}
    if set(data.get('source', {})) != sources:
        raise RuntimeError('Matching Wine source and patch are required for distribution')
    for name, checksum in (data['files'] | data['source']).items():
        with (pack/name).open('rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() != checksum:
                raise RuntimeError(f'Damaged Proton core build: {name}')
    # The source archive remains a companion build artifact, not APK payload.
    # Publish it alongside any release containing these LGPL binaries.
    target = destination/hashlib.sha256((pack/'pack.json').read_bytes()).hexdigest()[:24]
    target.mkdir(parents=True, exist_ok=True)
    for name in ('pack.json', *sorted(expected)):
        output = target/name
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pack/name, output)
    print(f'Installed Proton core: {data["version"]}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pack', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    install(args.pack, args.destination)
