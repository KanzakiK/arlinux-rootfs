# Project conventions

- Read the canonical [build and release guide](docs/BUILD.md) before building. Maintain build, cache, artifact, and release procedures only there; other documents link to it.
- The public Linux entry point is `build.sh`. Distribution recipes and the hosted-runner coordinator live in `tools/build/`. Do not add parallel builders or document build procedures for unavailable private projects.
- Distribution and Linux graphics builds run on ARM64 GitHub-hosted Linux runners. This repository does not build, integrate or dispatch Bionic Wine. Windows application launchers only download the independently published runtime on demand.
- Each component starts an independent `workflow_dispatch` in its owning public repository. Do not centralize component caches through reusable workflow calls. Repository ownership, runner routing, and dependencies are defined only in `tools/build/github-components.json`; workflow wrappers are generated from the canonical template.
- Reuse build caches only after verifying current inputs, every output, and referenced build files. Do not repackage old distribution ZIPs, installed instances, Wine prefixes, or hand-edited runtime archives as build-cache inputs.
- Maintain third-party customizations in the corresponding forks and pin their commits. Move existing long-lived patch sets into forks over time. Unmodified upstream archives must have fixed versions and verified SHA-256 checksums.
- Write project-maintained documentation, code comments, and developer-facing diagnostics in English. Preserve the intended language of user-facing localization resources and clearly identified upstream translations.
- Maintain local sources with native Windows Git, Python and PowerShell only. Linux-specific tests and compilation run on GitHub-hosted runners; do not create WSL source, build or validation trees.
