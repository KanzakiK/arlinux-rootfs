#!/usr/bin/env bash
# Experimental native Wine backend; reuse version-matched Windows PE modules.
set -euo pipefail
if [[ $# != 8 ]]; then
    echo 'Usage: wine-bionic.sh WINE_SOURCE WINE_TOOLS LLVM_MINGW_BIN NDK_ROOT NATIVE_PREFIX FEX_SOURCE PE_RUNTIME OUTPUT' >&2
    exit 2
fi
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source_dir="$(realpath "$1")"
tools_dir="$(realpath "$2")"
mingw="$(realpath "$3")"
ndk="$(realpath "$4")/toolchains/llvm/prebuilt/linux-x86_64"
prefix="$(realpath "$5")"
tls="$(realpath "${BIONIC_TLS_PREFIX:-$prefix}")"
pulse="$(realpath "${BIONIC_PULSE_PREFIX:-$prefix}")"
graphics="$(realpath "${BIONIC_GRAPHICS_PREFIX:-$prefix}")"
vulkan_driver="${BIONIC_VULKAN_DRIVER:-system}"
case "${BIONIC_OPENGL:-zink}" in
    zink) opengl_arg=--with-opengl ;;
    none) opengl_arg=--without-opengl ;;
    *) echo 'Unknown BIONIC_OPENGL.' >&2; exit 2 ;;
esac
vulkan_args=(--vulkan-driver "$vulkan_driver")
if [[ -n "${BIONIC_ARCHIVE:-}" ]]; then
    vulkan_args+=(--archive "$(realpath -m "$BIONIC_ARCHIVE")")
fi
if [[ -n "${BIONIC_DXVK_RUNTIME:-}" ]]; then
    vulkan_args+=(--dxvk-runtime "$BIONIC_DXVK_RUNTIME")
fi
if [[ "$vulkan_driver" == system ]]; then
    [[ -d "${BIONIC_DXVK_RUNTIME:-}" ]] || {
        echo 'Build tools/build/bionic-dxvk.sh and set BIONIC_DXVK_RUNTIME.' >&2; exit 2;
    }
    [[ -f "${BIONIC_SYSTEM_VULKAN_ADAPTER:-}" ]] || {
        echo 'Build tools/build/bionic-vulkan.py and set BIONIC_SYSTEM_VULKAN_ADAPTER.' >&2; exit 2;
    }
    vulkan_args+=(--system-vulkan-adapter "$BIONIC_SYSTEM_VULKAN_ADAPTER")
fi
fex_source="$(realpath "$6")"
pe_runtime="$(realpath "$7")"
output="$(realpath -m "$8")"
[[ ! -e "$output" ]] || { echo 'Output already exists.' >&2; exit 2; }
[[ -f "$source_dir/dlls/combase/parameterized.c" ]] || {
    echo 'Use the complete version-matched Wine source, including parameterized.c.' >&2; exit 2;
}
python3 - "$pe_runtime" <<'PY'
import json, sys
from pathlib import Path
manifest = json.loads((Path(sys.argv[1]) / 'arlinux-runtime.json').read_text())
assert manifest['wine_commit'] == '46af030d975f331ff6304a34a6b91c6147285c6d', 'Expected the packaged ARLinux Wine 11.19 runtime'
assert manifest['fex_commit'] == '82510eb452b258959ef982be58a9c3c1bafc82a4', 'FEX PE modules differ from the native helper source'
PY
python3 - "$fex_source" <<'PY'
import hashlib, sys
from pathlib import Path
root = Path(sys.argv[1]) / 'Source/Windows/UnixLib'
expected = {'FEXUnixLib.cpp': '15b1c8ccba37bbe287976e6972e0f27d71c0b076bd9f222fd3c52c7784203eb7',
            'FEXUnixLib.h': '89d62b3ddca282f191e9107b754f5e70a769b120845ab0403e486dc4d717fb34'}
for name, digest in expected.items():
    assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, 'Use the FEX source archive shipped with the PE runtime: ' + name
PY
mkdir -p "$repo/build/wine-bionic"
stage="$(mktemp -d "$repo/build/wine-bionic/build.XXXXXXXX")"
echo "Build directory: $stage"
mkdir "$stage/core" "$stage/fex"
mkdir "$stage/source"
tar -C "$source_dir" --exclude=.git --exclude=autom4te.cache -cf - . | tar -xf - -C "$stage/source"
source_dir="$stage/source"
python3 "$repo/tools/build/refresh-wine-vkd3d.py" "$source_dir"
bash "$repo/tools/build/prepare-wine-dcomp.sh" "$source_dir"
python3 "$repo/tools/build/prepare-wine-gamepad.py" "$source_dir"
python3 - "$source_dir/arlinux-vkd3d.json" "$pe_runtime/arlinux-vkd3d.json" <<'PY'
import json, sys
from pathlib import Path
assert Path(sys.argv[2]).is_file(), 'Rebuild Wine PE modules with the pinned VKD3D refresh first'
assert json.loads(Path(sys.argv[1]).read_text()) == json.loads(Path(sys.argv[2]).read_text()), 'Native and PE VKD3D revisions differ'
for parent in [Path(sys.argv[1]).parent, Path(sys.argv[2]).parent]:
    assert (parent/'arlinux-dcomp.json').is_file(), 'Rebuild Wine PE with DirectComposition first'
assert json.loads((Path(sys.argv[1]).parent/'arlinux-dcomp.json').read_text()) == json.loads((Path(sys.argv[2]).parent/'arlinux-dcomp.json').read_text()), 'Native and PE DirectComposition sources differ'
PY
if ! grep -q '/apex/com.android.conscrypt/cacerts' "$source_dir/dlls/crypt32/unixlib.c"; then
    patch -d "$source_dir" -p1 --batch --fuzz=0 < "$repo/tools/patches/wine-bionic-certificates.patch"
fi
patch -d "$source_dir" -p1 --batch --fuzz=0 < "$repo/tools/patches/wine-bionic-pulse.patch"
patch -d "$source_dir" -p1 --batch --fuzz=0 < "$repo/tools/patches/wine-arm64-apc-context.patch"
patch -d "$source_dir" -p1 --batch --fuzz=0 < "$repo/tools/patches/wine-bionic-local-focus.patch"
patch -d "$source_dir" -p1 --batch --fuzz=0 < "$repo/tools/patches/wine-bionic-dragdrop-owner.patch"
patch -d "$source_dir" -p1 --batch --fuzz=0 < "$repo/tools/patches/wine-bionic-wow64-images.patch"
(cd "$source_dir/dlls/winevulkan" && python3 make_vulkan)
cp "$fex_source/Source/Windows/UnixLib/"{FEXUnixLib.cpp,FEXUnixLib.h} "$stage/fex/"
patch -d "$stage/fex" -p1 --batch --fuzz=0 < "$repo/tools/patches/fex-bionic-unixlib.patch"
export PATH="$mingw:$PATH"
export CC="$ndk/bin/aarch64-linux-android29-clang" CXX="$ndk/bin/aarch64-linux-android29-clang++"
export AR="$ndk/bin/llvm-ar" RANLIB="$ndk/bin/llvm-ranlib"
export CFLAGS='-O2 -g -DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES'
export CPPFLAGS="-I$prefix/include -I$graphics/include" LDFLAGS="-L$prefix/lib -L$graphics/lib -Wl,-z,max-page-size=16384"
export X_CFLAGS="-I$prefix/include" X_LIBS="-L$prefix/lib"
export FREETYPE_CFLAGS="-I$prefix/include/freetype2" FREETYPE_LIBS="-L$prefix/lib -lfreetype"
export FONTCONFIG_CFLAGS="-I$prefix/include" FONTCONFIG_LIBS="-L$prefix/lib -lfontconfig"
export GNUTLS_CFLAGS="-I$tls/include" GNUTLS_LIBS="-L$tls/lib -lgnutls"
export PULSE_CFLAGS="-I$pulse/include" PULSE_LIBS="-L$pulse/lib -Wl,-rpath-link,$pulse/lib/pulseaudio -lpulse"
# configure requires a Gradle executable even with wineandroid.drv disabled.
export PKG_CONFIG_LIBDIR=/nonexistent GRADLE=/bin/true
(
    cd "$stage/core"
    "$source_dir/configure" --host=aarch64-linux-android --enable-wineandroid_drv=no \
        --enable-win64 --enable-archs=arm64ec,aarch64,i386,x86_64 --with-wine-tools="$tools_dir" \
        --disable-tests --with-x --with-freetype --with-fontconfig --without-xshm \
        --without-wayland --without-unwind --with-gnutls --without-gstreamer \
        --without-alsa --with-pulse --without-dbus "$opengl_arg" --with-vulkan \
        --prefix=/arlinux-wine --exec-prefix=/arlinux-wine
) > "$stage/configure.log" 2>&1
if [[ "$opengl_arg" == --with-opengl ]]; then
    grep -q '^#define SONAME_LIBGL ' "$stage/core/include/config.h" || {
        echo 'Wine could not enable OpenGL; check the Bionic graphics prefix.' >&2; exit 2;
    }
fi
grep -q '^#define SONAME_LIBVULKAN ' "$stage/core/include/config.h" || {
    echo 'Wine could not enable Vulkan; check the Bionic graphics prefix.' >&2; exit 2;
}
(
    cd "$stage/core"
    mapfile -t modules < <(sed -n -E 's/^(dlls\/[^ :]*\.so):.*/\1/p' Makefile)
    make -j"${JOBS:-8}" loader/wine server/wineserver "${modules[@]}"
    # winebus PE and Unix halves exchange private structures. Build the driver
    # from this same prepared source instead of reusing a potentially older PE.
    make -j"${JOBS:-8}" dlls/winebus.sys/{aarch64,i386,x86_64}-windows/winebus.sys
) > "$stage/build.log" 2>&1
"$CXX" -std=c++17 -shared -fPIC -static-libstdc++ -O2 -Wl,-z,defs \
    -Wl,-z,max-page-size=16384 "$stage/fex/FEXUnixLib.cpp" -o "$stage/fex/libarm64ecfex.so"
cp "$stage/fex/libarm64ecfex.so" "$stage/fex/libwow64fex.so"
tar -czf "$stage/wine-source.tar.gz" -C "$stage" source
python3 "$repo/tools/package-wine-bionic.py" --core "$stage/core" --fex "$stage/fex" \
    --native-prefix "$prefix" --dependency-prefix "$tls" --dependency-prefix "$pulse" \
    --graphics-prefix "$graphics" --ndk "$ndk" --pe-runtime "$pe_runtime" --output "$output" \
    --wine-source-archive "$stage/wine-source.tar.gz" \
    "${vulkan_args[@]}"
# Local build metadata is written after archive creation; private source/build
# paths never enter the redistributable runtime archive.
python3 - "$stage" "$output" <<'BUILD_STATE'
import json, sys
from pathlib import Path
stage, output = map(Path, sys.argv[1:])
(output/'build-state.json').write_text(json.dumps({'source': str(stage/'source'), 'core': str(stage/'core')}) + '\n')
BUILD_STATE
echo "Built experimental Bionic runtime: $output"
