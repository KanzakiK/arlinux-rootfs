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
while read -r checksum name; do
    curl --fail --location --retry 3 \
        "https://raw.githubusercontent.com/giang17/wine/$commit/$name" \
        --output "$output/source/$name"
    (cd "$output/source" && printf '%s  %s\n' "$checksum" "$name" | sha256sum --check)
done <<'FILES'
bbb898c34121c4124ec444b706c4aeda706b81f704561360bcad8de576489e87 dlls/dcomp/device.c
48d2c35335d4d376f9076c22b5aa4b31f903aeb7fb2db9b76eec0b973da2204f dlls/dcomp/dcomp.spec
7c41e7afa89b2095e0a0facaff7dfd4a263becd545d72ca36e90e5e0f19eb844 include/dcomp.idl
8ab749290bca4c353dd40fc65d686239b9512329d1ff87cffe457ac7d4999ccc include/wine/dcomp_layer.h
52ba56d76cec87605416204ebd630b20eb66da4441c20b52b3300e44cc3ff7bc include/wine/winedxgi.idl
FILES
patch -d "$output/source" -p1 --batch --fuzz=0 < "$repo/tools/patches/wine-dcomp-content-lifetime.patch"
printf 'MODULE = dcomp.dll\nIMPORTS = dxguid uuid user32 gdi32 d2d1\nSOURCES = device.c\n' \
    > "$output/source/dlls/dcomp/Makefile.in"
python3 - "$output/source/include/Makefile.in" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text()
anchor = '\twine/list.h \\\n'
assert text.count(anchor) == 1
path.write_text(text.replace(anchor, anchor + '\twine/dcomp_layer.h \\\n'))
PY
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
