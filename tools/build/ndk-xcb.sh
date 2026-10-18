#!/usr/bin/env bash
# NDK libxcb + xcb-util-wm for anlabwc HAVE_XWAYLAND (XWM talks xcb).
set -euo pipefail

ROOT="${ARLINUX_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$RECIPE_DIR/ndk-env.sh"
API="$ANDROID_API"
TRIPLE=aarch64-linux-android
CC="$NDK_BIN/${TRIPLE}${API}-clang"
PREFIX="${NDK_PREFIX:-${NDK_WESTON_PREFIX:-$ROOT/build/ndk-prefix}}"
SRC="$ROOT/build/ndk-src"
JOBS="${JOBS:-$(nproc)}"

export PATH="$NDK_BIN:$PATH"
export CC
export CFLAGS="-fPIC -O2 -I$PREFIX/include"
export LDFLAGS="-L$PREFIX/lib"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig:$PREFIX/share/pkgconfig"
export PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig:$PREFIX/share/pkgconfig"
export PKG_CONFIG_SYSROOT_DIR=""

mkdir -p "$PREFIX/lib/pkgconfig" "$SRC"
cd "$SRC"

fetch() {
    local url="$1" name="$2"
    if [[ ! -f "$name" ]]; then
        echo "fetch $name"
        curl -L --fail -o "$name" "$url"
    fi
}

extract() {
    local tar="$1" dir="$2"
    if [[ ! -d "$dir" ]]; then
        tar -xf "$tar"
    fi
}

autotools_install() {
    local dir="$1"
    shift
    pushd "$dir" >/dev/null
    if [[ ! -f Makefile ]]; then
        ./configure --host="$TRIPLE" --prefix="$PREFIX" --libdir="$PREFIX/lib" \
            --disable-static --disable-devel-docs "$@"
    fi
    make -j"$JOBS"
    make install
    popd >/dev/null
}

if [[ ! -f "$PREFIX/share/pkgconfig/xcb-proto.pc" && ! -f "$PREFIX/lib/pkgconfig/xcb-proto.pc" ]]; then
    echo "== xcb-proto =="
    fetch https://xorg.freedesktop.org/archive/individual/proto/xcb-proto-1.17.0.tar.xz \
        xcb-proto-1.17.0.tar.xz
    extract xcb-proto-1.17.0.tar.xz xcb-proto-1.17.0
    pushd xcb-proto-1.17.0 >/dev/null
    ./configure --prefix="$PREFIX"
    make install
    popd >/dev/null
    if [[ -f "$PREFIX/share/pkgconfig/xcb-proto.pc" && ! -f "$PREFIX/lib/pkgconfig/xcb-proto.pc" ]]; then
        ln -s "$PREFIX/share/pkgconfig/xcb-proto.pc" "$PREFIX/lib/pkgconfig/xcb-proto.pc"
    fi
fi

if [[ ! -f "$PREFIX/include/X11/X.h" ]]; then
    echo "== xorgproto =="
    fetch https://xorg.freedesktop.org/archive/individual/proto/xorgproto-2024.1.tar.xz \
        xorgproto-2024.1.tar.xz
    extract xorgproto-2024.1.tar.xz xorgproto-2024.1
    pushd xorgproto-2024.1 >/dev/null
    # Headers only; do not use the NDK clang from CC=.
    env -u CC -u CFLAGS -u LDFLAGS meson setup build --wipe \
        --prefix="$PREFIX" --libdir=lib --buildtype=release \
        --native-file "$PREFIX/native.ini" || \
    env -u CC -u CFLAGS -u LDFLAGS meson setup build \
        --prefix="$PREFIX" --libdir=lib --buildtype=release
    meson install -C build
    popd >/dev/null
fi

if [[ ! -f "$PREFIX/lib/pkgconfig/xau.pc" ]]; then
    echo "== libXau =="
    fetch https://www.x.org/releases/individual/lib/libXau-1.0.11.tar.xz libXau-1.0.11.tar.xz
    extract libXau-1.0.11.tar.xz libXau-1.0.11
    autotools_install libXau-1.0.11
fi

if [[ ! -f "$PREFIX/lib/pkgconfig/xcb.pc" ]]; then
    echo "== libxcb =="
    fetch https://xorg.freedesktop.org/archive/individual/lib/libxcb-1.17.0.tar.xz \
        libxcb-1.17.0.tar.xz
    extract libxcb-1.17.0.tar.xz libxcb-1.17.0
    autotools_install libxcb-1.17.0 --without-doxygen
fi

if [[ ! -f "$PREFIX/lib/pkgconfig/xcb-util.pc" ]]; then
    echo "== xcb-util =="
    fetch https://xcb.freedesktop.org/dist/xcb-util-0.4.1.tar.xz xcb-util-0.4.1.tar.xz
    extract xcb-util-0.4.1.tar.xz xcb-util-0.4.1
    autotools_install xcb-util-0.4.1
fi

if [[ ! -f "$PREFIX/lib/pkgconfig/xcb-ewmh.pc" ]]; then
    echo "== xcb-util-wm =="
    fetch https://xcb.freedesktop.org/dist/xcb-util-wm-0.4.2.tar.xz xcb-util-wm-0.4.2.tar.xz
    extract xcb-util-wm-0.4.2.tar.xz xcb-util-wm-0.4.2
    autotools_install xcb-util-wm-0.4.2
fi

if [[ ! -x "$PREFIX/bin/Xwayland" ]]; then
cat > "$PREFIX/lib/pkgconfig/xwayland.pc" <<'EOF'
prefix=/usr
exec_prefix=${prefix}
Name: Xwayland
Description: Xwayland (bionic binary packaged as libxwayland.so)
Version: 24.1.6
xwayland=/system/bin/false
have_listenfd=true
have_no_touch_pointer_emulation=true
have_force_xrandr_emulation=true
have_terminate_delay=true
EOF
fi

echo "NDK xcb ready: $PREFIX"
