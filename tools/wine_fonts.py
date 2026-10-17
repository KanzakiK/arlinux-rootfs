#!/usr/bin/env python3
"""Copy the builder's Windows Arial family into the Bionic Wine runtime."""
import hashlib
import json
import os
from pathlib import Path
import shutil

FILES = ('arial.ttf', 'arialbd.ttf', 'ariali.ttf', 'arialbi.ttf')


def source_directory():
    return Path(os.environ.get('ARLINUX_WINDOWS_FONTS',
        'C:/Windows/Fonts' if os.name == 'nt' else '/mnt/c/Windows/Fonts'))


def install(destination):
    source = source_directory()
    missing = [name for name in FILES if not (source/name).is_file()]
    if missing:
        raise RuntimeError('Set ARLINUX_WINDOWS_FONTS to the Windows font directory; missing: '+', '.join(missing))
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name in FILES:
        shutil.copyfile(source/name, destination/name)
        hashes[name] = hashlib.sha256((destination/name).read_bytes()).hexdigest()
    (destination/'arlinux-fonts.json').write_text(json.dumps(dict(
        family='Arial', source='Windows build host', modified=False, files=hashes), indent=2)+'\n')


if __name__ == '__main__':
    import sys
    install(sys.argv[1])
