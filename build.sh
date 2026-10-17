#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "$0")" && pwd)"
cd "$repo"
command="${1:-build}"
shift || true

products() {
  find distributions -mindepth 2 -maxdepth 2 -name product.json -printf '%h\n' \
    | sed 's|.*/||' | sort
}

select_products() {
  if [[ $# -eq 0 ]]; then mapfile -t selected < <(products); else selected=("$@"); fi
  [[ ${#selected[@]} -gt 0 ]] || { echo 'No distributions found.' >&2; exit 2; }
  for product in "${selected[@]}"; do
    [[ "$product" =~ ^[a-z][a-z0-9-]{0,63}$ ]] || {
      echo "Invalid distribution ID: $product" >&2; exit 2;
    }
    [[ -f "distributions/$product/product.json" ]] || {
      echo "Unknown distribution: $product" >&2; exit 2;
    }
    python3 tools/validate-distribution.py "distributions/$product"
  done
}

case "$command" in
  prepare|offline)
    id="${1:?Specify one distribution}"
    case "$id" in debian|yibu|arch|omarchy) ;; *) echo 'Offline preparation supports debian, yibu, arch and omarchy' >&2; exit 2 ;; esac
    select_products "$id"
    work="build/offline/$id"
    snapshot="${2:-}"
    if [[ "$command" == offline && ! -f "$snapshot" ]]; then
      echo 'offline requires an explicit build-only rootfs TAR snapshot' >&2
      exit 2
    fi
    git submodule update --init --recursive
    ./tools/build/linux-assets.sh "$id"
    mkdir -p "$work"
    python3 tools/bundle.py pack "distributions/$id" "$work/seed.zip"
    if [[ "$command" == prepare ]]; then
      python3 tools/device-desktop.py prepare "$work/seed.zip" "$work/prepare.zip"
    else
      python3 tools/device-desktop.py seal "$work/seed.zip" "$snapshot" "out/$id.zip"
    fi
    ;;
  build)
    select_products "$@"
    git submodule update --init --recursive
    ./tools/build/linux-assets.sh "${selected[@]}"
    for product in "${selected[@]}"; do
      if [[ "$product" == arch || "$product" == omarchy ]]; then
        snapshot="build/offline/$product/rootfs.tar"
        [[ -f "$snapshot" ]] || {
          echo "Prepare an offline desktop first: ./build.sh prepare $product, then ./build.sh offline $product SNAPSHOT.tar" >&2
          exit 2
        }
        python3 tools/bundle.py pack "distributions/$product" "build/offline/$product/seed.zip"
        python3 tools/device-desktop.py seal "build/offline/$product/seed.zip" "$snapshot" "out/$product.zip"
      else
        python3 tools/bundle.py pack "distributions/$product" "out/$product.zip"
      fi
    done
    ;;
  doctor)
    ./tools/build/doctor.sh
    ;;
  list)
    products
    ;;
  validate)
    [[ $# -gt 0 ]] || { echo 'validate requires a distribution directory' >&2; exit 2; }
    for distribution in "$@"; do python3 tools/validate-distribution.py "$distribution"; done
    ;;
  verify)
    [[ $# -gt 0 ]] || { echo 'verify requires at least one bundle' >&2; exit 2; }
    for bundle in "$@"; do python3 tools/bundle.py verify "$bundle"; done
    ;;
  *) echo "usage: $0 {build [ID...]|prepare ID|offline ID SNAPSHOT.tar|doctor|list|validate DIRECTORY...|verify BUNDLE...}" >&2; exit 2 ;;
esac
