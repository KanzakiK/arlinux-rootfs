#!/usr/bin/env bash
# Rebuild version-matched DXVK with optional graphics pipeline libraries.
set -euo pipefail
if [[ $# != 3 ]]; then
    echo 'Usage: bionic-dxvk.sh DXVK_SOURCE LLVM_MINGW_BIN OUTPUT_DIRECTORY' >&2
    exit 2
fi
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source_dir="$(realpath "$1")"
compiler="$(realpath "$2")"
output="$(realpath -m "$3")"
[[ ! -e "$output" ]] || { echo 'Output already exists.' >&2; exit 2; }
mkdir -p "$output/source"
tar -C "$source_dir" --exclude=.git -cf - . | tar -C "$output/source" -xf -
patch_file="$repo/tools/patches/dxvk-optional-pipeline-library.patch"
if patch -d "$output/source" -p1 --batch --fuzz=0 --dry-run < "$patch_file" >/dev/null 2>&1; then
    patch -d "$output/source" -p1 --batch --fuzz=0 < "$patch_file"
else
    patch -d "$output/source" -p1 --batch --fuzz=0 --reverse --dry-run < "$patch_file" >/dev/null
fi
for arch in aarch64 x86_64 i386; do
    target="$arch"
    family="$arch"
    extra='[]'
    if [[ "$arch" == aarch64 ]]; then
        extra="['-marm64x']"
    elif [[ "$arch" == i386 ]]; then
        target=i686
        family=x86
    fi
    cat > "$output/$arch.ini" <<EOF
[binaries]
c = '$compiler/$target-w64-mingw32-clang'
cpp = '$compiler/$target-w64-mingw32-clang++'
ar = '$compiler/llvm-ar'
strip = '$compiler/llvm-strip'
windres = '$compiler/$target-w64-mingw32-windres'
[built-in options]
c_args = $extra
cpp_args = $extra
c_link_args = $extra
cpp_link_args = $extra
[host_machine]
system = 'windows'
cpu_family = '$family'
cpu = '$target'
endian = 'little'
EOF
    meson setup "$output/build-$arch" "$output/source" --cross-file "$output/$arch.ini" \
        --buildtype release --force-fallback-for=libdisplay-info
    ninja -C "$output/build-$arch" -j"${JOBS:-8}"
    mkdir "$output/$arch-windows"
    for dll in dxgi d3d8 d3d9 d3d10core d3d11; do
        directory="$dll"
        [[ "$dll" != d3d10core ]] || directory=d3d10
        install -m755 "$output/build-$arch/src/$directory/$dll.dll" "$output/$arch-windows/$dll.dll"
    done
done
tar -czf "$output/source.tar.gz" -C "$output" source
