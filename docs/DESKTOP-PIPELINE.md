# Desktop build pipeline

The Windows APK entry is `arlinux/tools/build.ps1 build -Configuration Debug|Release`.
It builds Android native prerequisites on Windows, then invokes this repository's
`tools/build/desktop-pipeline.py` in WSL and embeds the verified desktop ZIP in the APK.
Android signing, alignment checks and publication remain in the Android repository.

The internal Linux command is:

```sh
python3 tools/build/desktop-pipeline.py --config /mnt/c/games/arlinux/build/desktop-build.json \
  --android-repo /mnt/c/games/arlinux --output /mnt/c/games/arlinux/build/cache/artifacts/desktop/default.zip
```

Configuration format 1 contains `framework`, `snapshot`, `snapshotSha256`,
`wineSource`, `mingw`, `ndk`, `bionicPrefix` and `addons`. The Android repository
supplies the example JSON. `wineSource` must be the complete pinned Wine Git
checkout, not an old patched build tree. `addons` contains only the vendor
`mono/` and `gecko/` directories. The native prefix is produced by the Windows
NDK build. Initialize the pinned submodules before building.

The pipeline builds Wine PE, FEX, DXVK, Bionic TLS/PulseAudio/graphics/Vulkan,
Bionic Wine and then the Steamworks ABI bridge against that Wine build. It also
builds the accessibility observer before rebuilding distribution assets and
sealing the package snapshot. No Proton runtime or Proton patch distribution is
built, replaced or installed.

The separate Builder preparation flow is driven by the Windows entry if the
snapshot is missing or its package recipe changed. `--prepare` emits the Builder
input; `--register-snapshot` records its exported SHA-256 and recipe identity.
Only build-only package snapshots are allowed, never a user's installed instance.

Stages live in `build/pipeline/<stage>/<identity>/generation-*/`. A receipt
checks input identity, output hashes and referenced Wine compiler work files.
Successful generations retain their absolute paths; do not relocate build trees.
A failed rebuild cannot replace a previous successful receipt. The pipeline
holds a repository-wide Linux build lock while generating shared assets.
`--rebuild` bypasses stage reuse, while pinned source downloads can remain cached.

Outputs are the desktop ZIP, JSON receipt, Bionic Wine archive and license/source
archives. Wine remains the separately published `latest` runtime; the build
command does not upload it. The receipt records the exact desktop and Wine hashes.
The Android entry also checks the embedded ZIP hash after APK packaging.

Run the pipeline cache and dependency-graph tests on Linux:

```sh
python3 tests/test-desktop-pipeline.py
```

These tests check invalidation, corruption, failed builds, absolute compiler paths
and the Wine dependency graph with simulated compiler outputs. They do not replace
a complete build or real-device clean-instance acceptance.
