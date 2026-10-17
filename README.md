# Arlinux rootfs

Arlinux rootfs is the open Linux side of Arlinux. It cross-builds AArch64 Linux
root filesystems into distribution bundles that can be imported by the Arlinux
Android application. The Android host is intentionally not required to build,
inspect, or extend a distribution.

A bundle contains:

- a distribution-owned root filesystem;
- distribution-native glibc and loader, executed by the host's tawcroot runtime;
- a Qualcomm Turnip/Zink graphics overlay;
- a launch profile and a versioned manifest.

The project is Linux-native. Its build and distribution interfaces use Bash,
Python, and standard Linux tools; there are no Windows or PowerShell build
paths in this repository or its distribution repositories.

## Build an existing distribution

Builds run without root privileges on an x86-64 Debian or Ubuntu host and
produce AArch64 bundles. Install the toolchain once:

```bash
sudo dpkg --add-architecture arm64
sudo apt update
sudo apt install \
  autoconf automake binutils-aarch64-linux-gnu build-essential ca-certificates \
  bison flex curl debootstrap file g++-aarch64-linux-gnu gcc-aarch64-linux-gnu git \
  glslang-tools jq libarchive-tools libtool meson ninja-build patchelf pkgconf:arm64 python3 tar \
  wayland-protocols zstd \
  libegl-dev:arm64 libgl-dev:arm64 libgles-dev:arm64 libglvnd-dev:arm64 libwayland-dev:arm64 \
  libx11-dev:arm64 libx11-xcb-dev:arm64 libxcb1-dev:arm64
```

Clone and build:

```bash
git clone --recurse-submodules https://github.com/taowen/arlinux-rootfs.git
cd arlinux-rootfs
./build.sh doctor
./build.sh list
mkdir -p build/proton-valve
git clone https://github.com/ValveSoftware/wine.git build/proton-valve/wine
git -C build/proton-valve/wine checkout e60892cc2398b0a83c332a2078c7b85e47bdb42b
# Supply an LLVM-MinGW 23+ bin directory with ARM64X support.
bash tools/build/proton-core.sh build/proton-valve/wine /path/to/llvm-mingw/bin build/linux/proton-core
./build.sh build debian
./build.sh verify out/debian.zip
```

Use `./build.sh build` to build every checked-out distribution. Build state is
written to `build/`, finished bundles to `out/`, and reusable downloads to
`${XDG_CACHE_HOME:-$HOME/.cache}/arlinux`. Set `ARLINUX_CACHE_DIR` to move the
cache.

The version-matched Proton core is built once and reused by distribution builds.
Set `ARLINUX_PROTON_CORE` to use another output directory from `proton-core.sh`.
Only its small runtime files enter the rootfs. Publish the matching
`wine-source.tar.gz`, `execmod.patch`, and `pack.json` alongside releases that
contain these Wine binaries; the build verifies their checksums before packaging.

Prebuilt ZIP bundles are published as release assets in each distribution's
own GitHub repository: [Debian](https://github.com/taowen/arlinux-debian/releases),
[Arch](https://github.com/taowen/arlinux-arch/releases),
[Omarchy](https://github.com/taowen/arlinux-omarchy/releases),
[KDE Plasma](https://github.com/taowen/arlinux-plasma/releases), and
[LXQt](https://github.com/taowen/arlinux-lxqt/releases). Download the `.zip`
asset, not GitHub's automatic source-code archive. The Android APK is released
separately; a rootfs bundle is imported after installing it.

## Applications

In a running ARM64 desktop, `arlinux-steam` downloads and starts Valve's native
Steam client. It is not bundled; see [runtime tools](docs/RUNTIME-PROTOCOL.md#native-steam-client)
for installation requirements and limits.

`arlinux-windows` uses the shared Bionic Wine 11.19 runtime, FEX Windows CPU
modules and DXVK. The Android host launches native Wine outside the guest
syscall adapter. The former glibc standalone runtime is no longer supported.

```sh
arlinux-windows /absolute/path/to/application.exe
# Install a locally built, checksum-verified Bionic runtime:
arlinux-windows --install BUNDLE.tar.gz --sha256 SHA256
```

Windows applications and Steam games share one instance-level Bionic Wine
prefix (`~/.local/share/arlinux/windows-bionic/prefix`, containing `pfx`).
`--prefix DIRECTORY` explicitly selects another data directory. Built-in
Paint.NET, Power BI and FontForge icons use the same runtime and Android launch
service. FontForge downloads the checksum-pinned official Windows x64 installer
on first click, installs unattended, then opens the editor. Later clicks launch
the installed copy directly, including an existing installation in the shared
prefix. An incomplete installation remains retryable. Its vendor icon is
extracted from `run_fontforge.exe` in the official 2025-10-09 installer.
Paint.NET and Power BI first installations ask for their vendor licenses.
Paint.NET uses its ARM64 vendor Wine ZIP; Power BI remains an experimental
compatibility target. Existing glibc prefixes are not reused.

Wine Windows modules are built with `tools/build/wine-pe.sh`, FEX PE modules
with `tools/build/fex-windows.sh`, and the PE input with
`tools/package-wine-pe.py`. These inputs contain no glibc native Wine backend.
The host repository's `tools/build/wine-bionic.sh` builds the Android native
backend and `tools/package-wine-bionic.py` packages matching Windows modules,
Bionic libraries, Zink, system Vulkan WSI and the shared GPU compatibility layer.
Publish the matching source archives alongside the binary runtime.

Packaging-only updates can reuse an immutable, SHA-256-verified runtime while
retaining its other compatibility fixes. The same packager refreshes the host
Arial family and copies the matching Unix/PE gamepad driver halves together:

```bash
python3 tools/package-wine-bionic.py --cached-runtime runtime.tar.gz \
  --cached-sha256 SHA256 --core build/native/core \
  --output build/refreshed-runtime --archive out/arlinux-wine-bionic.tar.gz
```

Use the core that built the matching Wine version. This path preserves existing
runtime metadata, verifies every cached file, records the base archive digest,
and creates the same deterministic archive as a full build. Output paths must
be new. It does not rebuild Wine or refresh unrelated native libraries.

DXVK is installed into each private prefix; app-specific DLL overrides remain
under the application's control. For example, use the official Paint.NET Wine
launcher settings for its bundled Microsoft shader compiler.

To develop an Android app **inside** a running Debian/Yibu instance, start with
the [Geany + Kotlin/Gradle project](examples/android-gradle/README.md), or the
smaller [Java example](examples/android-dev/README.md). Both build natively on
the ARM64 phone and run APKs through the host without system installation.

## Create a distribution

A distribution is an independent Git repository placed at
`distributions/<id>`. It does not link against or import the private Android
host. To start a repository alongside the built-in examples:

```bash
git clone https://github.com/you/my-arlinux-distribution.git distributions/my-linux
./build.sh validate distributions/my-linux
./build.sh build my-linux
```

Public reference implementations are:

- [arlinux-debian](https://github.com/taowen/arlinux-debian)
- [arlinux-arch](https://github.com/taowen/arlinux-arch)
- [arlinux-omarchy](https://github.com/taowen/arlinux-omarchy)
- [arlinux-lxqt](https://github.com/taowen/arlinux-lxqt)

Maintainers can publish one distribution from a clean checkout with
`tools/publish-distribution.sh <id> <tag> out/<id>.zip` after testing the ZIP
and authenticating `gh`. It verifies and uploads that exact bundle without
rebuilding it, then creates a release in the distribution's GitHub repository
with the ZIP and its SHA-256 in the release notes.

## Documentation

- [Distribution authoring](docs/DISTRIBUTION-AUTHORING.md): layout, build steps,
  and desktop integration for a new rootfs.
- [Static bundle protocol](docs/STATIC-PROTOCOL.md): required archive contents,
  installation, instances, and first boot.
- [Android–Linux runtime protocol](docs/RUNTIME-PROTOCOL.md): the live session,
  display, input, graphics, audio, and accessibility contract.
- [Graphics acceleration](docs/GRAPHICS.md): how Vulkan, OpenGL, Wayland, X11,
  and AHB fit together, including current limitations.

The [graphics protocol package](graphics-protocols/README.md) documents wire
definitions for Xwayland, Mesa, libhybris, and compositor developers.
The Android host uses [tawcroot](https://github.com/taowen/tawc/tree/main/tawcroot)
for syscall compatibility; distribution libc packages remain unmodified.

## Repository boundaries

Distribution repositories own package selection, rootfs creation, first-boot
configuration, launch profiles, and distribution-specific compatibility
policy. This repository owns the bundle format, guest integration, graphics stack,
cross-build tooling, validation, and shared guest support.

Android UI, input, lifecycle, and bundle installation belong to the private
host. A distribution must not depend on host source code or Android build
artifacts.

## License

Arlinux rootfs is GPL-3.0-or-later. Bundled distributions and third-party
submodules retain their own licenses and notices; distributors are responsible
for preserving all applicable notices in binary bundles.

## Bionic Wine runtime

Wine PE/native compilation, FEX/DXVK integration, Vulkan adapter, patches,
packaging and publication are maintained in this repository. See
[the build and publication guide](docs/WINDOWS-BIONIC.md). Android host builds
consume the resulting bundles and runtime download manifest.

Bionic Wine packages the Windows build host's unmodified Arial family (regular,
bold, italic and bold italic). WSL uses `/mnt/c/Windows/Fonts` by default; set
`ARLINUX_WINDOWS_FONTS` for another input directory. All four files are required.
The desktop build cache fingerprints these inputs and the runtime records their
SHA-256 checksums. Fonts are copied into each Wine prefix before wineboot.
