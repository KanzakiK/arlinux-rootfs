#!/usr/bin/env bash
set -euo pipefail
if [[ $# != 2 ]]; then
    echo 'Usage: wine-bionic-tls.sh NDK_ROOT BUILD_DIRECTORY' >&2
    exit 2
fi
base="$(realpath -m "$2")"
prefix=$base/prefix
ndk="$(realpath "$1")/toolchains/llvm/prebuilt/linux-x86_64"
mkdir -p "$base/source" "$prefix"
export CC="$ndk/bin/aarch64-linux-android28-clang" CXX="$ndk/bin/aarch64-linux-android28-clang++" AR="$ndk/bin/llvm-ar" RANLIB="$ndk/bin/llvm-ranlib"
export CFLAGS="-O2 -fPIC -I$prefix/include" CPPFLAGS="-I$prefix/include" LDFLAGS="-L$prefix/lib -Wl,-z,max-page-size=16384" PKG_CONFIG_LIBDIR="$prefix/lib/pkgconfig" ac_cv_func_malloc_0_nonnull=yes ac_cv_func_realloc_0_nonnull=yes
fetch() {
    local url=$1 name=$2 digest=$3 archive="$base/source/$2.tar.xz"
    if [[ ! -f "$archive" ]]; then
        curl -fLsS --connect-timeout 10 --max-time 120 --retry 2 "$url" -o "$archive"
    fi
    echo "$digest  $archive" | sha256sum -c -
    [[ -d "$base/source/$name" ]] || tar -xf "$archive" -C "$base/source"
}
fetch https://mirrors.kernel.org/gnu/gmp/gmp-6.3.0.tar.xz gmp-6.3.0 a3c2b80201b89e68616f4ad30bc66aee4927c3ce50e33929ca819d5c43538898
fetch https://mirrors.kernel.org/gnu/nettle/nettle-3.10.2.tar.gz nettle-3.10.2 fe9ff51cb1f2abb5e65a6b8c10a92da0ab5ab6eaf26e7fc2b675c45f1fb519b5
fetch https://mirrors.kernel.org/gnu/libunistring/libunistring-1.4.1.tar.xz libunistring-1.4.1 67d88430892527861903788868c77802a217b0959990f7449f2976126a307763
fetch https://www.gnupg.org/ftp/gcrypt/gnutls/v3.8/gnutls-3.8.13.tar.xz gnutls-3.8.13 ffed8ec1bf09c2426d4f14aae377de4753b53e537d685e604e99a8b16ca9c97e
build() { local name=$1; shift; if [[ ! -f "$base/$name.done" ]]; then mkdir -p "$base/$name"; cd "$base/$name"; "$base/source/$name/configure" --host=aarch64-linux-android --prefix="$prefix" --disable-static --enable-shared "$@" > "$base/$name-configure.log" 2>&1; make -j8 > "$base/$name-build.log" 2>&1; make install > "$base/$name-install.log" 2>&1; touch "$base/$name.done"; fi; }
build gmp-6.3.0 --disable-assembly
build nettle-3.10.2 --disable-documentation --disable-assembler
build libunistring-1.4.1
build gnutls-3.8.13 --disable-doc --disable-tools --disable-tests --disable-cxx --disable-nls --without-p11-kit --without-idn --without-zlib --without-brotli --without-zstd --with-included-libtasn1 --with-default-trust-store-dir=/apex/com.android.conscrypt/cacerts
printf 'Bionic TLS dependencies built in %s\n' "$prefix"
