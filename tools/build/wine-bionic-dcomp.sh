#!/usr/bin/env bash
# Build an isolated DirectComposition candidate for Bionic Wine; no Proton changes.
set -euo pipefail
if [[ $# != 4 ]]; then
    echo 'Usage: wine-bionic-dcomp.sh WINE_11_19_SOURCE WINE_TOOLS LLVM_MINGW_BIN NEW_OUTPUT' >&2
    exit 2
fi
source_dir="$(realpath "$1")"
wine_tools="$(realpath "$2")"
compiler="$(realpath "$3")"
output="$(realpath -m "$4")"
repo="$(cd "$(dirname "$0")/../.." && pwd)"
[[ ! -e "$output" ]] || { echo 'Output already exists.' >&2; exit 2; }
[[ "$(cat "$source_dir/VERSION")" == 'Wine version 11.19' ]] || {
    echo 'Expected version-matched Wine 11.19 source.' >&2; exit 2;
}
commit=318eda0d8fa08ee94faadf6dc5ad85870339b327
mkdir -p "$output/source" "$output/core"
cp -a "$source_dir/." "$output/source/"
bash "$repo/tools/build/prepare-wine-dcomp.sh" "$output/source"
export PATH="$compiler:$PATH"
(cd "$output/core" && "$output/source/configure" --host=aarch64-w64-mingw32 \
    --enable-win64 --enable-archs=arm64ec,aarch64,i386,x86_64 \
    --with-wine-tools="$wine_tools" --disable-tests --without-wayland --without-unwind \
    --without-x --without-freetype --without-fontconfig --without-gnutls --without-opengl) \
    > "$output/configure.log" 2>&1
make -C "$output/core" -j"${JOBS:-8}" dlls/dcomp/all > "$output/build.log" 2>&1
for arch in aarch64 i386 x86_64; do
    mkdir -p "$output/files/lib/wine/$arch-windows"
    cp "$output/core/dlls/dcomp/$arch-windows/dcomp.dll" "$output/files/lib/wine/$arch-windows/"
done
printf '%s\n' "$commit" > "$output/community-commit"
# Retain LGPL notices and the exact modified source used to produce the DLLs.
tar -czf "$output/wine-source.tar.gz" -C "$output" source
echo "Built diagnostic DComp candidate: $output"
