# Android gamepad backend for Bionic Wine

`bus_arlinux.h` adapts Wine HID device creation and report mapping from
[Winlator bus_winlator.c](https://github.com/brunodev85/wine-10.10-custom/blob/c507e3fa64a415ecf81b1bf238f316467647bc39/dlls/winebus.sys/bus_winlator.c),
Copyright 2026 BrunoSX, LGPL-2.1-or-later. The original license notice is retained.

ARLinux replaces Winlator UDP transport with the existing same-UID abstract
Unix socket broker implemented by Android `gamepad.c`. Screen and physical
controllers share four hot-pluggable slots. No root, uinput or network listener
is required. The Wine HID device is available through both XInput and DirectInput.
Rumble is not advertised because the current Android broker has no output protocol.

`tools/build/prepare-wine-gamepad.py` installs this backend into the Android
fallback of winebus. The desktop build cache includes this directory and patcher.
The runtime package includes this source, preparation script and LGPL license
under `share/arlinux/winebus` so binary recipients can reproduce the changes.

The native build also builds `winebus.sys` for ARM64, x86 and x64 from the same
prepared source, and packaging replaces the generic PE runtime's copies. The
driver and Unix backend exchange private structures; mixing builds can corrupt
device descriptions and prevent every controller from being enumerated.
