#!/usr/bin/env bash
# Cross-compile anlabwc's bionic Wayland/pixman/cairo deps with the Android NDK.
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
WAYLAND_SCANNER="${WAYLAND_SCANNER:-$(command -v wayland-scanner || true)}"
HOST_PKG_CONFIG_PATH="${HOST_PKG_CONFIG_PATH:-$(pkg-config --variable pc_path pkg-config)}"

export PATH="$NDK_BIN:$PATH"
# Do not set PKG_CONFIG_LIBDIR / SYSROOT globally: meson native lookups
# (wayland-scanner) need the host catalog too.
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig${HOST_PKG_CONFIG_PATH:+:$HOST_PKG_CONFIG_PATH}"

mkdir -p "$PREFIX/lib/pkgconfig" "$PREFIX/include" "$SRC"
cd "$SRC"

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

# Protocol XML is architecture-independent. Keep a pinned copy in the build
# tree instead of depending on the host distribution's package catalog.
WAYLAND_PROTOCOLS_VERSION=1.48
fetch \
    "https://gitlab.freedesktop.org/wayland/wayland-protocols/-/releases/$WAYLAND_PROTOCOLS_VERSION/downloads/wayland-protocols-$WAYLAND_PROTOCOLS_VERSION.tar.xz" \
    "wayland-protocols-$WAYLAND_PROTOCOLS_VERSION.tar.xz"
[[ -d "wayland-protocols-$WAYLAND_PROTOCOLS_VERSION" ]] || \
    tar -xf "wayland-protocols-$WAYLAND_PROTOCOLS_VERSION.tar.xz"
WAYLAND_PROTOCOLS_DIR="$SRC/wayland-protocols-$WAYLAND_PROTOCOLS_VERSION"

# Wayland requires a scanner at least as new as the target library. Build the
# pinned native scanner locally so Linux distributions and macOS/Homebrew do
# not need to provide exactly version 1.25.
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) HOST_TAG=windows-x86_64; scanner_suffix=.exe ;;
    Darwin*) HOST_TAG=darwin-"$(uname -m)"; scanner_suffix= ;;
    *) HOST_TAG=linux-"$(uname -m)"; scanner_suffix= ;;
esac
HOST_TOOLS="$ROOT/build/host-tools/$HOST_TAG"
HOST_SCANNER="$HOST_TOOLS/bin/wayland-scanner$scanner_suffix"
if [[ ! -x "$HOST_SCANNER" ]]; then
    fetch \
        https://gitlab.freedesktop.org/wayland/wayland/-/releases/1.25.0/downloads/wayland-1.25.0.tar.xz \
        wayland-1.25.0.tar.xz
    [[ -d wayland-1.25.0 ]] || tar -xf wayland-1.25.0.tar.xz
    pushd wayland-1.25.0 >/dev/null
    rm -rf build-host
    meson setup build-host --prefix="$HOST_TOOLS" --buildtype=release \
        -Dlibraries=false -Dscanner=true -Dtests=false \
        -Ddocumentation=false -Ddtd_validation=false
    meson compile -C build-host wayland-scanner -j"$JOBS"
    meson install -C build-host
    popd >/dev/null
fi
WAYLAND_SCANNER="$HOST_SCANNER"
host_wayland_pc="$(dirname "$(find "$HOST_TOOLS/lib" -name wayland-scanner.pc -print -quit)")"
HOST_PKG_CONFIG_PATH="$host_wayland_pc${HOST_PKG_CONFIG_PATH:+:$HOST_PKG_CONFIG_PATH}"

# Meson and Ninja run inside MSYS, so both code-generator and XML paths stay
# in the same POSIX namespace even though the scanner itself is a Windows EXE.
WAYLAND_SCANNER_PC="$WAYLAND_SCANNER"
WAYLAND_PROTOCOLS_PC="$WAYLAND_PROTOCOLS_DIR"

sed -e "s|@NDK_BIN@|$NDK_BIN|g" \
    -e "s|@ANDROID_API@|$API|g" \
    -e "s|@WAYLAND_SCANNER@|$WAYLAND_SCANNER|g" \
    -e "s|@PREFIX@|$PREFIX|g" \
    "$RECIPE_DIR/android-cross.ini.tpl" > "$PREFIX/android-cross.ini"
sed "s|@HOST_PKG_CONFIG_PATH@|$HOST_PKG_CONFIG_PATH|g" \
    "$RECIPE_DIR/native.ini.tpl" > "$PREFIX/native.ini"

# --- pkg-config overlays (system EGL, host wayland-protocols) ---
SYSROOT_LIB="$NDK_PREBUILT/sysroot/usr/lib/${TRIPLE}/${API}"
SYSROOT_INC="$NDK_PREBUILT/sysroot/usr/include"

cat > "$PREFIX/lib/pkgconfig/egl.pc" <<EOF
prefix=$NDK_PREBUILT/sysroot/usr
libdir=$SYSROOT_LIB
includedir=$SYSROOT_INC
Name: egl
Description: Android NDK EGL
Version: 1.5
Libs: -L\${libdir} -lEGL
Cflags: -I\${includedir} -DEGL_NO_X11
EOF

cat > "$PREFIX/lib/pkgconfig/glesv2.pc" <<EOF
prefix=$NDK_PREBUILT/sysroot/usr
libdir=$SYSROOT_LIB
includedir=$SYSROOT_INC
Name: glesv2
Description: Android NDK GLESv2
Version: 3.2
Libs: -L\${libdir} -lGLESv2
Cflags: -I\${includedir}
EOF

cat > "$PREFIX/lib/pkgconfig/android.pc" <<EOF
prefix=$NDK_PREBUILT/sysroot/usr
libdir=$SYSROOT_LIB
includedir=$SYSROOT_INC
Name: android
Description: Android NDK libandroid
Version: $API
Libs: -L\${libdir} -landroid
Cflags: -I\${includedir}
EOF

# Host wayland-scanner (meson native: true). PKG_CONFIG_LIBDIR hides brew.
cat > "$PREFIX/lib/pkgconfig/wayland-scanner.pc" <<EOF
wayland_scanner=$WAYLAND_SCANNER_PC
prefix=/usr
Name: Wayland Scanner
Description: host wayland-scanner
Version: 1.25.0
EOF

# XML is arch-independent; use the pinned source tree downloaded above.
wproto_datadir="$WAYLAND_PROTOCOLS_PC"
cat > "$PREFIX/lib/pkgconfig/wayland-protocols.pc" <<EOF
prefix=/usr
datadir=$wproto_datadir
pkgdatadir=$wproto_datadir
Name: Wayland Protocols
Description: host wayland-protocols (XML only)
Version: $WAYLAND_PROTOCOLS_VERSION
EOF

# --- stubs: libinput / libevdev (anlabwc uses a synthetic seat) ---
if [[ ! -f "$PREFIX/lib/libinput.a" || "$RECIPE_DIR/stubs/libinput.h" -nt "$PREFIX/include/libinput.h" ]]; then
    echo "stubs libinput/libevdev"
    "$CC" -c -fPIC -I"$RECIPE_DIR/stubs" \
        "$RECIPE_DIR/stubs/libinput.c" -o "$SRC/libinput.o"
    "$CC" -c -fPIC -I"$RECIPE_DIR/stubs" \
        "$RECIPE_DIR/stubs/libevdev.c" -o "$SRC/libevdev.o"
    "$NDK_BIN/llvm-ar" rcs "$PREFIX/lib/libinput.a" "$SRC/libinput.o"
    "$NDK_BIN/llvm-ar" rcs "$PREFIX/lib/libevdev.a" "$SRC/libevdev.o"
    mkdir -p "$PREFIX/include/libevdev"
    cp "$RECIPE_DIR/stubs/libinput.h" "$PREFIX/include/"
    cp "$RECIPE_DIR/stubs/libevdev/libevdev.h" "$PREFIX/include/libevdev/"
    cat > "$PREFIX/lib/pkgconfig/libinput.pc" <<EOF
prefix=$PREFIX
includedir=\${prefix}/include
libdir=\${prefix}/lib
Name: libinput
Description: stub libinput (anlabwc uses a synthetic seat)
Version: 1.26.0
Libs: -L\${libdir} -linput
Cflags: -I\${includedir}
EOF
    cat > "$PREFIX/lib/pkgconfig/libevdev.pc" <<EOF
prefix=$PREFIX
includedir=\${prefix}/include
libdir=\${prefix}/lib
Name: libevdev
Description: stub libevdev (anlabwc uses a synthetic seat)
Version: 1.13.0
Libs: -L\${libdir} -levdev
Cflags: -I\${includedir}
EOF
fi

build_meson() {
    local name="$1" url="$2" tar="$3" dir="$4"
    shift 4
    if [[ -f "$PREFIX/lib/pkgconfig/${name}.pc" ]] && [[ "$name" != egl ]]; then
        echo "skip $name (pc exists)"
        return 0
    fi
    fetch "$url" "$tar"
    if [[ ! -d "$dir" ]]; then
        # MSYS2 may be unable to materialize optional Unix symlinks on NTFS
        # (libdrm's disabled test fixtures are one example).  Continue only
        # when the actual Meson source tree was extracted successfully.
        if ! tar -xf "$tar"; then
            [[ -f "$dir/meson.build" ]] || return 1
            echo "warning: ignored unsupported archive entries; source tree is usable"
        fi
    fi
    pushd "$dir" >/dev/null
    if [[ -d build && ! -f build/build.ninja ]]; then
        rm -rf build
    fi
    meson setup build --cross-file "$PREFIX/android-cross.ini" \
        --native-file "$PREFIX/native.ini" \
        --prefix="$PREFIX" --libdir=lib --buildtype=release \
        "$@"
    meson compile -C build -j"$JOBS"
    meson install -C build
    popd >/dev/null
}

# libffi (wayland)
if [[ ! -f "$PREFIX/lib/libffi.a" && ! -f "$PREFIX/lib/libffi.so" ]]; then
    fetch https://github.com/libffi/libffi/releases/download/v3.4.6/libffi-3.4.6.tar.gz libffi-3.4.6.tar.gz
    [[ -d libffi-3.4.6 ]] || tar -xzf libffi-3.4.6.tar.gz
    pushd libffi-3.4.6 >/dev/null
    # libffi's automatic out-of-tree restart breaks on Windows-mounted WSL
    # workspaces; configure in place on every supported host instead.
    ./configure --disable-builddir --host="${TRIPLE}" --prefix="$PREFIX" --disable-docs \
        CC="$CC" CXX="$CXX" CFLAGS="-fPIC" CXXFLAGS="-fPIC"
    make -j"$JOBS"
    make install
    popd >/dev/null
fi

build_meson wayland-server \
    https://gitlab.freedesktop.org/wayland/wayland/-/releases/1.25.0/downloads/wayland-1.25.0.tar.xz \
    wayland-1.25.0.tar.xz wayland-1.25.0 \
    -Ddocumentation=false -Dtests=false -Ddtd_validation=false -Dscanner=false

build_meson pixman-1 \
    https://www.cairographics.org/releases/pixman-0.43.4.tar.gz \
    pixman-0.43.4.tar.gz pixman-0.43.4 \
    -Dgtk=disabled -Dlibpng=disabled -Dopenmp=disabled -Dtests=disabled

build_meson xkbcommon \
    https://github.com/xkbcommon/libxkbcommon/archive/refs/tags/xkbcommon-1.7.0.tar.gz \
    xkbcommon-1.7.0.tar.gz libxkbcommon-xkbcommon-1.7.0 \
    -Denable-x11=false -Denable-wayland=false -Denable-docs=false \
    -Denable-tools=false -Denable-xkbregistry=false

build_meson libdrm \
    https://gitlab.freedesktop.org/mesa/drm/-/archive/libdrm-2.4.124/drm-libdrm-2.4.124.tar.gz \
    drm-libdrm-2.4.124.tar.gz libdrm-libdrm-2.4.124-38ec7dbd4df3141441afafe5ac62dfc9df36a77e \
    -Dintel=disabled -Dradeon=disabled -Damdgpu=disabled -Dnouveau=disabled \
    -Dvmwgfx=disabled -Domap=disabled -Dexynos=disabled -Dfreedreno=disabled \
    -Dtegra=disabled -Dvc4=disabled -Detnaviv=disabled -Dfreedreno-kgsl=false \
    -Dinstall-test-programs=false -Dvalgrind=disabled -Dman-pages=disabled \
    -Dtests=false

echo "NDK prefix ready: $PREFIX"
