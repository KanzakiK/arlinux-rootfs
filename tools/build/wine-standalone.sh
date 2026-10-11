#!/usr/bin/env bash
# Build one complete, version-matched Wine runtime for arlinux-windows.
set -euo pipefail
if [[ $# != 3 ]]; then
    echo 'Usage: wine-standalone.sh WINE_SOURCE LLVM_MINGW_BIN OUTPUT_DIRECTORY' >&2
    exit 2
fi
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source_dir="$(realpath "$1")"
export PATH="$(realpath "$2"):$PATH"
destination="$(realpath -m "$3")"
revision=455e3509b98a6919fd4ad1def4803e08c41c03b2
[[ "$(git -C "$source_dir" rev-parse HEAD)" == "$revision" ]] || {
    echo 'Wine source must match the pinned Wine 11.19 revision.' >&2
    exit 2
}
[[ ! -e "$destination" ]] || { echo 'Output directory already exists.' >&2; exit 2; }
mkdir -p "$repo/build/wine-standalone"
stage="$(mktemp -d "$repo/build/wine-standalone/build.XXXXXXXX")"
mkdir "$stage/source" "$stage/tools" "$stage/core"
echo "Build directory: $stage"
git -C "$source_dir" archive HEAD | tar -xf - -C "$stage/source"
for number in 0001 0010 0013 0016 0021; do
    patches=("$repo/third_party/proton/patches/arlinux/$number"-*.patch)
    [[ ${#patches[@]} == 1 && -f "${patches[0]}" ]] || {
        echo "Expected one patch for $number." >&2; exit 2;
    }
    patch -d "$stage/source" -p1 --batch --forward --fuzz=0 < "${patches[0]}"
done
for name in anonymous parameterized metadata gdiplus memory-table image-cache actual-relocation; do
    patch -d "$stage/source" -p1 --batch --forward --fuzz=0 \
        < "$repo/third_party/proton/patches/arlinux/wine-11.19/$name.patch"
done
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
(cd "$stage/core" && "$stage/source/configure" --host=aarch64-linux-gnu --enable-win64 \
    --enable-archs=arm64ec,aarch64,i386,x86_64 --with-wine-tools="$stage/tools" \
    --disable-tests --without-wayland --without-unwind) > "$stage/configure.log" 2>&1
# Power BI's local authentication needs the real GnuTLS implementation.
grep -q '^ac_cv_header_gnutls_gnutls_h=yes$' "$stage/core/config.log" || {
    echo 'Install ARM64 GnuTLS development headers before building.' >&2; exit 2;
}
grep -q '^#define SONAME_LIBGNUTLS ' "$stage/core/include/config.h" || {
    echo 'ARM64 GnuTLS library was not detected.' >&2; exit 2;
}
make -C "$stage/core" -j"${JOBS:-8}" > "$stage/build.log" 2>&1
make -C "$stage/core" install DESTDIR="$stage/install" > "$stage/install.log" 2>&1
mkdir "$stage/output"
mv "$stage/install/usr/local" "$stage/output/files"
printf '%s\n' "$revision" > "$stage/output/wine-commit"
cp "$stage/source/VERSION" "$stage/output/wine-version"
tar -czf "$stage/output/wine-source.tar.gz" -C "$stage" source
mkdir -p "$(dirname "$destination")"
mv -T --no-clobber "$stage/output" "$destination"
[[ ! -d "$stage/output" ]] || { echo 'Destination appeared during build; preserving outputs.' >&2; exit 2; }
echo "Built complete Wine 11.19 runtime in $destination"
