#!/usr/bin/env bash
# NDK deps for anlabwc: xml2, pcre2, glib, freetype, fontconfig, harfbuzz, pango.
# Runs after ndk-wayland.sh (wayland/pixman/cairo/png already in prefix).
set -euo pipefail

ROOT="${ARLINUX_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$RECIPE_DIR/ndk-env.sh"
API="$ANDROID_API"
TRIPLE=aarch64-linux-android
CC="$NDK_BIN/${TRIPLE}${API}-clang"
CXX="$NDK_BIN/${TRIPLE}${API}-clang++"
PREFIX="${NDK_PREFIX:-${NDK_WESTON_PREFIX:-$ROOT/build/ndk-prefix}}"
SRC="$ROOT/build/ndk-src"
JOBS="${JOBS:-$(nproc)}"
HOST_PKG_CONFIG_PATH="${HOST_PKG_CONFIG_PATH:-}"
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) HOST_TAG=windows-x86_64; scanner_suffix=.exe ;;
    Darwin*) HOST_TAG=darwin-"$(uname -m)"; scanner_suffix= ;;
    *) HOST_TAG=linux-"$(uname -m)"; scanner_suffix= ;;
esac
PINNED_WAYLAND_SCANNER="$ROOT/build/host-tools/$HOST_TAG/bin/wayland-scanner$scanner_suffix"
WAYLAND_SCANNER="${WAYLAND_SCANNER:-$PINNED_WAYLAND_SCANNER}"
if [[ ! -x "$WAYLAND_SCANNER" ]]; then
    echo "missing pinned host wayland-scanner: $WAYLAND_SCANNER; run ndk-wayland first" >&2
    exit 2
fi

export PATH="$NDK_BIN:$PATH"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig"

mkdir -p "$PREFIX/lib/pkgconfig" "$SRC"
cd "$SRC"

# Prefer the NDK prefix over host .pc files when cross-compiling.
sed -e "s|@NDK_BIN@|$NDK_BIN|g" \
    -e "s|@ANDROID_API@|$API|g" \
    -e "s|@WAYLAND_SCANNER@|$WAYLAND_SCANNER|g" \
    -e "s|@PREFIX@|$PREFIX|g" \
    "$RECIPE_DIR/android-cross.ini.tpl" > "$PREFIX/android-cross.ini"
# Deps (xml2/glib/pango) must export public symbols; hidden visibility
# would leave an empty dynamic symbol table.
sed -e "s/, '-fvisibility=hidden'//" \
    "$PREFIX/android-cross.ini" > "$PREFIX/android-cross-export.ini"
PREFIX_FOR_INI="$PREFIX" python3 - <<'PY'
from pathlib import Path
import os
prefix = os.environ.get("PREFIX_FOR_INI")
p = Path(prefix) / "android-cross-export.ini"
text = p.read_text()
text = text.replace(
    "c_args = ['-fPIC', '-D_GNU_SOURCE']",
    f"c_args = ['-fPIC', '-D_GNU_SOURCE', '-I{prefix}/include']",
    1,
)
text = text.replace(
    "c_link_args = ['-Wl,--build-id=sha1']",
    f"c_link_args = ['-Wl,--build-id=sha1', '-L{prefix}/lib']",
    1,
)
p.write_text(text)
print(p.read_text())
PY
if ! grep -q pkg_config_libdir "$PREFIX/android-cross.ini"; then
    printf '\n[properties]\npkg_config_libdir = '\''%s/lib/pkgconfig'\''\n' "$PREFIX" \
        >> "$PREFIX/android-cross.ini"
    printf '\n[properties]\npkg_config_libdir = '\''%s/lib/pkgconfig'\''\n' "$PREFIX" \
        >> "$PREFIX/android-cross-export.ini"
fi
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*)
        # Meson itself runs in the MSYS/Cygwin ABI, so its build-machine
        # generators must use the matching MSYS compiler rather than MinGW.
        HOST_CC="${HOST_CC:-/usr/bin/gcc.exe}"
        HOST_CXX="${HOST_CXX:-/usr/bin/g++.exe}"
        HOST_AR="${HOST_AR:-/usr/bin/ar.exe}"
        HOST_STRIP="${HOST_STRIP:-/usr/bin/strip.exe}"
        HOST_PKG_CONFIG_PATH="${HOST_PKG_CONFIG_PATH:-$ROOT/build/host-tools/windows-x86_64/lib/pkgconfig:/ucrt64/lib/pkgconfig}"
        ;;
    *)
        HOST_CC="${HOST_CC:-$(command -v cc)}"
        HOST_CXX="${HOST_CXX:-$(command -v c++)}"
        HOST_AR="${HOST_AR:-$(command -v ar)}"
        HOST_STRIP="${HOST_STRIP:-$(command -v strip)}"
        HOST_PKG_CONFIG_PATH="${HOST_PKG_CONFIG_PATH:-$(pkg-config --variable pc_path pkg-config)}"
        ;;
esac
cat > "$PREFIX/native.ini" <<EOF
[binaries]
c = '$HOST_CC'
cpp = '$HOST_CXX'
ar = '$HOST_AR'
strip = '$HOST_STRIP'
pkg-config = 'pkg-config'

[built-in options]
pkg_config_path = '$HOST_PKG_CONFIG_PATH'
EOF

fetch() {
    local url="$1" name="$2"
    if [[ ! -f "$name" ]]; then
        echo "fetch $name"
        rm -f "$name.part"
        curl -L --fail --retry 5 --retry-all-errors --connect-timeout 20 \
            -o "$name.part" "$url"
        mv "$name.part" "$name"
    fi
}

extract() {
    local tar="$1" dir="$2"
    if [[ ! -d "$dir" ]]; then
        # Some upstream archives contain optional Unix symlinks that MSYS2
        # cannot create on every NTFS configuration.  Accept that limitation
        # only when the real build tree was otherwise extracted intact.
        if ! tar -xf "$tar"; then
            if [[ ! -f "$dir/meson.build" && ! -x "$dir/configure" ]]; then
                return 1
            fi
            echo "warning: ignored unsupported archive entries; source tree is usable"
        fi
    fi
}

meson_cross() {
    meson setup build --cross-file "$PREFIX/android-cross-export.ini" \
        --native-file "$PREFIX/native.ini" \
        --prefix="$PREFIX" --libdir=lib --buildtype=release \
        --default-library=shared \
        "$@"
}

# zlib is supplied by Android's system image/NDK sysroot.  Export metadata so
# target packages such as libpng can express their public dependency on -lz.
if [[ ! -f "$PREFIX/lib/pkgconfig/zlib.pc" ]]; then
    cat > "$PREFIX/lib/pkgconfig/zlib.pc" <<EOF
prefix=$PREFIX
libdir=\${prefix}/lib
includedir=\${prefix}/include

Name: zlib
Description: Android platform zlib
Version: 1.3.0.1-motley
Libs: -lz
Cflags:
EOF
fi

if [[ ! -f "$PREFIX/lib/pkgconfig/libxml-2.0.pc" ]]; then
    echo "== libxml2 =="
    fetch https://download.gnome.org/sources/libxml2/2.13/libxml2-2.13.5.tar.xz libxml2-2.13.5.tar.xz
    extract libxml2-2.13.5.tar.xz libxml2-2.13.5
    pushd libxml2-2.13.5 >/dev/null
    rm -rf build
    meson_cross -Dpython=false -Diconv=disabled -Dhttp=false
    meson compile -C build xml2 -j"$JOBS"
    mkdir -p "$PREFIX/include/libxml" "$PREFIX/lib/pkgconfig"
    cp -a include/libxml/*.h "$PREFIX/include/libxml/"
    cp -a build/include/libxml/xmlversion.h "$PREFIX/include/libxml/"
    cp -a build/libxml2.so "$PREFIX/lib/"
    cp build/meson-private/libxml-2.0.pc "$PREFIX/lib/pkgconfig/"
    popd >/dev/null
fi

if [[ ! -f "$PREFIX/lib/pkgconfig/libpcre2-8.pc" ]]; then
    echo "== pcre2 =="
    fetch https://github.com/PCRE2Project/pcre2/releases/download/pcre2-10.44/pcre2-10.44.tar.bz2 pcre2-10.44.tar.bz2
    extract pcre2-10.44.tar.bz2 pcre2-10.44
    pushd pcre2-10.44 >/dev/null
    make distclean >/dev/null 2>&1 || true
    ./configure --host="$TRIPLE" --prefix="$PREFIX" --libdir="$PREFIX/lib" \
        CC="$CC" CFLAGS="-fPIC" \
        --enable-shared --disable-static \
        --enable-pcre2-8 --disable-pcre2-16 --disable-pcre2-32 \
        --disable-pcre2grep --disable-pcre2test --enable-jit=no
    make -j"$JOBS"
    make install
    popd >/dev/null
fi

# API 28+ bionic already has iconv_open. GNU libiconv's iconv.h in $PREFIX/include
# would redefine iconv_open → libiconv_open; GLib then fails to link libc iconv.
if [[ -f "$PREFIX/include/iconv.h" ]] || [[ -f "$PREFIX/lib/libiconv.so" ]]; then
    echo "== remove GNU libiconv from prefix (use bionic) =="
    rm -f "$PREFIX/include/iconv.h" "$PREFIX/include/libcharset.h" \
        "$PREFIX/include/localcharset.h" \
        "$PREFIX/lib/libiconv.so" "$PREFIX/lib/libiconv.la" \
        "$PREFIX/lib/libcharset.so" "$PREFIX/lib/libcharset.la" \
        "$PREFIX/lib/pkgconfig/iconv.pc" "$PREFIX/bin/iconv"
fi

if [[ ! -f "$PREFIX/lib/pkgconfig/glib-2.0.pc" ]]; then
    echo "== glib =="
    fetch https://download.gnome.org/sources/glib/2.82/glib-2.82.4.tar.xz glib-2.82.4.tar.xz
    extract glib-2.82.4.tar.xz glib-2.82.4
    pushd glib-2.82.4 >/dev/null
    rm -rf build
    meson_cross \
        -Dtests=false -Dintrospection=disabled -Dnls=disabled \
        -Dlibelf=disabled -Dsysprof=disabled -Dglib_debug=disabled \
        -Dlibmount=disabled -Dselinux=disabled -Dxattr=false \
        -Dglib_assert=false -Dglib_checks=false
    meson compile -C build -j"$JOBS"
    meson install -C build
    popd >/dev/null
fi

if [[ ! -f "$PREFIX/lib/pkgconfig/freetype2.pc" ]]; then
    echo "== freetype =="
    # The Savannah endpoint is intermittently unreachable from Windows;
    # use the upstream project's signed-version tag mirror on GitHub.
    fetch https://codeload.github.com/freetype/freetype/tar.gz/refs/tags/VER-2-13-3 freetype-VER-2-13-3.tar.gz
    extract freetype-VER-2-13-3.tar.gz freetype-VER-2-13-3
    pushd freetype-VER-2-13-3 >/dev/null
    rm -rf build
    meson_cross -Dharfbuzz=disabled -Dbrotli=disabled -Dbzip2=disabled \
        -Dpng=enabled -Dzlib=enabled -Dtests=disabled
    meson compile -C build -j"$JOBS"
    meson install -C build
    popd >/dev/null
fi

if [[ ! -f "$PREFIX/lib/pkgconfig/expat.pc" ]]; then
    echo "== expat =="
    fetch https://github.com/libexpat/libexpat/releases/download/R_2_6_4/expat-2.6.4.tar.xz expat-2.6.4.tar.xz
    extract expat-2.6.4.tar.xz expat-2.6.4
    pushd expat-2.6.4 >/dev/null
    make distclean >/dev/null 2>&1 || true
    ./configure --host="$TRIPLE" --prefix="$PREFIX" --libdir="$PREFIX/lib" \
        CC="$CC" CXX="$CXX" CFLAGS="-fPIC" CXXFLAGS="-fPIC" \
        --enable-shared --disable-static --without-xmlwf --without-docbook \
        --without-examples --without-tests
    make -j"$JOBS"
    make install
    popd >/dev/null
fi

if [[ ! -f "$PREFIX/lib/pkgconfig/fontconfig.pc" ]]; then
    echo "== fontconfig =="
    fetch https://www.freedesktop.org/software/fontconfig/release/fontconfig-2.15.0.tar.xz fontconfig-2.15.0.tar.xz
    extract fontconfig-2.15.0.tar.xz fontconfig-2.15.0
    pushd fontconfig-2.15.0 >/dev/null
    rm -rf build
    meson_cross -Ddoc=disabled -Dtests=disabled -Dtools=disabled \
        -Dcache-build=disabled -Dnls=disabled
    meson compile -C build -j"$JOBS"
    meson install -C build
    popd >/dev/null
fi

if [[ ! -f "$PREFIX/lib/pkgconfig/fribidi.pc" ]]; then
    echo "== fribidi =="
    fetch https://github.com/fribidi/fribidi/releases/download/v1.0.16/fribidi-1.0.16.tar.xz fribidi-1.0.16.tar.xz
    extract fribidi-1.0.16.tar.xz fribidi-1.0.16
    pushd fribidi-1.0.16 >/dev/null
    rm -rf build
    meson_cross -Ddocs=false -Dtests=false -Dbin=false
    meson compile -C build -j"$JOBS"
    meson install -C build
    popd >/dev/null
fi

if [[ ! -f "$PREFIX/lib/pkgconfig/harfbuzz.pc" ]]; then
    echo "== harfbuzz =="
    fetch https://github.com/harfbuzz/harfbuzz/releases/download/10.1.0/harfbuzz-10.1.0.tar.xz harfbuzz-10.1.0.tar.xz
    extract harfbuzz-10.1.0.tar.xz harfbuzz-10.1.0
    pushd harfbuzz-10.1.0 >/dev/null
    rm -rf build
    meson_cross -Dtests=disabled -Ddocs=disabled -Dutilities=disabled \
        -Dglib=enabled -Dgobject=disabled -Dcairo=disabled -Dfreetype=enabled \
        -Dicu=disabled -Dintrospection=disabled
    meson compile -C build -j"$JOBS"
    meson install -C build
    popd >/dev/null
fi

if [[ ! -f "$PREFIX/include/cairo/cairo-ft.h" ]]; then
    echo "== cairo (rebuild with freetype) =="
    fetch https://www.cairographics.org/releases/cairo-1.18.4.tar.xz cairo-1.18.4.tar.xz
    extract cairo-1.18.4.tar.xz cairo-1.18.4
    pushd cairo-1.18.4 >/dev/null
    rm -rf build
    meson_cross -Dtests=disabled -Dxlib=disabled -Dxcb=disabled \
        -Dgtk_doc=false -Dpng=enabled \
        -Dfreetype=enabled -Dfontconfig=enabled -Dtee=enabled \
        -Dquartz=disabled -Ddwrite=disabled -Dlzo=disabled \
        -Dspectre=disabled -Dsymbol-lookup=disabled
    meson compile -C build -j"$JOBS"
    meson install -C build
    popd >/dev/null
fi

if [[ ! -f "$PREFIX/lib/pkgconfig/pangocairo.pc" ]]; then
    echo "== pango =="
    fetch https://download.gnome.org/sources/pango/1.54/pango-1.54.0.tar.xz pango-1.54.0.tar.xz
    extract pango-1.54.0.tar.xz pango-1.54.0
    pushd pango-1.54.0 >/dev/null
    rm -rf build
    meson_cross -Dintrospection=disabled -Dbuild-examples=false \
        -Dbuild-testsuite=false -Dfontconfig=enabled -Dfreetype=enabled \
        -Dcairo=enabled -Dxft=disabled -Dlibthai=disabled -Dgtk_doc=false
    meson compile -C build -j"$JOBS"
    meson install -C build
    popd >/dev/null
fi

echo "anlabwc NDK deps ready: $PREFIX"
