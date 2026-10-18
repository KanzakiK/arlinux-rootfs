# Build and release guide

This is the canonical guide for the Android APK and the independent Linux,
graphics, audio and Bionic Wine products. In the `arlinux` checkout, the sole
workstation entry is `build.ps1`, implemented by `tools/build.ps1`. Android is
compiled on Windows; Linux distributions and Wine compile on GitHub-hosted
Linux runners. WSL is not a build dependency.

Linux recipes and their dispatcher live here in `arlinux-rootfs/build.sh` and
`tools/build/`. Public component-only work can use `build.sh github` as its
coordinator; it invokes the same hosted recipes and does not assemble an APK.

## Runner migration status

The GitHub runner implementation currently lives on `codex/github-runners` and
has not yet been merged into `main`. Check out that branch for the commands
below. Integration validation is still in progress; individual successful jobs
do not establish that every final product has passed validation. The former
workstation build instructions are superseded by this guide.

## Independent products

| Product | Build runner and repository | Output |
|---|---|---|
| Android APK | Windows through `arlinux/build.ps1` | Debug APK or signed Release APK |
| Yibu | `ubuntu-24.04-arm` in `taowen/arlinux-yibu` | Distribution ZIP and build receipt |
| Other distributions | ARM64 Linux runner in the corresponding repository | Distribution ZIP and build receipt |
| Linux graphics | ARM64 Linux runners in `taowen/mesa` and `taowen/libhybris` | Verified Mesa and libhybris components |
| Bionic Wine | `ubuntu-24.04` in Wine and dependency repositories | Runtime archive, checksums, and matching sources |
| Audio | `ubuntu-24.04` in `taowen/arlinux-rootfs` | Native libraries and an output receipt |

Yibu neither contains Wine nor waits for its build. Wine is downloaded separately
and shared by the Windows launcher and Steam compatibility tool. Steamworks,
Windows accessibility, and tray helpers accompany that runtime.

Rootfs package preparation runs natively on ARM64. Wine is cross-compiled with
the Linux Android NDK and LLVM-MinGW. Its PE builds are split into ARM64/ARM64EC,
x64, and x86 jobs. FEX, DXVK, TLS, audio, and graphics run in parallel where their
dependencies permit, then converge at the required assembly stages.

## Workflow ownership

`tools/build/github-components.json` is the sole definition of repositories,
runner labels, product targets, and dependencies. Each component starts its own
`workflow_dispatch` in its owning repository through `gh workflow run --repo`.
Do not centralize component builds through reusable workflow calls: jobs and
architectures in one repository share that repository's cache allowance.

Standalone wrappers are generated from `tools/build/github-component.workflow.yml`
by `tools/build/install-github-workflows.py`. They invoke the same `build.sh`
recipes through `tools/build/github-component.py`, without copying build logic.

## Android development, testing and release

Run these commands from the `arlinux` checkout with PowerShell 7. Use Git,
GitHub CLI, native Windows Python with `zstandard`, Node.js, and the Android
SDK/NDK/JDK and native host tools required by `toolchain.json` and the recipes.
Keep versions in their lock/configuration files rather than duplicating them
in another guide. Authenticate GitHub CLI with workflow-dispatch access.

```powershell
.\build.ps1 doctor
.\build.ps1 build -Configuration Debug
.\build.ps1 install -Configuration Debug -Serial SERIAL
.\build.ps1 build -Configuration Release
```

Debug and Release use the same native Android cache, hosted rootfs and audio
products, and Gradle path. Release adds stripping/signing and final Android
binary/signature checks. The APK embeds Yibu, not Wine. Wine and its support
tools are downloaded as one independent runtime by the product.

`-FrameworkRef COMMIT` selects an exact pushed `arlinux-rootfs` revision; the
default is `main`. The entry resolves its full SHA and prepares a native host
source view under `build/cache/sources/arlinux-rootfs/COMMIT`. Concurrent
commands share this view under a preparation lock. Local Android source edits
remain valid development inputs and invalidate only the affected native cache.

Standalone products still use the same workstation entry:

```powershell
.\build.ps1 rootfs -Distribution yibu
.\build.ps1 wine
```

Device installation always uses `tools/install-apk.sh` through the entry. It
handles X300 system confirmation. A rooted test device that refuses ordinary
ADB installation can explicitly select the root mode without changing system
installation settings:

```powershell
$env:ARLINUX_INSTALL_ROOT = '1'
try { .\build.ps1 install -Configuration Debug -Serial SERIAL }
finally { Remove-Item Env:ARLINUX_INSTALL_ROOT }
```

Follow `arlinux/tools/diagnostics/README.md` and `AGENTS.md` for device evidence
and fresh-instance acceptance. Release installation and publishing take the
exact built/tested APK path; publishing never rebuilds it:

```powershell
.\build.ps1 install -Configuration Release -Serial SERIAL -Apk PATH
.\build.ps1 publish -Apk PATH
.\build.ps1 publish-wine -Archive PATH -Check
.\build.ps1 publish-wine -Archive PATH
```

## Prepare the coordinator

A Linux coordinator needs Bash, Git, GitHub CLI, Python 3.12 or later, venv
support, and the `zstandard` Python package. It dispatches jobs and verifies
downloads; compilation happens on the runners. Runner bootstrap obtains build
dependencies and the inputs pinned in `tools/build/github-inputs.json`.

```sh
git clone --branch codex/github-runners https://github.com/taowen/arlinux-rootfs.git
cd arlinux-rootfs
python3 -m venv "$HOME/.cache/arlinux-build/python"
. "$HOME/.cache/arlinux-build/python/bin/activate"
python -m pip install zstandard==0.25.0
gh auth login
```

The authenticated account needs workflow-dispatch access to the component
repositories. Credentials stay on the coordinator. Each component uses its own
temporary `GITHUB_TOKEN` to publish verified outputs. No private source checkout
or private-repository credential is a build input.

After committing and pushing recipes and the template, maintainers synchronize
the standalone workflow wrappers:

```sh
python tools/build/install-github-workflows.py
python tools/build/install-github-workflows.py --check
```

Fork maintainers first update ownership in the component plan. Only public
repositories and the declared standard runner labels are supported.

Build completeness belongs to the dependency graph and its input/output hashes.
Do not maintain parallel lists of required runtime features, DLLs or old package
layouts, or rescan the same rootfs at multiple packaging layers. Read and copy
the declared inputs directly, propagate command failures, and verify behavior
in a fresh device instance. Download checksums, cache integrity, archive path
safety and Android binary/signature requirements remain enforced.

## Build

Run from this repository, using the exact pushed framework commit:

```sh
FRAMEWORK_REF="$(git rev-parse HEAD)"
OUTPUT="$PWD/build/github-products"
./build.sh github --plan --output "$OUTPUT"
./build.sh github --framework-ref "$FRAMEWORK_REF" --product rootfs --output "$OUTPUT"
./build.sh github --framework-ref "$FRAMEWORK_REF" --product wine --output "$OUTPUT"
./build.sh github --framework-ref "$FRAMEWORK_REF" --product audio --output "$OUTPUT"
```

Use `--product all` for all three products, `--distribution omarchy` to select
another rootfs distribution, and `--parallel N` to limit independent workflows
in flight. Available distributions are Yibu, Debian, Arch, Omarchy, Plasma, and
LXQt. LXQt retains its seed/first-install protocol; it must not be described as a
fully prepared offline Yibu image.

Re-running a request resumes an active workflow or reuses its verified published
component. A failed coordinator does not cancel running remote jobs. Builds do
not install anything on a device or publish a moving Wine release.

## Cache and delivery

GitHub Actions includes 10 GB of cache storage per repository, shared by its
jobs. Keep the default limit and use standard hosted runners. This is not 10 GB
per job. See [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

Fixed vendor downloads use repository-shared cache keys. Incremental compiler
caches have explicit size limits. Large complete outputs are delivered as
verified component capsules with build receipts and referenced tool trees.

A cache hit requires matching current inputs, every output, and referenced file
hashes. A previous capsule may seed the cache, but these checks still decide
reuse. Missing or corrupt dependency outputs fail the consumer rather than
silently rebuilding components owned by another repository.

Cache and Actions artifact storage have separate quotas. Cross-repository
handoff uses immutable component prereleases named `arlinux-STAGE-IDENTITY`.
Each records its pinned request, archive checksum, and chunk checksums. The
coordinator verifies these and final product receipts. Tar archives preserve
symbolic links and executable permissions.

Old distribution ZIPs, installed instances, Wine prefixes, and hand-edited
runtime archives are not build caches. A component prerelease is a build input,
not a tested final release, and must not replace a moving download manifest.

| Coordinator output | Path below `--output` |
|---|---|
| Rootfs bundle and receipt | `rootfs/default.zip`, `rootfs/default.json` |
| Wine runtime and matching sources | `wine/` |
| Audio libraries and receipt | `audio/` |
| Resolved products | `products.json` |
| Dispatch and component records | `github-state/` |

## Validation and release

Keep source commits, checksums, receipts, and workflow URLs with validation
results. Validate distribution contents and affected runtime behavior. Use the
exact new product in a fresh instance, without restoring an installed rootfs,
home directory, or Wine prefix. Steam game compatibility requires the Bionic
Wine custom compatibility tool, hardware acceleration, and the normal Play
dependency-preparation path.

Publish only exact artifacts that passed validation; publishers never rebuild
them. Initialize the matching distribution submodule before publishing its
bundle, and ensure all source commits have been pushed.

```sh
# TAG must be the intended vMAJOR.MINOR.PATCH release tag.
./build.sh publish-rootfs yibu "$TAG" "$OUTPUT/rootfs/default.zip"
./build.sh publish-wine "$OUTPUT/wine/arlinux-wine-bionic.tar.gz" --check
./build.sh publish-wine "$OUTPUT/wine/arlinux-wine-bionic.tar.gz"
```

Distribution bundles are published to their own repositories. The Wine publisher
checks matching Wine, FEX, DXVK, and helper sources before updating `taowen/wine`
latest and `runtime/tools/windows-downloads.tsv`. A component build or prerelease
upload does not substitute for runtime validation.

Keep procedures only in this guide. Other documents should link here rather
than maintain alternate build entry points or packaging recipes.
