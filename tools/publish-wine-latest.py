#!/usr/bin/env python3
"""Publish the tested Bionic Wine archive and its reproducibility source asset."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time


def component_source_archives(metadata, directory):
    component_sources = []
    for name in ('wine', 'fex', 'dxvk'):
        record = metadata.get('originalSources', {}).get(name, {})
        filename, expected = record.get('asset'), record.get('sha256')
        if not isinstance(filename, str) or Path(filename).name != filename or not expected:
            raise ValueError('Missing component source record: ' + name)
        path = directory / filename
        actual = None
        if path.is_file():
            with path.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != expected:
            raise ValueError('Missing or mismatched component source archive: ' + str(path))
        component_sources.append((path, expected))
    return component_sources


def verify_uploaded_asset(command, asset, checksum, size):
    # GitHub can briefly return the previous asset or an unset digest after
    # replacement. Never advance the download pin until metadata agrees.
    for attempt in range(6):
        release = json.loads(subprocess.check_output(command[:1] + ['api',
                             'repos/taowen/wine/releases/tags/latest'], text=True))
        uploaded = next((item for item in release['assets'] if item['name'] == asset), None)
        if uploaded and uploaded.get('digest') == 'sha256:' + checksum and uploaded.get('size') == size:
            return
        if attempt < 5:
            time.sleep(2)
    raise RuntimeError('Published archive verification failed; download pin unchanged')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path, help='Exact archive already tested on devices')
    parser.add_argument('--source-archive', type=Path,
                        help='wine-source-<commit>.tar.gz produced by wine-pe.sh')
    parser.add_argument('--manifest', required=True, type=Path,
                        help='arlinux-rootfs/runtime/tools/windows-downloads.tsv')
    parser.add_argument('--check', action='store_true', help='Validate without publishing')
    args = parser.parse_args()
    archive = args.archive.resolve(strict=True)
    checksum = hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest()
    with tarfile.open(archive) as packed:
        metadata = json.load(packed.extractfile('bionic-runtime.json'))
        if metadata.get('protocol') != 1 or metadata.get('libc') != 'bionic':
            raise ValueError('Expected the project Bionic Wine runtime')
        required = ('directComposition', 'vkd3d', 'graphicsBuild')
        if any(not metadata.get(name) for name in required):
            raise ValueError('Runtime omits required build components: ' + ', '.join(required))
        if metadata.get('vulkanCompat') != 'hybris' or metadata.get('openglDriver') != 'zink':
            raise ValueError('Latest requires system Vulkan compatibility and Zink OpenGL')
        if not all(metadata.get('backends', {}).get(name) for name in ('vulkan', 'opengl', 'audio', 'tls')):
            raise ValueError('Latest requires Vulkan, OpenGL, audio and TLS backends')
        # Compact packaging serves x64 callers through the ARM64X modules;
        # optimize() deliberately removes their standalone x86_64 duplicates.
        arches = ['aarch64', 'i386']
        if metadata.get('packaging', {}).get('standaloneX64Dlls') is not False:
            arches.append('x86_64')
        for arch in arches:
            for dll in ('dcomp', 'd3d12', 'd3d12core', 'dwrite', 'kbdus'):
                if f'files/lib/wine/{arch}-windows/{dll}.dll' not in metadata['files']:
                    raise ValueError('Latest omits required module: ' + arch + '/' + dll)
        if 'files/etc/dxvk.conf' not in metadata['files']:
            raise ValueError('Latest omits the WebView2 composition configuration')
        expected = dict(metadata['files'])
        for member in packed:
            name = member.name.removeprefix('./')
            if name in expected:
                if not (member.isfile() or member.islnk()):
                    raise ValueError('Expected a runtime file or archive hard link: ' + name)
                actual = hashlib.file_digest(packed.extractfile(member), 'sha256').hexdigest()
                if actual != expected.pop(name):
                    raise ValueError('Runtime checksum mismatch: ' + name)
        if expected:
            raise ValueError('Missing runtime files')
    source = metadata.get('wineSource')
    if not isinstance(source, dict) or not source.get('commit') or not source.get('archiveSHA256') \
            or not source.get('archiveName') or not source.get('archiveURL'):
        raise ValueError('Runtime metadata has no complete wineSource record')
    source_archive = (args.source_archive or (archive.parent / source['archiveName'])).resolve()
    if not source_archive.is_file():
        raise ValueError('Missing source archive; pass --source-archive: ' + str(source_archive))
    source_checksum = hashlib.file_digest(source_archive.open('rb'), 'sha256').hexdigest()
    if source_checksum != source['archiveSHA256']:
        raise ValueError('Wine source archive SHA-256 does not match bionic-runtime.json')
    expected_source_url = ('https://github.com/taowen/wine/releases/download/arlinux-wine-source-' +
                           source['archiveSHA256'] + '/' + source['archiveName'])
    if source['archiveURL'] != expected_source_url:
        raise ValueError('wineSource.archiveURL must use the immutable source release tag')
    # The PE packager also records the Wine, FEX and DXVK source inputs.
    # Validate every one before changing any public release asset.
    component_sources = component_source_archives(metadata, archive.parent)
    asset = 'arlinux-wine-bionic.tar.gz'
    url = 'https://github.com/taowen/wine/releases/download/latest/' + asset
    manifest = f'Wine {metadata["wine"]} Bionic latest\t{checksum}\t{url}\n'
    print('Validated Bionic Wine archive SHA-256:', checksum, flush=True)
    print('Validated Wine source archive SHA-256:', source_checksum, flush=True)
    if args.check:
        return
    command = ['gh', 'release']
    source_tag = 'arlinux-wine-source-' + source['archiveSHA256']
    # Older gh release --json projections omit GitHub's asset digest field.
    # Raw API responses preserve it across supported CLI versions.
    source_view = subprocess.run(['gh', 'api', 'repos/taowen/wine/releases/tags/' + source_tag],
                                 capture_output=True, text=True)
    if source_view.returncode:
        subprocess.run(command + ['create', source_tag, '-R', 'taowen/wine',
            '--title', 'ARLinux Wine source ' + source['commit'], '--notes',
            'Immutable source archive for the ARLinux Bionic Wine runtime.'], check=True)
        source_assets = []
    else:
        source_assets = json.loads(source_view.stdout).get('assets', [])
    existing_source = next((item for item in source_assets if item['name'] == source['archiveName']), None)
    if existing_source:
        if existing_source.get('digest') != 'sha256:' + source_checksum or \
                existing_source.get('size') != source_archive.stat().st_size:
            raise RuntimeError('Immutable Wine source release already contains a different archive')
    else:
        with tempfile.TemporaryDirectory(prefix='arlinux-wine-source-') as directory:
            staged_source = Path(directory) / source['archiveName']
            shutil.copyfile(source_archive, staged_source)
            subprocess.run(command + ['upload', source_tag, '-R', 'taowen/wine',
                                      str(staged_source)], check=True)
    # Keep the stable latest runtime asset for existing clients.
    view = subprocess.run(['gh', 'api', 'repos/taowen/wine/releases/tags/latest'],
                          capture_output=True, text=True)
    if view.returncode:
        subprocess.run(command + ['create', 'latest', '-R', 'taowen/wine',
            '--title', 'ARLinux Bionic Wine latest', '--notes',
            'Shared Bionic Wine runtime for ARLinux Windows applications and Steam games. '
            'Downloads are pinned and verified by SHA-256.', '--latest'], check=True)
    assets = json.loads(subprocess.check_output(['gh', 'api',
                        'repos/taowen/wine/releases/tags/latest'], text=True))['assets']
    for path, expected in component_sources:
        existing = next((item for item in assets if item['name'] == path.name), None)
        if existing:
            if existing.get('digest') != 'sha256:' + expected or existing.get('size') != path.stat().st_size:
                raise RuntimeError('Component source asset already differs: ' + path.name)
        else:
            subprocess.run(command + ['upload', 'latest', '-R', 'taowen/wine', str(path)], check=True)
    existing = next((item for item in assets if item['name'] == asset), None)
    if not existing or existing.get('digest') != 'sha256:' + checksum or existing.get('size') != archive.stat().st_size:
        with tempfile.TemporaryDirectory(prefix='arlinux-wine-latest-') as directory:
            staged = Path(directory) / asset
            shutil.copyfile(archive, staged)
            subprocess.run(command + ['upload', 'latest', '-R', 'taowen/wine',
                                      str(staged), '--clobber'], check=True)
    verify_uploaded_asset(command, asset, checksum, archive.stat().st_size)
    args.manifest.write_text(manifest, encoding='utf-8', newline='\n')
    print('Published latest and updated download pin:', args.manifest)


if __name__ == '__main__':
    main()
