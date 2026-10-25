#!/usr/bin/env python3
"""Publish an exact verified distribution ZIP without building or repackaging it."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile


def output(*args):
    return subprocess.check_output(list(map(str, args)), text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('distribution', choices=('lxqt', 'plasma', 'arch', 'omarchy'))
    parser.add_argument('tag')
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r'v\d+\.\d+\.\d+', args.tag):
        raise ValueError('Use a version tag such as v0.1.4')
    framework = Path(__file__).resolve().parents[1]
    if output('git', '-C', framework, 'status', '--porcelain', '--untracked-files=normal'):
        raise ValueError('Commit framework changes before publishing')
    archive = args.archive.resolve(strict=True)
    # Consume the producer's receipt and ordinary bundle safety/hash validation.
    receipt = json.loads(archive.with_suffix('.json').read_text())
    with archive.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    if receipt['desktopSha256'] != checksum:
        raise ValueError('Archive differs from its producer receipt')
    subprocess.run([sys.executable, str(framework/'tools/bundle.py'), 'verify', str(archive)], check=True)
    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read('manifest.json'))
        if manifest['distributionId'] != args.distribution or 'device-build' in bundle.namelist():
            raise ValueError('Expected a consumer bundle for the requested distribution')
    recipe = json.loads((framework/f'tools/build/components/{args.distribution}.json').read_text())
    repository = recipe['repository']
    tree = output('git', '-C', framework, 'ls-tree', 'HEAD', 'distributions/'+args.distribution)
    source = tree.split()[2]
    output('gh', 'api', f'repos/{repository}/commits/{source}', '--jq', '.sha')
    revision = output('git', '-C', framework, 'rev-parse', 'HEAD')
    notes = (f'Import this ZIP into ARLinux 0.6.4 or later. Keep it zipped. '
             f'Guest Tools are supplied by the APK and pinned when the environment is created.\n\n'
             f'- Protocol: {manifest["protocol"]}\n- Distribution source: `{source}`\n'
             f'- Framework: `{revision}`\n- Size: {archive.stat().st_size} bytes\n'
             f'- SHA-256: `{checksum}`\n')
    with tempfile.TemporaryDirectory(prefix='arlinux-publish-') as temporary:
        asset = Path(temporary)/(args.distribution+'.zip')
        shutil.copyfile(archive, asset)
        subprocess.run(['gh', 'release', 'create', args.tag, str(asset),
                        '-R', repository, '--target', source,
                        '--title', f'{args.distribution.title()} {args.tag}', '--notes', notes], check=True)
    print(output('gh', 'release', 'view', args.tag, '-R', repository, '--json', 'url', '--jq', '.url'))


if __name__ == '__main__':
    main()
