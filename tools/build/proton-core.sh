#!/usr/bin/env bash
# Build a version-matched Android PE-mapping fix, without changing Steam's depot.
set -euo pipefail
if [[ $# != 3 ]]; then
    echo 'Usage: proton-core.sh WINE_SOURCE LLVM_MINGW_BIN OUTPUT_DIRECTORY' >&2
    exit 2
fi
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source_dir="$(realpath "$1")"
export PATH="$(realpath "$2"):$PATH"
destination="$(realpath -m "$3")"
revision=e60892cc2398b0a83c332a2078c7b85e47bdb42b
[[ "$(git -C "$source_dir" rev-parse HEAD)" == "$revision" ]] || {
    echo 'Wine source must match Valve proton-11.0-2e-arm64.' >&2; exit 2;
}
[[ ! -e "$destination" ]] || { echo 'Output directory already exists.' >&2; exit 2; }
mkdir -p "$repo/build/proton-core"
stage="$(mktemp -d "$repo/build/proton-core/build.XXXXXXXX")"
output="$stage/pack"
mkdir "$output"
echo "Build directory: $stage"
mkdir "$stage/wine" "$stage/tools" "$stage/core"
# Export the committed source: unrelated local changes must never enter a pack.
git -C "$source_dir" archive HEAD | tar -xf - -C "$stage/wine"
cp "$repo/third_party/proton/patches/arlinux/0001-ntdll-map-executable-sections-before-relocations.patch" "$stage/execmod.patch"
patch -d "$stage/wine" -p1 --fuzz=0 < "$stage/execmod.patch"
(cd "$stage/wine" && ./dlls/winevulkan/make_vulkan && ./tools/make_specfiles \
    && ./tools/make_requests && autoreconf -fi) > "$stage/generate.log" 2>&1
(cd "$stage/tools" && "$stage/wine/configure" --enable-win64 --disable-tests \
    --without-mingw --without-x --without-wayland --without-freetype \
    && make -j"${JOBS:-8}" tools/widl/all tools/winebuild/all tools/winegcc/all tools/wmc/all tools/wrc/all nls/all) \
    > "$stage/tools.log" 2>&1
(cd "$stage/core" && "$stage/wine/configure" --host=aarch64-linux-gnu --enable-win64 \
    --enable-archs=arm64ec,aarch64,i386,x86_64 --with-wine-tools="$stage/tools" \
    --disable-tests --without-x --without-wayland --without-freetype --without-unwind \
    && make -j"${JOBS:-8}" dlls/ntdll/ntdll.so server/wineserver) > "$stage/core.log" 2>&1
mkdir -p "$output/files/lib/wine/aarch64-unix" "$output/files/bin-arm64"
install -m755 "$stage/core/dlls/ntdll/ntdll.so" "$output/files/lib/wine/aarch64-unix/ntdll.so"
install -m755 "$stage/core/server/wineserver" "$output/files/bin-arm64/wineserver"
aarch64-linux-gnu-strip --strip-debug "$output/files/lib/wine/aarch64-unix/ntdll.so" "$output/files/bin-arm64/wineserver"
printf '%s\n' "$revision" > "$output/wine-commit"
printf '%s\n' proton-11.0-2e-arm64 > "$output/proton-version"
cp "$stage/execmod.patch" "$output/"
tar -czf "$output/wine-source.tar.gz" -C "$stage" wine
python3 - "$output" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
stock = {
    'files/lib/wine/aarch64-unix/ntdll.so': '9c618d49c9926f55d8a28f10c4cfd514d26e654d5bc36a1c639730abf61dd1ff',
    'files/bin-arm64/wineserver': '25ea49371e70b5e9989ee9ff28cadab21b4b6d8f2ff4e235d1e55c16bb77463b',
}
def digest(name):
    with (root/name).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()
manifest = {
    'format': 1, 'version': '1791559733 proton-11.0-2e-arm64',
    'wine_commit': (root/'wine-commit').read_text().strip(),
    'stock': stock, 'files': {name: digest(name) for name in stock},
    'source': {'wine-source.tar.gz': digest('wine-source.tar.gz'),
               'execmod.patch': digest('execmod.patch')},
}
(root/'pack.json').write_text(json.dumps(manifest, indent=2)+'\n')
PY
mkdir -p "$(dirname "$destination")"
mv -T --no-clobber "$output" "$destination"
[[ ! -d "$output" ]] || { echo 'Output appeared during build; preserving both copies.' >&2; exit 2; }
echo "Built matching Proton core in $destination"
