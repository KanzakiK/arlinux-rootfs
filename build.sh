#!/usr/bin/env bash
# Single Linux product dispatcher. See docs/BUILD.md.
set -euo pipefail
repo="$(cd "$(dirname "$0")" && pwd)"
cd "$repo"
command="${1:---help}"
shift || true
case "$command" in
  gpu) exec python3 tools/build/linux-gpu-component.py "$@" ;;
  github) exec python3 tools/build/github-products.py "$@" ;;
  wine) exec python3 tools/build/wine-pipeline.py "$@" ;;
  rootfs) exec python3 tools/build/desktop-pipeline.py "$@" ;;
  publish-wine) exec python3 tools/publish-wine-latest.py "$@" --manifest "$repo/runtime/tools/windows-downloads.tsv" ;;
  publish-rootfs) exec bash tools/publish-distribution.sh "$@" ;;
  doctor) exec bash tools/build/doctor.sh "$@" ;;
  list) find distributions -mindepth 2 -maxdepth 2 -name product.json -printf '%h\n' | sed 's|.*/||' | sort ;;
  validate) [[ $# -gt 0 ]] || exit 2; for p in "$@"; do python3 tools/validate-distribution.py "$p"; done ;;
  verify) [[ $# -gt 0 ]] || exit 2; for p in "$@"; do python3 tools/bundle.py verify "$p"; done ;;
  --help|-h) echo 'Usage: ./build.sh {wine|rootfs|publish-wine|publish-rootfs|doctor|list|validate|verify} ...'; echo 'Canonical guide: docs/BUILD.md' ;;
  *) echo "Unsupported command: $command. See docs/BUILD.md; build/prepare/offline are removed." >&2; exit 2 ;;
esac
