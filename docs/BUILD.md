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
Request identities use source content and dependency identities rather than the
integration commit alone. Actions caches retain stage archives, receipts and Linux
GPU outputs. Root-owned scratch rootfs trees are deliberately excluded: their
private directory permissions prevent the unprivileged Actions cache from saving.
Guest ownership and modes stay inside snapshot.tar; only host cache files change
owner after the privileged package stage.
After successful publication, the workflow compacts the pipeline cache to the
current input identity and generation of each completed stage. Older directories
still referenced by the current build remain in place. This prevents restored
historical snapshots from accumulating inside every newly saved Actions cache.
The `arlinux-v2-` cache namespace allows saving compacted entries while retaining
the previous namespace as a verified restore seed. The two-attempt
[Yibu check](https://github.com/taowen/arlinux-yibu/actions/runs/39146117964)
passed in 147 and 95 seconds, with a 9-second build step each time. Its saved
cache decreased from 2,359,330,124 to 620,977,341 bytes, with identical output.
Only matching input/output hashes permit reuse; published component capsules
preserve symlinks and modes. Keep download checksums and archive path safety,
propagate real command failures, and validate APK behavior on a fresh instance.
Local coordinators hold a cross-process lock per content identity until the
component is published. Concurrent invocations share the result instead of
dispatching the same workflow twice; process exit automatically releases locks.
Pinned full commit references do not need an extra GitHub commit-resolution call.

Application runtime files and the final sealing recipe do not belong to the APT
snapshot identity. The snapshot tracks its package callback, installer recipes,
bundle packer, distribution and GPU inputs. The desktop stage separately tracks
the sealing and bundle recipes. This prevents compression changes from silently
reusing stale archives or unnecessarily reinstalling packages after the cache
schema has been populated.

Final rootfs compression uses Zstandard level 12 with four threads. A Windows
compression-only benchmark of a real 638,197,760-byte tar stream measured level
19 at 126.1 seconds / 156,531,220 bytes and level 12 at 7.6 seconds /
174,929,387 bytes. Both round trips matched the original SHA-256. These are
compression timings under local load, not total hosted workflow timings.
Do not maintain redundant feature/file presence lists or rescan the same rootfs
at multiple packaging layers. Publish only the exact validated bundle.
