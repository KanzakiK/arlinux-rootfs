#!/usr/bin/env python3
"""Apply the pinned Wine Staging VKD3D update to a private Wine build tree."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def refresh(source):
    patches = Path(__file__).resolve().parents[1] / 'patches/wine-staging-vkd3d'
    record = json.loads((patches / 'manifest.json').read_text())
    if (source / 'VERSION').read_text().strip() != 'Wine version ' + record['wine']:
        raise RuntimeError('VKD3D patches require the matching Wine ' + record['wine'] + ' source')
    # Verify the entire series before changing any source files.
    for entry in record['patches']:
        data = (patches / entry['name']).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise RuntimeError('VKD3D patch checksum mismatch: ' + entry['name'])
    stamp = source / 'arlinux-vkd3d.json'
    if stamp.exists():
        if json.loads(stamp.read_text()) != record:
            raise RuntimeError('Source already contains a different VKD3D update')
        return record
    for entry in record['patches']:
        subprocess.run(['patch', '-d', str(source), '-p1', '--batch', '--fuzz=0'],
                       input=(patches / entry['name']).read_bytes(), check=True)
    stamp.write_text(json.dumps(record, indent=2) + '\n')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Private, complete Wine source tree (modified in place)')
    args = parser.parse_args()
    print('VKD3D revision:', refresh(args.source.resolve())['vkd3dCommit'])
