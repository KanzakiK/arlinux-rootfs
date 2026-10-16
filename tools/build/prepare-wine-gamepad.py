#!/usr/bin/env python3
"""Install the Winlator-derived Android winebus backend into a Wine source tree."""
from pathlib import Path
import shutil, sys
source = Path(sys.argv[1]) / 'dlls/winebus.sys'
backend = Path(__file__).resolve().parents[2] / 'native/winebus/bus_arlinux.h'
target = source / backend.name
changed = not target.exists() or target.read_bytes() != backend.read_bytes()
if changed:
    shutil.copyfile(backend, target)
path = source / 'bus_udev.c'
text = path.read_text()
marker = '#else\n\nNTSTATUS udev_bus_init(void *args)'
replacement = '#elif defined(__ANDROID__)\n\n#include "bus_arlinux.h"\n\n' + marker
if '#include "bus_arlinux.h"' not in text:
    if text.count(marker) != 1: raise RuntimeError('Wine UDEV fallback changed')
    path.write_text(text.replace(marker, replacement))
elif changed:
    # Wine makedep may not discover includes behind the Android-only branch.
    # Recompile the translation unit when preparing an existing build tree.
    path.touch()
