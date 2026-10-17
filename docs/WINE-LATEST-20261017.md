# Bionic Wine latest: 2026-10-17 audit

Runtime SHA-256:
`6fe4aeb884ee1abcf9543247be900aab93ff652b39a29c6668aad04c11a92c41`

Wine commit: `46af030d975f331ff6304a34a6b91c6147285c6d` (11.19).
The runtime and Windows launcher continue to use the same instance Bionic Wine;
no Steam Proton modification is involved.

## Build and packaging verification

`tools/build/wine-pe.sh` produced the complete Windows module installation.
Its prepared source was byte-for-byte equal to the previous compiler cache;
Make dependencies and installation were rerun through the public entry point.
`tools/build/wine-bionic.sh` compiled the native backend from a new private
source tree. `tools/package-wine-pe.py` and `tools/package-wine-bionic.py`
assembled the final archive with the matching PE, FEX, DXVK and native inputs.

Reverse dry-run checks verified every direct Wine patch from both build scripts
against their prepared source, with no fuzz:

| Patch | Native source | PE source |
| --- | --- | --- |
| wine-bionic-certificates | Yes | — |
| wine-dwrite-bitmap-cache | Yes | Yes |
| wine-dwrite-transformed-hinting | Yes | — |
| wine-keyboard-layout | Yes | Yes |
| wine-bionic-pulse | Yes | — |
| wine-bionic-shared-storage-security | Yes | — |
| wine-arm64-apc-context | Yes | — |
| wine-bionic-local-focus | Yes | — |
| wine-bionic-dragdrop-owner | Yes | — |
| wine-bionic-wow64-images | Yes | — |
| wine-bionic-opengl-unavailable | Yes | — |
| wine-bionic-layered-alpha | Yes | — |
| wine-bionic-layered-minimize | Yes | — |
| wine-bionic-mmap-probe | Yes | — |

The pinned VKD3D and DirectComposition records matched both source trees.
The native winebus backend matched `native/winebus/bus_arlinux.h`.
The package includes Vulkan/Hybris, Zink OpenGL, Turnip, audio, TLS, Android
gamepad support, raw XInput2 mouse input, Arial and the US keyboard layout DLL.
All 4,638 file hashes passed publication validation. LLVM confirmed ARM64,
ARM64EC and x64 code maps in the compact ARM64X `dcomp`, `dwrite` and `kbdus`
modules; standalone x64 duplicates are intentionally removed by packaging.

The release publisher checks and uploads the native Wine source archive plus
the PE Wine, FEX and DXVK source archives recorded in runtime metadata. The
native Wine source archive SHA-256 is
`2e385a69722b64ad4585fc461d8b65e76dd36ae4805cc64cd0846f8c5f0ad6e6`.

## Final artifact acceptance

Xiaomi 15, serial `3fad759`, debug package `io.taowen.arlinux.dev`, fresh
imported instance `yibu-38b4c388`. Previous test instance was deleted. Only
SHA-256-verified immutable runtime/installer downloads were seeded through
`tools/cache-windows-downloads.py`; no installed application or Wine prefix
was restored.

- Built-in FontForge icon installed the official x64 2025-10-09 installer and
  automatically opened the editor; typing the Arial path opened its font grid.
- ARM64 and x64 DirectWrite probes passed six cold/warm mask comparisons each
  and transformed-outline height checks (21 pixels versus 21 pixels).
- The application's actual GTK runtime passed all five keyboard translations.
- The layered-window probe passed all ten pixel, shape, transparency,
  minimization and restoration phases.

The preceding FontForge candidate also passed editing an outline, typing an
SFD filename, saving, quitting and reopening. This final release acceptance
does not claim a new Steam game or Power BI end-to-end regression.
