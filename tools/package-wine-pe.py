#!/usr/bin/env python3
"""Package one complete Wine build with independently built FEX and DXVK.

No Proton launcher, prefix template, or older Wine modules are included.
The source archives remain beside the bundle for license compliance.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wine', type=Path, required=True, help='wine-pe.sh output')
    parser.add_argument('--fex', type=Path, required=True, help='fex-windows.sh output')
    parser.add_argument('--dxvk', type=Path, required=True, help='dxvk-windows.sh output')
    parser.add_argument('--addons', type=Path, required=True, help='Directory containing wine/mono and wine/gecko')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='wine-package-', dir=args.output.parent) as temporary:
        stage = Path(temporary)
        files = stage/'files'
        # Only the Windows modules; no glibc native backend is packaged.
        # A single complete, version-matched Wine installation is the sole base.
        shutil.copytree(args.wine/'files', files, symlinks=True)
        shutil.rmtree(files/'lib/wine/aarch64-unix', ignore_errors=True)
        for directory in ('include', 'share/man', 'share/applications'):
            shutil.rmtree(files/directory, ignore_errors=True)
        # Import/static libraries are build-time inputs, never loaded by Wine.
        for path in (files/'lib').rglob('*.a'):
            path.unlink()
        for name in ('arm64ecfex', 'wow64fex'):
            for arch, suffix in (('aarch64-windows', 'dll'),):
                shutil.copy2(args.fex/f'lib{name}.{suffix}', files/f'lib/wine/{arch}/lib{name}.{suffix}')
        for arch in ('aarch64', 'i386', 'x86_64'):
            shutil.copytree(args.dxvk/f'{arch}-windows', files/f'lib/wine/dxvk/{arch}-windows')
        for name in ('mono', 'gecko'):
            shutil.copytree(args.addons/name, files/'share/wine'/name, symlinks=True)
        # Wine's documented CPU-module registry defaults, installed by wineboot.
        inf = files/'share/wine/wine.inf'
        text = inf.read_text()
        for arch, old, new in (('amd64', 'xtajit64.dll', 'libarm64ecfex.dll'),
                               ('x86', 'xtajit.dll', 'libwow64fex.dll')):
            needle = f'HKLM,Software\\Microsoft\\Wow64\\{arch},,2,"{old}"'
            if text.count(needle) != 1:
                raise ValueError(f'Wine CPU-module default changed: {old}')
            text = text.replace(needle, needle.replace(old, new))
        inf.write_text(text)
        config = files/'share/fex-emu/Config.json'
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({'Config': {'TSOEnabled': '1', 'X87ReducedPrecision': '1',
                                               'VectorTSOEnabled': '0', 'MemcpySetTSOEnabled': '0',
                                               'HalfBarrierTSOEnabled': '1', 'MaxInst': '500', 'Multiblock': '1'}}, indent=2)+'\n')
        metadata = {'format': 2, 'kind': 'wine-pe', 'architecture': 'aarch64',
                    'wine_version': (args.wine/'wine-version').read_text().strip(),
                    'wine_commit': (args.wine/'wine-commit').read_text().strip(),
                    'fex_commit': (args.fex/'source-commit').read_text().strip(),
                    'dxvk_commit': (args.dxvk/'source-commit').read_text().strip(),
                    'files': {str(p.relative_to(stage)): digest(p)
                              for p in sorted(files.rglob('*')) if p.is_file()}}
        sources = (('wine', args.wine/'wine-source.tar.gz'),
                   ('fex', args.fex/'fex-source.tar.gz'), ('dxvk', args.dxvk/'source.tar.gz'))
        metadata['sources'] = {}
        for name, source in sources:
            destination = args.output.with_name(args.output.stem.removesuffix('.tar')+f'-{name}-source.tar.gz')
            shutil.copy2(source, destination)
            metadata['sources'][name] = {'asset': destination.name, 'sha256': digest(destination)}
        (stage/'arlinux-runtime.json').write_text(json.dumps(metadata, indent=2)+'\n')
        archive = stage/'wine.tar.gz'
        with tarfile.open(archive, 'w:gz', compresslevel=3) as bundle:
            bundle.add(files, arcname='files')
            bundle.add(stage/'arlinux-runtime.json', arcname='arlinux-runtime.json')
        archive.replace(args.output)
    checksum = digest(args.output)
    args.output.with_name(args.output.name+'.sha256').write_text(f'{checksum}  {args.output.name}\n')
    print(f'{checksum}  {args.output}')


if __name__ == '__main__':
    main()
