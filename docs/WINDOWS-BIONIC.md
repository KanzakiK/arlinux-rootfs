# Bionic Wine architecture

Build, cache, package and publish procedures are maintained only in
[BUILD.md](BUILD.md). `build.sh wine` owns the complete dependency graph; the
individual scripts under `tools/build/` are internal stages, not an alternative
manual build recipe.

Wine runs Windows PE executables directly on Android Bionic. Its loader,
wineserver and Unix DLLs do not run through the Linux guest's glibc or tawcroot.
The desktop's Python control client can run in the Linux guest. The Android
launch service starts the native backend with the instance's environment.

The runtime contains version-matched ARM64/ARM64EC/x64/x86 Windows modules,
FEX Windows CPU modules, DXVK, VKD3D, DirectComposition, TLS, PulseAudio and
Bionic graphics libraries. The Linux NDK cross-compiles Android native modules
with 16 KB ELF segment alignment. PE compilation uses LLVM-MinGW.
Steam and the Windows launcher use this same runtime and one instance-level
prefix; Steam registers it as a custom compatibility tool. Do not patch or
replace Steam Proton.

## Graphics and input

Wine's X11 backend reaches Android's Xwayland and compositor. OpenGL uses
Bionic Mesa Zink. Vulkan uses the system Vulkan adapter and shared hybris
compatibility layer; it does not load libhybris's libc bridge. The compositor
continues to render using OpenGL ES/EGL.

GPU workarounds select by capabilities and actual operation results, not phone
model or a narrow driver version. Low-address WOW64 memory uses placed mapping,
external-host import or AHardwareBuffer fallback as supported. Wine-created
images can retry without injected host-sharing flags when rejected; explicit
application sharing is preserved. Imported noncoherent memory is synchronized.
The Qualcomm backend's conservative float-control policy avoids fragment
coordinate corruption. Other backends retain their advertised float controls.

The matching Unix and PE winebus halves share private structures, so they must
come from the same source. The Android backend provides the project's virtual
and physical gamepad path. Raw mouse input requires the XInput headers and
libXi in both compilation and packaging.

## Source and packaging invariants

The Wine fork's pinned source includes the complete WinRT implementation,
including combase/parameterized.c. The currently maintained source preparations
apply VKD3D and community DirectComposition changes to private copies. Migrating
these existing changes into the fork remains required; do not add another
parallel preparation or packaging route.

PE and native builds verify matching VKD3D/DirectComposition provenance.
Packaging validates required DLLs, graphics records, dependency hashes,
licenses and matching source archives. The independent Wine receipt identifies
its exact output and compatibility helper binaries. Rootfs consumes these
verified helper artifacts; it does not build Wine or contain the Wine archive.

The runtime records Arial input hashes and installs the fonts before wineboot.
The Wine cache fingerprints those font inputs. Published runtime pins live in
runtime/tools/windows-downloads.tsv. Consumer startup downloads the pinned
archive, verifies SHA-256 and prepares dependencies automatically.

## Diagnostics

Use the Android repository's tools/diagnostics/README.md for process, exception,
symbolized stack and screenshot evidence before changing compatibility code.
Tests in tests/ cover Vulkan policies, component provenance, PE cache retries,
source preparation and packaging. Compilation checks do not replace clean
instance acceptance with GPU rendering, input and actual Steam Play.
