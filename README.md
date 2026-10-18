# Arlinux rootfs

Arlinux rootfs is the open Linux side of Arlinux. It builds AArch64 Linux
root filesystems into distribution bundles that can be imported by the Arlinux
Android application. Build inputs and component ownership are defined in [BUILD.md](docs/BUILD.md).

A bundle contains:

- a distribution-owned root filesystem;
- distribution-native glibc and loader, executed by the host's tawcroot runtime;
- a Qualcomm Turnip/Zink graphics overlay;
- a launch profile and a versioned manifest.

The project is Linux-native. Its build and distribution interfaces use Bash,
Python, and standard Linux tools. Components compile on GitHub-hosted Linux
runners in their respective repositories.

## Build and release

The only build and release guide is [docs/BUILD.md](docs/BUILD.md).
`build.sh` coordinates independent component workflows on GitHub-hosted Linux
runners. Distribution bundles and Bionic Wine remain separate products. See
the guide for the current runner migration status and checkout requirements.

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
An alternate `--prefix` is rejected; runtime updates do not create a new prefix. Built-in
Paint.NET, Power BI and FontForge icons use the same runtime and Android launch
service. FontForge downloads the checksum-pinned official Windows x64 installer
on first click, installs unattended, then opens the editor. Later clicks launch
the installed copy directly, including an existing installation in the shared
prefix. An incomplete installation remains retryable. Its vendor icon is
extracted from `run_fontforge.exe` in the official 2025-10-09 installer.
Paint.NET and Power BI first installations ask for their vendor licenses.
Paint.NET uses its ARM64 vendor Wine ZIP; Power BI remains an experimental
compatibility target. Existing glibc prefixes are not reused.

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

See [the canonical build guide](docs/BUILD.md) for validation and building.

Public reference implementations are:

- [arlinux-debian](https://github.com/taowen/arlinux-debian)
- [arlinux-arch](https://github.com/taowen/arlinux-arch)
- [arlinux-omarchy](https://github.com/taowen/arlinux-omarchy)
- [arlinux-lxqt](https://github.com/taowen/arlinux-lxqt)

Publish tested artifacts through the entry described in [BUILD.md](docs/BUILD.md).

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
[the build and publication guide](docs/BUILD.md). Android host builds
consume the resulting bundles and runtime download manifest.

Bionic Wine packages the Windows build host's unmodified Arial family (regular,
bold, italic and bold italic). WSL uses `/mnt/c/Windows/Fonts` by default; set
`ARLINUX_WINDOWS_FONTS` for another input directory. All four files are required.
The Wine build cache fingerprints these inputs and the runtime records their
SHA-256 checksums. Fonts are copied into each Wine prefix before wineboot.
