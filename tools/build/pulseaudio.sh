#!/usr/bin/env bash
# Cross-compile the pinned PulseAudio/AAudio server on Linux (WSL on Windows).
set -euo pipefail
ROOT="$(cd "$1" && pwd)"
key="$2"
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"
source "$ROOT/tools/build/ndk-env.sh"
for tool in git make autoconf automake libtoolize autopoint intltoolize pkg-config python; do
    command -v "$tool" >/dev/null || {
        echo "Missing $tool. See runtime/pulseaudio/README.md for build dependencies." >&2
        exit 2
    }
done
work="${ARLINUX_PULSE_WORK:-${XDG_CACHE_HOME:-$HOME/.cache}/arlinux/pulseaudio/$key}"
src="$work/source"
prefix="$work/prefix"
out="${ARLINUX_PULSE_OUTPUT:-$ROOT/build/pulseaudio}"
mkdir -p "$work" "$prefix"
# Serialize configure and install when Gradle and the desktop pipeline share a key.
exec 9>"$work/build.lock"
flock 9
checkout() {
    local name="$1" path="$2" repository revision
    read -r repository revision < <(python3 - "$ROOT/runtime/pulseaudio/sources.json" "$name" <<'PY'
import json, sys
source = json.load(open(sys.argv[1]))[sys.argv[2]]
print(source['repository'], source['revision'])
PY
)
    if [[ ! -d "$path/.git" ]]; then
        git clone --no-checkout "$repository" "$path"
        git -C "$path" checkout --detach "$revision"
    fi
    [[ "$(git -C "$path" rev-parse HEAD)" == "$revision" ]]
}
checkout android "$src"
checkout pulseaudio "$src/pulseaudio"
if ! git -C "$src/pulseaudio" apply --reverse --check "$ROOT/runtime/pulseaudio/ndk.patch" 2>/dev/null; then
    git -C "$src/pulseaudio" apply "$ROOT/runtime/pulseaudio/ndk.patch"
fi
export CC="$NDK_BIN/aarch64-linux-android${ANDROID_API}-clang"
export CXX="$NDK_BIN/aarch64-linux-android${ANDROID_API}-clang++"
export AR="$NDK_BIN/llvm-ar" RANLIB="$NDK_BIN/llvm-ranlib" STRIP="$NDK_BIN/llvm-strip"
export CFLAGS="-O2 -fPIC -I$prefix/include"
export LDFLAGS="-L$prefix/lib -Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384"
export PKG_CONFIG_LIBDIR="$prefix/lib/pkgconfig" ACLOCAL_PATH="$prefix/share/aclocal"
export ac_cv_func_mkfifo=no ac_cv_header_glob_h=no ax_cv_PTHREAD_PRIO_INHERIT=no
export ac_cv_func_malloc_0_nonnull=yes ac_cv_func_realloc_0_nonnull=yes
export ac_cv_lib_ltdl_lt_dladvise_init=yes
# NDK libc contains backtrace symbols, but its declarations require API 33.
export ac_cv_header_execinfo_h=no
jobs="${ARLINUX_BUILD_JOBS:-8}"
for library in libtool libsndfile; do
    product=libltdl.so
    [[ "$library" == libsndfile ]] && product=libsndfile.so
    if [[ ! -f "$prefix/lib/$product" ]]; then
        mkdir -p "$src/$library/build-arm64"
        cd "$src/$library/build-arm64"
        if [[ "$library" == libtool ]]; then
            ../configure --host=aarch64-linux-android --prefix="$prefix" HELP2MAN=true MAKEINFO=true
        else
            ../configure --host=aarch64-linux-android --prefix="$prefix" --disable-external-libs --disable-alsa --disable-sqlite
        fi
        # These dependency snapshots already contain generated Autotools files.
        make -j"$jobs" ACLOCAL=true AUTOCONF=true AUTOMAKE=true AUTOHEADER=true
        make install ACLOCAL=true AUTOCONF=true AUTOMAKE=true AUTOHEADER=true
    fi
done
cd "$src/pulseaudio"
if [[ ! -f configure ]]; then
    export LIBTOOLIZE="$(command -v libtoolize)"
    NOCONFIGURE=1 bash ./bootstrap.sh
fi
mkdir -p build-arm64
cd build-arm64
if [[ ! -f Makefile ]]; then
    ../configure --host=aarch64-linux-android --prefix="$prefix" \
        --disable-static --enable-shared --disable-rpath --disable-nls \
        --disable-x11 --disable-oss-wrapper --disable-alsa --disable-esound \
        --disable-waveout --disable-glib2 --disable-gtk3 --disable-gconf \
        --disable-avahi --disable-jack --disable-asyncns --disable-tcpwrap \
        --disable-lirc --disable-dbus --disable-bluez5 --disable-udev \
        --disable-openssl --disable-manpages --disable-samplerate --without-speex \
        --with-database=simple --disable-orc --without-caps --without-fftw \
        --disable-systemd-daemon --disable-systemd-login --disable-systemd-journal \
        --disable-webrtc-aec --disable-tests --disable-neon-opt --disable-gsettings
fi
make -j"$jobs"
make install
"$CC" -shared -O2 -fPIC -I"$src/pulseaudio/build-arm64" -I"$src/pulseaudio/src" \
    -I"$prefix/include" -L"$prefix/lib/pulseaudio" -L"$prefix/lib" \
    -Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384 \
    -o "$prefix/lib/pulse-13.0/modules/module-aaudio-sink.so" \
    "$src/pulseaudio-module/module-aaudio-sink.c" \
    -lpulsecore-13.0 -lpulsecommon-13.0 -lpulse -laaudio
jni="$out/jni/arm64-v8a"
modules="$out/assets/pulseaudio"
mkdir -p "$jni" "$modules"
cp "$prefix/bin/pulseaudio" "$jni/libpulseaudio.so"
cp "$prefix/lib/pulseaudio/"libpulse{core,common}-13.0.so "$jni/"
cp "$prefix/lib/"{libpulse,libsndfile,libltdl}.so "$jni/"
for module in libprotocol-native module-native-protocol-unix module-aaudio-sink; do
    cp "$prefix/lib/pulse-13.0/modules/$module.so" "$modules/"
done
"$STRIP" --strip-unneeded "$jni/"*.so "$modules/"*.so
