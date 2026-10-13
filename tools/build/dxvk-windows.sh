#!/usr/bin/env bash
# Standalone Windows applications need the Vulkan 1.3-compatible DXVK line.
set -euo pipefail
if [[ $# != 2 ]]; then
    echo 'Usage: dxvk-windows.sh LLVM_MINGW_BIN OUTPUT_DIRECTORY' >&2
    exit 2
fi
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
compiler="$(realpath "$1")"
output="$(realpath -m "$2")"
"$compiler/aarch64-w64-mingw32-clang" -marm64x -shared -x c /dev/null -o /dev/null -### 2>/dev/null \
    || { echo 'LLVM-MinGW with ARM64X support (LLVM 23+) is required.' >&2; exit 2; }
revision=6be588b2a57eb28659907834cdeb46bc5f2f69ad
patch_file="$repo/tools/patches/dxvk-optional-pipeline-library.patch"
key="$(printf '%s\n' "$revision" "$compiler" "$(sha256sum "$patch_file")" \
    "$("$compiler/aarch64-w64-mingw32-clang" --version)" | sha256sum | cut -c1-24)"
cache="$repo/build/dxvk-windows/$key"
mkdir -p "$cache" "$output"
if [[ ! -f "$cache/source/src/util/util_singleton.h" ]]; then
    git clone --branch arlinux https://github.com/taowen/dxvk.git "$cache/source"
    git -C "$cache/source" checkout --detach "$revision"
    git -C "$cache/source" submodule update --init --depth 1 \
        include/vulkan include/spirv subprojects/libdisplay-info
fi
if patch -d "$cache/source" -p1 --batch --fuzz=0 --dry-run < "$patch_file" >/dev/null 2>&1; then
    patch -d "$cache/source" -p1 --batch --fuzz=0 < "$patch_file"
else
    patch -d "$cache/source" -p1 --batch --fuzz=0 --reverse --dry-run < "$patch_file" >/dev/null
fi
for arch in aarch64 x86_64 i386; do
    target="$arch"
    family="$arch"
    extra='[]'
    if [[ "$arch" == aarch64 ]]; then
        # One ARM64X DLL serves native ARM64 and emulated x64 clients.
        extra="['-marm64x']"
    elif [[ "$arch" == i386 ]]; then
        target=i686
        family=x86
    fi
    cross="$cache/$arch.ini"
    if [[ ! -f "$cross" ]]; then
    cat > "$cross" <<EOF
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
    fi
    if [[ ! -f "$cache/$arch/build.ninja" ]]; then
        meson setup "$cache/$arch" "$cache/source" --cross-file "$cross" \
            --buildtype release --force-fallback-for=libdisplay-info
    fi
    ninja -C "$cache/$arch" -j"${JOBS:-8}"
    mkdir -p "$output/$arch-windows"
    for dll in dxgi d3d8 d3d9 d3d10core d3d11; do
        directory="$dll"
        [[ "$dll" != d3d10core ]] || directory=d3d10
        install -m755 "$cache/$arch/src/$directory/$dll.dll" "$output/$arch-windows/$dll.dll"
    done
done
printf '%s\n' "$revision" > "$output/source-commit"
tar -czf "$output/source.tar.gz" --exclude=.git -C "$cache" source
