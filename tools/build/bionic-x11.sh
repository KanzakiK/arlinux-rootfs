#!/usr/bin/env bash
# Build Wine's Xlib prerequisites from a pinned fork and verified releases.
set -euo pipefail
[[ $# == 4 ]] || { echo 'Usage: bionic-x11.sh BASE_PREFIX LINUX_NDK LIBX11_SOURCE OUTPUT' >&2; exit 2; }
base="$(realpath "$1")"
ndk="$(realpath "$2")/toolchains/llvm/prebuilt/linux-x86_64"
x11="$(realpath "$3")"
output="$(realpath -m "$4")"
[[ "$output" != /mnt/* && ! -e "$output" ]] || { echo 'Require fresh Linux output.' >&2; exit 2; }
prefix="$output/prefix"
mkdir -p "$output/work"
cp -a "$base" "$prefix"
# Bionic provides pthread symbols in libc. Xlib's portable build uses -lpthread.
printf 'INPUT(-lc)\n' > "$prefix/lib/libpthread.so"
export PATH="$ndk/bin:/usr/local/bin:/usr/bin:/bin"
export CC="$ndk/bin/aarch64-linux-android29-clang" CPP="$ndk/bin/aarch64-linux-android29-clang -E"
export AR="$ndk/bin/llvm-ar" RANLIB="$ndk/bin/llvm-ranlib" NM="$ndk/bin/llvm-nm"
export CFLAGS="-fPIC -O2 -I$prefix/include" LDFLAGS="-L$prefix/lib -Wl,-z,max-page-size=16384"
export PKG_CONFIG_LIBDIR="$prefix/lib/pkgconfig:$prefix/share/pkgconfig" PKG_CONFIG_PATH=""
export ACLOCAL_PATH="$prefix/share/aclocal" xorg_cv_malloc0_returns_null=no
fetch() {
    local section=$1 name=$2 sha=$3
    curl -fLsS --connect-timeout 10 --max-time 120 --retry 2 "https://www.x.org/releases/individual/$section/$name.tar.xz" -o "$output/work/$name.tar.xz"
    echo "$sha  $output/work/$name.tar.xz" | sha256sum -c -
    tar -xf "$output/work/$name.tar.xz" -C "$output/work"
}
build() {
    local source=$1; shift
    (
        cd "$source"
        [[ -f configure ]] || autoreconf -fi
        ./configure --host=aarch64-linux-android --prefix="$prefix" --libdir="$prefix/lib" "$@"
        make -j"${JOBS:-8}"
        make install
    )
}
fetch util util-macros-1.20.1 0b308f62dce78ac0f4d9de6888234bf170f276b64ac7c96e99779bb4319bcef5
build "$output/work/util-macros-1.20.1"
fetch lib xtrans-1.5.2 5c5cbfe34764a9131d048f03c31c19e57fb4c682d67713eab6a65541b4dff86c
build "$output/work/xtrans-1.5.2" --disable-docs
mkdir "$output/work/libX11"
git -C "$x11" archive HEAD | tar -xf - -C "$output/work/libX11"
build "$output/work/libX11" --disable-static --enable-shared --disable-specs --without-xmlto --without-fop --disable-devel-docs --enable-unix-transport --disable-tcp-transport --disable-xf86bigfont --without-perl
fetch lib libXext-1.3.6 edb59fa23994e405fdc5b400afdf5820ae6160b94f35e3dc3da4457a16e89753
build "$output/work/libXext-1.3.6" --disable-static --disable-docs --disable-specs --without-xmlto --without-fop
python3 - "$output" "$base" <<'STATE'
import json,sys
from pathlib import Path
(Path(sys.argv[1])/'build-state.json').write_text(json.dumps({'basePrefix':sys.argv[2]})+'\n')
STATE
