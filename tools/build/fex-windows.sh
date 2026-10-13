#!/usr/bin/env bash
# Build both Wine CPU modules and their Unix helpers from one pinned FEX source.
set -euo pipefail
if [[ $# != 2 ]]; then
    echo 'Usage: fex-windows.sh LLVM_MINGW_BIN OUTPUT_DIRECTORY' >&2
    exit 2
fi
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source="$repo/third_party/proton/FEX"
output="$(realpath -m "$2")"
export PATH="$(realpath "$1"):$PATH"
expected="$(git -C "$repo/third_party/proton" ls-tree HEAD FEX | awk '{print $3}')"
[[ "$(git -C "$source" rev-parse HEAD)" == "$expected" ]] || {
    echo 'Initialize the pinned Proton FEX submodule before building.' >&2; exit 2;
}
for dependency in External/{fmt,range-v3,unordered_dense,xxhash,rpmalloc} Source/Common/cpp-optparse; do
    [[ -e "$source/$dependency/.git" ]] || {
        echo "Initialize FEX/$dependency before building." >&2; exit 2;
    }
done
for fix in "$repo/third_party/proton/patches/fex/"*.patch; do
    if ! patch -d "$source" -p1 -R --dry-run < "$fix" >/dev/null 2>&1; then
        patch -d "$source" -p1 --forward < "$fix"
    fi
done
mkdir -p "$output"
for entry in arm64ec:arm64ecfex aarch64:wow64fex; do
    triple="${entry%%:*}"
    module="${entry##*:}"
cmake -G Ninja -S "$source" -B "$output/$triple" \
    -DCMAKE_TOOLCHAIN_FILE="$source/Data/CMake/toolchain_mingw.cmake" \
    -DMINGW_TRIPLE="$triple-w64-mingw32" -DCMAKE_BUILD_TYPE=Release \
    -DENABLE_FEXCORE_PROFILER=True -DENABLE_LTO=False -DBUILD_TESTING=False \
    -DTUNE_CPU=none -DRANGES_NATIVE=OFF -DBUILD_STEAM_SUPPORT=True \
    -DENABLE_VIXL_DISASSEMBLER=OFF -DENABLE_ZYDIS=OFF
cmake --build "$output/$triple" --target "$module" -j"${JOBS:-8}"
install -m755 "$output/$triple/Bin/lib$module.dll" "$output/lib$module.dll"
done
git -C "$source" rev-parse HEAD > "$output/source-commit"
tar -czf "$output/fex-source.tar.gz" --exclude=.git -C "$repo/third_party/proton" FEX
sha256sum "$output/"lib*fex.dll "$output/fex-source.tar.gz"
