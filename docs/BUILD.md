# Distribution build and release

This repository builds Linux distributions and their native Linux GPU libraries.
It has no Bionic Wine source, build graph, assembly or publishing pipeline.
Application launchers download the independently published runtime when needed.

The only Linux entry is `./build.sh`. Android APK development uses the Android
repository's `build.ps1`, which obtains this independent distribution product.

```sh
python tools/build/install-github-workflows.py
./build.sh github --framework-ref COMMIT --product rootfs --output build/products
./build.sh publish-rootfs yibu TAG build/products/rootfs/default.zip
```

Use Python with zstandard and authenticated gh. Component ownership, ARM64
standard runner labels and dependencies are defined in
`tools/build/github-components.json`. Each repository runs an independent
workflow_dispatch and owns its own 10 GB cache. No WSL compilation is required.
Only matching input/output hashes permit reuse; published component capsules
preserve symlinks and modes. Keep download checksums and archive path safety,
propagate real command failures, and validate APK behavior on a fresh instance.
Do not maintain redundant feature/file presence lists or rescan the same rootfs
at multiple packaging layers. Publish only the exact validated bundle.
