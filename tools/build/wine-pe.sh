#!/usr/bin/env bash
# Build version-matched Wine Windows modules; native binaries are built for Bionic.
set -euo pipefail
if [[ $# != 3 ]]; then
    echo 'Usage: wine-pe.sh WINE_SOURCE LLVM_MINGW_BIN OUTPUT_DIRECTORY' >&2
    exit 2
fi
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source_dir="$(realpath "$1")"
export PATH="$(realpath "$2"):$PATH"
destination="$(realpath -m "$3")"
revision=afe1b2beeeb1ecdc9152c082eaee552bbe572076
[[ "$(git -C "$source_dir" rev-parse HEAD)" == "$revision" ]] || {
    echo 'Wine source must match the pinned ARLinux Wine 11.19 revision.' >&2
    exit 2
}
[[ ! -e "$destination" ]] || { echo 'Output directory already exists.' >&2; exit 2; }
mkdir -p "$repo/build/wine-pe"
stage="$(mktemp -d "$repo/build/wine-pe/build.XXXXXXXX")"
mkdir "$stage/source" "$stage/tools" "$stage/core"
echo "Build directory: $stage"
git -C "$source_dir" archive HEAD | tar -xf - -C "$stage/source"
if [[ -n "${ARLINUX_WINE_VKD3D_REFRESH:-}" ]]; then
    python3 "$ARLINUX_WINE_VKD3D_REFRESH" "$stage/source"
fi
(cd "$stage/source" && perl tools/make_requests)
native_triplet="$(gcc -dumpmachine)"
export PKG_CONFIG_LIBDIR="/usr/lib/$native_triplet/pkgconfig:/usr/share/pkgconfig"
pkg-config --exists freetype2 || {
    echo 'Install native FreeType development headers for Wine font generation.' >&2; exit 2;
}
(cd "$stage/tools" && "$stage/source/configure" --enable-win64 --disable-tests \
    --without-mingw --without-x --without-wayland \
    && make -j"${JOBS:-8}" tools/all tools/sfnt2fon/all \
        tools/widl/all tools/winebuild/all tools/winegcc/all tools/wmc/all tools/wrc/all nls/all) \
    > "$stage/tools.log" 2>&1
export PKG_CONFIG_LIBDIR=/usr/lib/aarch64-linux-gnu/pkgconfig:/usr/share/pkgconfig
(cd "$stage/core" && "$stage/source/configure" --host=aarch64-w64-mingw32 --enable-win64 \
    --enable-archs=arm64ec,aarch64,i386,x86_64 --with-wine-tools="$stage/tools" \
    --disable-tests --without-wayland --without-unwind --without-x --without-freetype --without-fontconfig --without-gnutls --without-opengl) > "$stage/configure.log" 2>&1
make -C "$stage/core" -j"${JOBS:-8}" > "$stage/build.log" 2>&1
make -C "$stage/core" install DESTDIR="$stage/install" > "$stage/install.log" 2>&1
rm -rf "$stage/install/usr/local/lib/wine/aarch64-unix"
mkdir "$stage/output"
mv "$stage/install/usr/local" "$stage/output/files"
git -C "$source_dir" rev-parse HEAD > "$stage/output/wine-commit"
cp "$stage/source/VERSION" "$stage/output/wine-version"
if [[ -f "$stage/source/arlinux-vkd3d.json" ]]; then
    cp "$stage/source/arlinux-vkd3d.json" "$stage/output/arlinux-vkd3d.json"
fi
tar -czf "$stage/output/wine-source.tar.gz" -C "$stage" source
mkdir -p "$(dirname "$destination")"
mv -T --no-clobber "$stage/output" "$destination"
[[ ! -d "$stage/output" ]] || { echo 'Destination appeared during build; preserving outputs.' >&2; exit 2; }
echo "Built Wine 11.19 Windows modules in $destination"
