# Experimental Bionic Wine

Wine can run Windows PE executables directly from Android without loading the
Linux guest's glibc or tawcroot. The desktop and its Python control client may
still use the Linux guest; the Wine processes do not.

The prototype uses Wine 11.19, its matching ARM64/ARM64EC/x64/x86 PE modules,
and FEX's existing Windows CPU modules. Wine's loader, wineserver, Unix DLLs,
and FEX Unix helpers are compiled with Android NDK 29, API 29, and 16 KB ELF
segment alignment. The Unix helpers replace POSIX shm with private files in
`TMPDIR`. The native loader resides beside `ntdll.so`; `bin/wine` links to it.

The community reference is the [Proton Wine ARM64EC Android build](https://github.com/The412Banner/proton-wine/blob/proton_11.0/build-scripts/build-step-arm64ec.sh).
The prototype retains ARLinux's Wine revision and application fixes.

### Wine Staging dependency refresh

The April 2026 [Wine Staging 11.6 announcement](https://www.phoronix.com/news/Wine-Staging-11.6)
highlights DirectComposition and VKD3D. Our base is already Wine 11.19;
do not downgrade it or replace the community DirectComposition implementation
and its local lifetime fixes with the older staging stubs.

VKD3D is refreshed using the eight patches from Wine Staging revision
`11dd86bdfada3c85877b90c765ff9e3af200ddd1`, reaching VKD3D
`fed0c3418f815b0bc07533f6fc6f4aa06e8712c3`. The complete series and SHA-256
manifest live in `tools/patches/wine-staging-vkd3d`. These update Wine's bundled
VKD3D, including shader compilation; they do not replace DXVK or Steam Proton.
Source: [Wine Staging patch series](https://github.com/wine-staging/wine-staging/tree/11dd86bdfada3c85877b90c765ff9e3af200ddd1/patches/vkd3d-latest).

Build both PE and native components from the same refreshed sources. The rootfs repository's
`tools/build/wine-pe.sh` applies the checked-in
`tools/build/refresh-wine-vkd3d.py` automatically. The PE build records `arlinux-vkd3d.json`.
The Bionic build applies the same series to its private source copy and refuses
PE inputs with a missing or different record. Packaging retains this provenance
in `bionic-runtime.json`. Existing published runtimes remain unchanged until a
rebuilt runtime passes device acceptance and is published.

2026-10-16 build verification: the complete series applies to the Wine 11.19
source with zero fuzz. Rebuilt `d3d12`, `d3d12core`, `d3dcompiler_47` and
`wined3d` for aarch64/ARM64EC, i386 and x86_64 (12 DLL outputs). The refresh
workflow's three regression tests passed. This is compilation validation;
the refreshed runtime has not yet passed Android device acceptance or replaced
the published latest runtime.

## Required default build components

`wine-pe.sh` now prepares the pinned community DirectComposition implementation
and `wine-dcomp-content-lifetime.patch` before compiling all PE architectures.
It shares `prepare-wine-dcomp.sh` with the focused DComp build; an extra DComp
packaging overlay is no longer required. Both PE and Bionic packaging require
DComp and VKD3D provenance, and all aarch64/i386/x86_64 DComp and D3D12 modules.
The WebView2 DXVK composition configuration is installed automatically.

The latest publisher rejects runtimes missing DComp, VKD3D, the graphics build
record, Zink, system Vulkan compatibility, audio, TLS or composition config.
Bionic packaging archives the exact private source tree including its native
patches, copies the source archive beside the runtime, and names source assets
and immutable release tags by source SHA-256. Different local patches to the
same Wine commit therefore cannot collide in an immutable source release.
These are build requirements; successful packaging does not replace device
acceptance for Power BI or Steam games.

## Build

Run all commands in the `arlinux-rootfs` checkout. Wine PE/native builds,
DXVK, Vulkan adapter, patches, packaging and publication are maintained here.
The Android host repository consumes the resulting distribution and download
manifest; it is not needed for these Wine build scripts.

Use the pinned `third_party/wine` revision, which tracks
`dlls/combase/parameterized.c`. The PE build creates matching native Wine tools;
supply those tools to the Bionic build, together with a dependency prefix
containing X11, XCB, FreeType, and Fontconfig.

Build TLS and graphics dependencies and provide the native PulseAudio client
prefix used by the Android audio server:

```bash
tools/build/wine-bionic-tls.sh NDK_ROOT TLS_BUILD_DIRECTORY
tools/build/wine-bionic-graphics.sh \
  ARLINUX_MESA_SOURCE NDK_ROOT NATIVE_PREFIX GRAPHICS_PROTOCOLS GRAPHICS_BUILD_DIRECTORY
export BIONIC_TLS_PREFIX=TLS_BUILD_DIRECTORY/prefix
export BIONIC_PULSE_PREFIX=PULSEAUDIO_NATIVE_PREFIX
export BIONIC_GRAPHICS_PREFIX=GRAPHICS_BUILD_DIRECTORY/prefix
```

Graphics uses a Bionic desktop Vulkan loader. The default driver is the phone's
system Vulkan HAL, with the shared libhybris desktop X11/Wayland WSI and
`VK_LAYER_HYBRIS_compat` compiled against Bionic, plus an AHardwareBuffer
allocator. The compatibility layer handles capability queries and matching
shader, polygon and BC texture transformations together. It does not load
libhybris's libc bridge. The Android compositor continues to use OpenGL ES/EGL.
OpenGL uses Bionic Mesa Zink over the same system Vulkan ICD and compatibility
layer. The graphics build enables Zink, GLX and EGL, and Wine enables its X11
OpenGL backend. Packaging includes the GL libraries and DRI modules; the host
selects Zink with runtime-local driver paths. `BIONIC_OPENGL=none` builds only
the Vulkan dependencies and permits `-` as the Mesa source argument.
Build the adapter from ARLinux's libhybris checkout and its Android headers:

```bash
python3 tools/build/bionic-vulkan.py --source LIBHYBRIS_SOURCE \
  --headers LIBHYBRIS_ANDROID_HEADERS --ndk NDK_ROOT \
  --native-prefix NATIVE_PREFIX --graphics-prefix "$BIONIC_GRAPHICS_PREFIX" \
  --output SYSTEM_VULKAN_BUILD_DIRECTORY
export BIONIC_SYSTEM_VULKAN_ADAPTER=SYSTEM_VULKAN_BUILD_DIRECTORY/libvulkan_android_desktop.so
tools/build/bionic-dxvk.sh DXVK_SOURCE LLVM_MINGW_BIN DXVK_BUILD_DIRECTORY
export BIONIC_DXVK_RUNTIME=DXVK_BUILD_DIRECTORY
```

Use the version-matched DXVK source from the shipping runtime, including its
submodules. The build makes KHR_pipeline_library optional, allowing system
drivers without that extension to create a Direct3D device. ARM64X requires
LLVM-MinGW with LLVM 23 or newer.
The shared Vulkan compatibility layer uses a conservative float-control
policy for the Qualcomm proprietary backend, independent of phone model,
GPU model and driver version. It reports
`shaderDenormFlushToZeroFloat32 = false` through both core/KHR property
queries and both standalone/Vulkan 1.2 structures. This avoids a fragment
coordinate corruption observed on Xiaomi 15: pixel shaders read zero
`SV_POSITION`, collapsing Paint.NET's canvas and panels to solid colors.
This is a backend-wide compatibility policy, not evidence that every
Qualcomm driver has the defect. Other float controls remain unchanged;
Mesa/Turnip and other driver implementations retain their reported modes.
DXVK uses its ordinary capability checks without an application patch.
`tests/applications/windows-fragment-coordinates.c` checks coordinates by
reading back a rendered gradient; `tests/test-vulkan-float-policy.py` checks
that backend selection does not depend on version and both structures agree.

Wine's WOW64 memory fixes also select by advertised capabilities and actual
operation results, without a device/vendor/version whitelist. Placed mapping
and external-host import retain priority; AHardwareBuffer export is the
fallback when both are unavailable and the Android extension and entry points
exist. Image creation retries without Wine's injected host-sharing flag only
when the driver rejects it; explicit application sharing is preserved.
Noncoherent imported memory receives flush/invalidate synchronization when
needed. X300 and Xiaomi 15 are validation devices, not activation conditions.
These paths do not guarantee support on drivers lacking a usable low-address
mapping mechanism.

When initializing a fresh test prefix, use builtin Wine DLLs for `wineboot`
and install DXVK afterward. If an earlier diagnostic left initialization
stuck, stop that prefix's Wine server before retrying.
`BIONIC_VULKAN_DRIVER=turnip` retains the Mesa KGSL path explicitly; in that
mode pass `ARLINUX_MESA_SOURCE` as the graphics build's first argument.
`BIONIC_VULKAN_DRIVER=none BIONIC_OPENGL=none` omits the ICD and OpenGL.
Khronos dependencies and TLS archives are pinned and
SHA-256 checked. The adapter build stages its selected sources separately.
The build host needs Meson, Ninja, CMake, Python/Mako, Expat development files,
and Wayland protocol XML.

```bash
tools/build/wine-bionic.sh \
  WINE_SOURCE WINE_TOOLS LLVM_MINGW_BIN NDK_ROOT \
  NATIVE_PREFIX FEX_SOURCE PE_RUNTIME OUTPUT_DIRECTORY
```

Set `BIONIC_ARCHIVE=/absolute/path/arlinux-wine-VERSION.tar.gz` before this
command to also create the compressed runtime and its `.sha256` file. Packaging
checks every file against the generated manifest before compression. Archive
timestamps and ownership are normalized, so identical inputs produce identical
archives. Existing archives are rejected.

The graphics builder enables `xmlconfig` for both fresh and cached Mesa builds,
then records the installed Zink library hashes in
`arlinux-bionic-graphics.json`. Packaging requires that record and verifies its
library hashes; an old prefix with XML configuration disabled must be rebuilt.
PE debug stripping verifies that all runtime sections remain unchanged.

After publishing the immutable runtime asset, set its URL and archive SHA-256
in the rootfs repository's `runtime/tools/windows-downloads.tsv`. Rebuild the
offline desktop and APK using [the Android release workflow](https://github.com/taowen/arlinux/blob/main/docs/ANDROID_RELEASE.md).
The APK downloads this pinned runtime on first Paint.NET launch; the Wine
runtime is a separate download rather than an APK asset.

`PE_RUNTIME` is the extracted shipping Wine package with `files/` and
`arlinux-runtime.json`, including the FEX PE modules and patched CPU defaults.
A bare Wine installation does not contain those modules. Wine is pinned to `afe1b2beeeb1ecdc9152c082eaee552bbe572076`;
FEX is pinned to `82510eb452b258959ef982be58a9c3c1bafc82a4`. The PE build
emits `wine-source.tar.gz`; the Bionic packager records its commit, immutable
source release URL, and SHA-256 in `bionic-runtime.json`. Publish that source
archive alongside the runtime before updating the download manifest. The build
checks the helper source and header hashes before patching. The output contains
`files/` and `bionic-runtime.json`. Packaging resolves native ELF dependencies,
checks ARM64 and the Android interpreter, and records file SHA-256 hashes.
The dependencies opened dynamically by Wine are included explicitly.

Install the archive through `arlinux-windows --install BUNDLE --sha256 SHA256`.
The runtime is stored immutably under `/arlinux-shared/windows-bionic/<sha256>`;
application state remains in the single instance-level Wine prefix.

## Launch

The desktop's Windows apps category includes **Windows Launcher**. Its window
is provided by the Android host. Select an EXE and open the application. The host
keeps its working directory beside the EXE, and remembers recent applications.
The phone file picker resolves a local EXE in place, retaining access to adjacent
DLLs and resources after the required Android file-access grant. It does not
import an isolated EXE copy or support arbitrary remote document providers.
The launcher and Steam games use `~/.local/share/arlinux/windows-bionic/prefix`
(containing `pfx`), independent of the selected runtime version. It reports
startup errors and early process exits, with a path to the native log.
The distribution launcher downloads the pinned Bionic release on first use.

`WindowsRuntimeHost` opens the app-private abstract socket
`arlinux-windows-ANDROID_UID` when the desktop starts. It accepts newline JSON
from the same UID, validates the runtime and paths, and launches Wine with
`ProcessBuilder` in Android. Starting Bionic Wine inside the guest would retain
tawcroot's additional seccomp filter, which cannot be removed.

From the desktop guest:

```bash
arlinux-windows /absolute/path/to/application.exe
```

The launcher resolves and verifies the pinned runtime automatically. Diagnostic
launches should use the shared `windows` module rather than manually constructing
host socket requests or selecting another Wine prefix. Stopping the host
terminates its launchers and requests shutdown of the associated wineservers.

GUI launches wait without an arbitrary application lifetime limit. Diagnostic
`windows.run(..., timeout=SECONDS)` calls have a bounded wait after launch
acknowledgement. `WindowsWaitTimeout` retains the job identity and log path;
it does not claim the application exited. Its explicit `cancel_launcher()`
operation stops only that recorded launcher, never the shared wineserver or
unrelated Windows applications. Detached children are not covered by launcher
cancellation. Host launch acknowledgement and prefix preparation are separately
bounded. Prefix/runtime updates require closing active Windows launchers first.

Integrated authentication uses Samba's `ntlm_auth` from the active Linux
instance. Power BI preparation installs the `winbind` package automatically,
including when revisiting an application installed before this dependency was
added. `WindowsRuntimeHost` prepends an instance-owned helper directory to Wine's
PATH. Its helper enters the guest through `arlinux-exec` and preserves the
authentication protocol on stdin/stdout; Wine itself continues to run under
Android's Bionic libc. No Windows credentials are supplied by the bridge.
The helper receives an explicit loopback interface setting because Android
restricts Samba's network-interface enumeration; it does not start a listener.
`tests/applications/windows-sspi-local.c` checks both NTLM and Negotiate,
including token acquisition and an encrypted message roundtrip.

Guest absolute paths are mapped into the active instance or shared storage.
Prefixes must be in home or shared storage, outside the runtime binaries.
The host selects its private X11 socket and passes its full pathname as
`DISPLAY`; XCB supports this directly. It does not depend on the global
`/tmp/.X11-unix` namespace. System fonts are exposed through Fontconfig.

The host sets the native PulseAudio socket, Wayland runtime directory, and
the ICD selected by `bionic-runtime.json`'s `vulkanDriver`. Older bundles without
that field retain Turnip. Inherited guest Vulkan driver and layer paths are
cleared. It initializes prefixes and installs matching DXVK PE
modules in their Windows system directories. Use
`--dll-overrides 'mshtml=;d3dcompiler_47=n'` for application-specific settings. The EXE's
directory becomes its working directory.

## Validation and limits

For repeated Debug device tests, preserve the app-owned shared download cache
while deleting and reinstalling the tested Linux instance. To prepare missing
installers from a host cache, run:

```powershell
C:\tools\python3.exe tools/cache-windows-downloads.py `
  --manifest build/windows-app-downloads.tsv --serial ANDROID_SERIAL `
  dotnet40 dotnet48 webview2 powerbi
```

Copy the manifest from the current rootfs checkout's
`runtime/tools/windows-app-downloads.tsv` first. The helper checks the device
cache before downloading, checks host and device SHA-256 values, and imports
only official installation files into private `files/shared/downloads`.
Downloads remain in `build/windows-download-cache` for subsequent tests. This
does not restore application installations, account data, or Wine prefixes.

Windows Launcher browses Android's public `Download` directory and its
subdirectories. Extract the complete application folder there, then select its
EXE. Applications run in place with their adjacent DLLs and resources; the
launcher does not import or copy them into private storage. Android's all-files
access setting must be enabled using the launcher button. The guest maps this
directory to `/Download` in sessions started after permission is granted; restart
the Linux desktop after the first grant. Canonical path checks keep launcher
navigation and external Windows executable paths within this directory.

When no usable Wine runtime is installed, selecting an EXE enables **Install Wine
and open**. The launcher uses the existing pinned runtime installer, including
archive and file checksums, a shared installation lock, and atomic installation.
Wine lives in `/arlinux-shared/windows-bionic`, with verified download artifacts
in `/arlinux-shared/downloads`, independently of the active distribution. An
installation failure leaves the launcher available for retry; installation logs
are in `/arlinux-shared/windows-bionic/launcher-install.log`. Closing the launcher
while installing allows the installation to finish but does not open the EXE.

On Xiaomi 15 / Android 17, the APK-hosted ARM64, x64, and x86 process probe
passed child exit status, thread synchronization, and file roundtrips.
`tests/applications/windows-bionic-host.py` also exercises request validation
and opens Notepad. Process maps show Android's Bionic libc and linker64, with
`Seccomp: 2`, `Seccomp_filters: 1`, and no glibc or tawcroot mapping.

Vulkan, audio, and GnuTLS are included and tested on the phone. ARM64, x64,
and x86 passed hardware Direct3D 11 swapchain presentation through
DXVK/Turnip on Adreno 830, waveOut playback completion, HTTPS certificate
verification, and rejection of an untrusted local TLS certificate.
`tests/applications/windows-bionic-backends.c` implements these probes.
A phone screenshot confirmed the rendered clear color. All 5,399 packaged
file hashes matched the installed runtime.

The system Vulkan adapter also passed ARM64, x64, and x86 Direct3D 11 tests
on Adreno 830, using Qualcomm's system driver: 300 presented frames and
swapchain recreation after resizing from 632x446 to 1745x1064. A screenshot
confirmed the clear color. On vivo V2509A / MediaTek MT6993, Mali-G1-Ultra MC12
with Vulkan 1.3.305 passed ARM64 and x64 Direct3D 11 presentation and resize
through the Bionic compatibility layer. A longer run confirmed the blue
window on screen. The layer supplies the missing polygon, clip/cull and BC
capabilities with its existing transformations; merely porting the ICD/WSI
without that layer leaves DXVK unable to create a device on Mali.
These probes cover device creation, clear rendering and presentation, rather
than all emulated shader and texture semantics or complete applications.
The Bionic Zink OpenGL path passed ARM64, x64 and x86 WGL context creation,
pixel readback, window resizing and 600 swaps on both Adreno 830 and
Mali-G1-Ultra MC12. Longer x86 runs confirmed the blue window on both devices.
The Android-hosted Mali x86 probe also passed with automatic Zink selection.
The child-window probe reproduces missing XComposite support: GPU readback
passes but GDI readback and on-screen copying are black. Packaging the X11
libraries opened by Wine at runtime restores the child window and correct
GDI pixels. These libraries are required in addition to OpenGL itself.
The Mali x86 probe currently fails image creation with
`VK_ERROR_INVALID_EXTERNAL_HANDLE`: Wine's WoW64 path requests host-pointer
external memory for images, which this driver rejects. ARM64 and x64 are
usable; Mali x86 requires an additional memory compatibility fix.
The shared native WSI currently exposes RGBA formats to guarantee opaque
RGBX backing.

Paint.NET loads CLR and Direct3D. Its bundled DirectWrite library cannot load
its font from Z:; placing the application in the Bionic prefix C: drive
resolves that failure. The ARM64 APC dispatcher now supplies `APC_CALLBACK_DATA`
when requested, fixing the null context pointer that caused the CLR fatal error
in SleepEx/APC pumping. The CLR probe in
`tests/applications/windows-coreclr-apc.cs` passed 300 callbacks on the phone,
covering ordinary APCs, context callbacks, special context callbacks, stack
walking, and garbage collection. Paint.NET can create a new canvas without
that crash, and its GPU canvas, color wheel and panels render with the shared float-control
correction. Fresh Bionic prefixes on Xiaomi 15 and vivo X300 passed drawing,
PNG saving and reopening, and switching between the main task area and fullscreen
with successful repainting. Power BI's launcher uses Bionic, but the application
has not been validated.

Older bundles omit OpenGL. Standalone Windows launchers use Bionic exclusively; glibc Wine bundles and
prefixes are retired.
The packager removes PE debug sections and separate `.dbg`/`.pdb` files, checking
that executable section contents and addresses remain unchanged. It also omits
the standalone `x86_64-windows` directory: ARM64EC hybrid system DLLs serve x64
applications through FEX. `i386-windows` remains for WoW64 applications.
The r1 archive updated in place is 421,102,056 bytes (down from 1,043,356,647); regular
file payload is approximately 1.59 GB. On Xiaomi 15, a fresh prefix passed ARM64,
x64 and x86 child-process/thread/file-I/O probes and hardware D3D11 presentation.
Paint.NET startup, canvas and color-wheel rendering also passed with the trimmed runtime.
There is no performance comparison yet; x64 and x86 still require FEX.
## Runtime publication

Maintain one `latest` release in `taowen/wine`, with the stable asset name
`arlinux-wine-bionic.tar.gz`. Do not create numbered Bionic release variants.
Wine's upstream version remains runtime metadata; SHA-256 identifies the exact
tested build and keys the download/runtime cache.

After device acceptance, publish the exact tested archive with:

```bash
python tools/publish-wine-latest.py PATH_TO_TESTED_ARCHIVE \
  --source-archive PATH_TO_WINE_SOURCE_ARCHIVE \
  --manifest PATH_TO_ROOTFS/runtime/tools/windows-downloads.tsv
```

The publisher verifies both archives, uploads the source once to the immutable
`arlinux-wine-source-<source-sha256>` release, replaces the `latest` runtime asset,
checks GitHub's asset digest, then updates the rootfs download pin. Use
`--check` to validate without publishing. Rebuild distribution/APK bundles after
updating the pin. On a clean installation, the latest channel resolves the
current GitHub asset ID and SHA-256, so an older APK can fetch the current
runtime. Installed runtimes are reused until Linux reinstallation clears the
shared Wine store and its archive cache. Personal files, installed applications
and unrelated vendor downloads are retained.

## Upstream development refresh (2026-10-16)

The source input is now pinned to ARLinux merge `46af030d975f331ff6304a34a6b91c6147285c6d`,
which includes upstream `7b573fd7522d7e78957bdba1b175c717303923e8` (2026-10-15).
Upstream still calls this development tree Wine 11.19; this is not a Wine 11.20 release.
The Android address-space adaptation was reconciled with upstream's removal of
the old free-range allocation. The WOW64 Vulkan memory patch was rebased to the
new allocation declarations. The WinRT parameterized-interface implementation
is tracked in the source commit, rather than recovered from an older build.

`wine-pe.sh` builds native Wine tools from its own private source tree before
configuring PE modules. Reusing an unrelated older makedep/widl is unsupported.
The new source, native tools and PE build are validated together; a completed
PE build alone does not establish Android or Power BI acceptance.

PE build retries reuse a content-addressed directory under `build/wine-pe/`.
The key covers the Wine commit, component preparation scripts and patches,
compiler/linker binaries, and native build-tool versions. A per-directory lock
rejects concurrent builds with identical inputs. Completed configure steps and
object files survive compilation or packaging failures; changing an input uses
a separate directory. `JOBS` and the output path do not invalidate the cache.
`tests/test-wine-pe-retry.py` exercises failed compilation, repeated packaging,
and invalidation after patch changes with a lightweight build fixture.

## Android shared-storage file security

`wine-bionic-shared-storage-security.patch` projects effective Android app access
into file and directory DACLs on FUSE/sdcardfs. Shared-storage synthetic UIDs
otherwise map to Wine's anonymous SID and can make `AccessCheck(FILE_GENERIC_READ)`
fail even though Wine can open the file. Electron's install-directory preflight
then aborts, reporting misleading AppContainer/ALL APPLICATION PACKAGES advice.

Keep the real owner SID and add only the current user's rights confirmed by
`faccessat` through the open fd. Use flags=0 when real/effective UIDs match;
Android may reject AT_EACCESS with EINVAL. Unequal identities retain AT_EACCESS. Do not grant WRITE_DAC/WRITE_OWNER,
change Android permissions, disable Electron sandboxing, or match device models.
Foreign-owner descriptors are refreshed so scoped-storage grants are not cached
as permanent access. Ordinary private storage keeps upstream behavior.

Regression: fresh Linux instance and prefix, Windows Launcher → Browse Downloads
→ complete extracted VSCode folder → Code.exe; verify an editable document.
Use `tools/diagnostics/windows-file-access.c` in the Android repo to compare
file/folder SDs and impersonation-token AccessCheck against readable Downloads,
private files and an inaccessible path.
