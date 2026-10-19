# Distribution build and release

This repository builds Linux distributions and their native Linux GPU libraries.
It has no Bionic Wine source, build graph, assembly or publishing pipeline.
Application launchers download the independently published runtime when needed.

The only Linux entry is `./build.sh`. Android APK development uses the Android
repository's `build.ps1`, which obtains this independent distribution product.

The Android entry's `capture` command selects the independent `vulkan-capture`
stage in `taowen/gfxreconstruct` on the ARM64 standard runner. Its pinned source
is `third_party/gfxreconstruct`; native compilation, verified staging and
`capture.zip` assembly are owned by `tools/build/vulkan-capture-component.py`.
Distributions consume the exact verified capture product as a declared
dependency. The layer, conversion/replay tools and license notices are installed
in `/usr/lib/arlinux/gfxreconstruct`; no capture layer is enabled by default.
The single runtime command `/usr/bin/arlinux-vulkan-capture` selects it only for
its child process. Its archive receipt and per-tool provenance accompany the product.

In the desktop terminal, run `arlinux-vulkan-capture --seconds 30 -- APPLICATION ARGUMENTS`.
It records only that child invocation, defaults to a 512 MiB approximate capture
limit and writes `~/Documents/ARLinux-Captures/TIMESTAMP`. The child is stopped
at the time/size limit; save work first. Captures can contain private data and
are never uploaded automatically. Conversion is explicit (`--convert`), or use
`--lifetimes` for API resource counts. JSON output may be much larger than the
capture. These diagnostics are not performance/compatibility acceptance.

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
The unmodified distribution seed is stored separately as a content-addressed
`.tar.zst` and SHA-256 receipt. Hosted caches include these readable archives,
never their root-owned extracted trees. Every reuse verifies the archive before
extracting guest ownership and links. Runtime-only edits can therefore reuse
the base seed even when the assembled Linux-assets stage changes.

Hosted verification used [run 39196689519](https://github.com/taowen/arlinux-yibu/actions/runs/39196689519)
to populate the seed archive, then [run 39197632409](https://github.com/taowen/arlinux-yibu/actions/runs/39197632409)
with a changed Steam Python launcher. Both workflows passed: 623 seconds and
173 seconds overall, with dispatcher steps of 530 and 73 seconds. The second
log explicitly reports `verified archive cache` for the seed and `OK cached
rootfs-packages` for the APT snapshot. It still rebuilt Linux assets and sealed
the changed runtime into a new distribution; this was not a coordinator-only
cache lookup or reuse of an installed instance. Network/runner time is included.
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

The package stage declares its compiled runtime helpers and Arch Mesa installer
as inputs explicitly; application entry points are not classified by filename
extension. Optional capture archives and their installation recipe belong to
Linux assets and final sealing, not APT preparation. All current runtime files
and capture tools are still input/output-verified in those stages.
Debian package preparation uses deb.debian.org inside the disposable package
rootfs, restoring the distribution's consumer sources before exporting the
snapshot. This does not change the user's repository policy or bypass APT
signature validation. The immutable base seed retains its distribution recipe.
Capture runners install only the native capture dependencies and initialize
GFXReconstruct and its staging-helper repository; GPU compiler jobs do not clone
an unrelated distribution. These preparation paths remain in the same adapter.

Hosted verification on 2026-10-19 used framework
`cae4d3293e4a3b104fe4dc335c11e273f9004e52` for
[the first package rebuild](https://github.com/taowen/arlinux-yibu/actions/runs/39244008771):
208 seconds from dispatch to completion, including 65 seconds of host
preparation, 8 seconds restoring cache, 109 seconds in the product dispatcher
and 10 seconds publishing. The log downloaded 156 MB of Debian packages in
2 seconds from deb.debian.org. The earlier
[Tsinghua-mirror run](https://github.com/taowen/arlinux-yibu/actions/runs/39232216101)
took 1,047 seconds overall, including 946 seconds in the dispatcher and
778 seconds downloading 156 MB. This is an observed network comparison,
not a guaranteed mirror throughput or a compiler speedup. The rebuilt ZIP SHA-256
is `1772dd3b56e8c84fa18978dbfb67175da0a3c186b29d9ff43e5b829523c867a7`;
reading its actual rootfs confirmed that consumer APT sources were restored.

Framework `80540e94103cb79255356859179eb935f4da717a` then changed the
extensionless capture command's documentation and removed the synthetic test
hook, without changing package recipes.
[The changed-runtime build](https://github.com/taowen/arlinux-yibu/actions/runs/39244537290)
passed in 176 seconds overall: host preparation 71 seconds, cache restore
7 seconds, dispatcher 69 seconds and publication 10 seconds. Its log reports
`OK cached rootfs-packages`, reuses the verified seed archive and seals a new
distribution. This demonstrates package-cache reuse, not reuse of an installed
instance. The product adapter no longer runs unrelated synthetic unit tests as
part of building a distribution; production input/output validation remains.

The independently dispatched
[capture product](https://github.com/taowen/gfxreconstruct/actions/runs/39243368620)
passed with 43 seconds of host preparation, compared with 80 seconds in
[the earlier run](https://github.com/taowen/gfxreconstruct/actions/runs/39230755443).
Its incremental build took 12 seconds; this is not a cold compiler benchmark.
These checks validate hosted construction and caching only, not fresh-instance
device compatibility. Environment preparation and Linux-assets assembly remain
material costs after eliminating repeated APT preparation.

Final rootfs compression uses Zstandard level 12 with four threads. A Windows
compression-only benchmark of a real 638,197,760-byte tar stream measured level
19 at 126.1 seconds / 156,531,220 bytes and level 12 at 7.6 seconds /
174,929,387 bytes. Both round trips matched the original SHA-256. These are
compression timings under local load, not total hosted workflow timings.
Do not maintain redundant feature/file presence lists or rescan the same rootfs
at multiple packaging layers. Publish only the exact validated bundle.

Linux GPU cross-compilation invokes ccache explicitly in the Meson cross file
and libhybris CC/CXX commands. The hosted test compiles C and C++ twice in an
isolated cache and requires two hits with identical object files. This changes
compiler caching, not Mesa drivers or its X11/Wayland platform selection.
Distribution-only jobs skip deletion of unrelated preinstalled runner SDKs.

Actions-restored stage generations take precedence over older release seeds;
the ordinary pipeline input/output verification still decides whether they can
be reused. This prevents an older seed overwriting restored Mesa outputs and
triggering an unnecessary rebuild and published-output mismatch.
The [Mesa verification](https://github.com/taowen/mesa/actions/runs/39150751054/attempts/2)
passed in 75 and 62 seconds overall, with build steps of 2 and 1 seconds and
identical published output. The [Yibu verification](https://github.com/taowen/arlinux-yibu/actions/runs/39150885091/attempts/2)
passed in 99 and 75 seconds, with a 9-second build step on the repeat.

Capsule imports stream decompression into tar extraction without writing an
intermediate full tar. Hosted tests retain executable/read-only modes, symlinks
and hardlinks across repeated imports and reject corrupt or escaping archives.

Workstation product downloads persist manifests, partial transfers and verified
capsules under shared `github-state/downloads/COMPONENT_ID` directories. A lock
serializes concurrent consumers of the same component. Missing parts download
in parallel (up to four); completed partial files are verified and promoted
without another request. Interruptions retain
verified parts and partial files for resumption; after assembling and checking
the complete capsule, redundant part copies are removed.
Canonical per-commit product caches can also satisfy another integration pin
when the exact component reference and every output hash match. The coordinator
copies those verified files into the isolated output instead of fetching them
again. A changed component still requires its first transfer; this is a build
cache, not reuse of installed instances or arbitrary release ZIPs.

Client-only coordinator and artifact transport code is excluded from distribution
content inputs. Changing retries, transfer caching or download presentation must
not invalidate the Linux image. Actual rootfs generation scripts, runtime files,
GPU inputs and the package-selection function remain declared inputs.

The real Yibu product from hosted run 39179635023 passed the normal archive and
rootfs receipt checks. A different integration pin with identical component
inputs then reused the verified 191,807,424-byte distribution ZIP in 7.4 seconds,
without binary downloads. Updating the transport implementation also resumed
that same hosted Yibu run rather than dispatching another distribution build.
These results verify build/download behavior, not fresh-instance application
acceptance.
