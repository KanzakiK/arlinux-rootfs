#!/usr/bin/env bash
set -euo pipefail
if [[ $# != 5 ]]; then
    echo 'Usage: wine-bionic-graphics.sh MESA_SOURCE_OR_DASH NDK_ROOT NATIVE_PREFIX GRAPHICS_PROTOCOLS BUILD_DIRECTORY' >&2
    exit 2
fi
mesa="$(realpath -m "$1")"
ndk="$(realpath "$2")/toolchains/llvm/prebuilt/linux-x86_64"
native="$(realpath "$3")"
protocols="$(realpath "$4")"
base="$(realpath -m "$5")"
prefix="$base/prefix"
driver="${BIONIC_VULKAN_DRIVER:-system}"
opengl="${BIONIC_OPENGL:-zink}"
case "$opengl" in zink|none) ;; *) echo 'Unknown BIONIC_OPENGL.' >&2; exit 2 ;; esac
case "$driver" in system|turnip|none) ;; *) echo 'Unknown BIONIC_VULKAN_DRIVER.' >&2; exit 2 ;; esac
if [[ "$opengl" == zink && "$driver" == none ]]; then
    echo 'Zink requires a Vulkan driver.' >&2; exit 2
fi
if [[ "$opengl" == zink && ! -f "$mesa/meson.build" ]]; then
    echo 'Zink requires MESA_SOURCE instead of a dash.' >&2; exit 2
fi
if [[ "$driver" != none && ! -f "$mesa/src/vulkan/wsi/wsi_common_arlinux.c" ]]; then
    echo 'Use ARLinux Mesa with its shared Android buffer WSI.' >&2
    exit 2
fi
mkdir -p "$base" "$prefix/lib/pkgconfig"
fetch() {
    local url=$1 name=$2 digest=$3
    [[ -f "$base/$name" ]] || curl -fLsS --connect-timeout 10 --max-time 120 --retry 2 "$url" -o "$base/$name"
    echo "$digest  $base/$name" | sha256sum -c -
}
# Wine opens these X11 extension libraries with dlopen. Keep them available
# even when they are not dependencies of Mesa or the desktop Vulkan loader.
build_xlib() {
    local name=$1 digest=$2
    fetch "https://www.x.org/releases/individual/lib/$name.tar.xz" "$name.tar.xz" "$digest"
    [[ -d "$base/$name" ]] || tar -xf "$base/$name.tar.xz" -C "$base"
    (
        cd "$base/$name"
        export CC="$ndk/bin/aarch64-linux-android29-clang"
        export CFLAGS="-O2 -fPIC -I$native/include -I$prefix/include"
        export LDFLAGS="-L$prefix/lib -L$native/lib -Wl,-z,max-page-size=16384"
        export xorg_cv_malloc0_returns_null=no
        export PKG_CONFIG_LIBDIR="$prefix/lib/pkgconfig"
        [[ -f Makefile ]] || ./configure --host=aarch64-linux-android --prefix="$prefix" \
            --disable-static --disable-docs --disable-specs --without-xmlto --without-fop
        make -j"${JOBS:-8}"
        make install
    )
}
fetch https://codeload.github.com/KhronosGroup/Vulkan-Headers/tar.gz/refs/tags/v1.4.357 Vulkan-Headers.tar.gz 7dc0dbcf1d49dd3d7da3761c251c6097dfbaac475321a4a8a99269d3d5abecdc
fetch https://codeload.github.com/KhronosGroup/Vulkan-Loader/tar.gz/refs/tags/v1.4.357 Vulkan-Loader.tar.gz 54fa49715782b919092c8353a8a7656180cad1a1b6879b61845e77c261edb2e7
fetch https://gitlab.freedesktop.org/wayland/wayland/-/releases/1.25.0/downloads/wayland-1.25.0.tar.xz wayland-1.25.0.tar.xz c065f040afdff3177680600f249727e41a1afc22fccf27222f15f5306faa1f03
for name in Vulkan-Headers Vulkan-Loader; do
    [[ -d "$base/$name-1.4.357" ]] || tar -xf "$base/$name.tar.gz" -C "$base"
done
[[ -d "$base/wayland-1.25.0" ]] || tar -xf "$base/wayland-1.25.0.tar.xz" -C "$base"
if [[ ! -d "$base/scanner-build" ]]; then
    meson setup "$base/scanner-build" "$base/wayland-1.25.0" --prefix="$base/host-prefix" \
        --buildtype=release -Dlibraries=false -Dscanner=true -Dtests=false \
        -Ddocumentation=false -Ddtd_validation=false
fi
ninja -C "$base/scanner-build" -j"${JOBS:-8}"
meson install -C "$base/scanner-build"
export PATH="$base/host-prefix/bin:$PATH"
export PKG_CONFIG_PATH="$base/host-prefix/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"
cmake -S "$base/Vulkan-Headers-1.4.357" -B "$base/headers-build-1.4.357" -DCMAKE_INSTALL_PREFIX="$prefix"
cmake --install "$base/headers-build-1.4.357"
python3 - "$mesa" "$base" "$native" "$ndk" "$protocols" "$driver" "$opengl" <<'PY'
from pathlib import Path
import re, shutil, sys
mesa, base, native, ndk, protocols = map(Path, sys.argv[1:6])
source = base / 'mesa'
if (sys.argv[6] != 'none' or sys.argv[7] == 'zink') and not source.exists():
    shutil.copytree(mesa, source, symlinks=True,
                    ignore=shutil.ignore_patterns('.git', 'build', 'build-*', 'autom4te.cache'))
    for name in ['src/util/detect_os.h', 'include/vulkan/vk_android_native_buffer.h']:
        p = source / name
        p.write_text(p.read_text().replace('#if defined(__ANDROID__) || defined(ANDROID)', '#if 0')
                     .replace('#if defined(__ANDROID__)', '#if 0'))
    p = source / 'src/util/u_process.c'
    p.write_text(p.read_text().replace('#if DETECT_OS_ANDROID', '#if defined(__ANDROID__)')
                 .replace('#elif DETECT_OS_ANDROID', '#elif defined(__ANDROID__)'))
prefix = base / 'prefix'
# MSYS libtool metadata embeds /c/... paths. Adapt a private link view instead
# of modifying the Windows-produced prefix (which remains a verified input).
libdir = prefix / 'lib'
native_libdir = native / 'lib'
msys_native = re.sub(r'^/mnt/([a-z])/', r'/\1/', str(native))
for p in native_libdir.iterdir():
    target = libdir / p.name
    if p.suffix == '.la':
        target.write_text(p.read_text().replace(msys_native, str(native)).replace(str(native), str(prefix)))
    elif ('.so' in p.name or p.suffix == '.a') and not target.exists():
        target.symlink_to(p)
for p in (native / 'lib/pkgconfig').glob('*.pc'):
    value = p.read_text().replace(msys_native, str(native))
    value = re.sub(r'^libdir=.*$', 'libdir=' + str(libdir), value, flags=re.M)
    (prefix / 'lib/pkgconfig' / p.name).write_text(value)
pc = protocols / 'arlinux-wsi-protocols.pc'
(prefix / 'lib/pkgconfig' / pc.name).write_text(pc.read_text().replace('${pcfiledir}', str(protocols)))
# Host protocol XML and its scanner are used for code generation.
pc = Path('/usr/share/pkgconfig/wayland-protocols.pc')
if pc.exists():
    (prefix / 'lib/pkgconfig' / pc.name).write_text(pc.read_text())
(base / 'cross.ini').write_text(f'''[binaries]
c = '{ndk}/bin/aarch64-linux-android29-clang'
cpp = '{ndk}/bin/aarch64-linux-android29-clang++'
ar = '{ndk}/bin/llvm-ar'
strip = '{ndk}/bin/llvm-strip'
pkg-config = '/usr/bin/pkg-config'
[host_machine]
system = 'linux'
cpu_family = 'aarch64'
cpu = 'armv8'
endian = 'little'
[properties]
needs_exe_wrapper = true
pkg_config_libdir = '{prefix}/lib/pkgconfig'
[built-in options]
c_args = ['-D_GNU_SOURCE', '-I{native}/include']
cpp_args = ['-D_GNU_SOURCE', '-I{native}/include']
c_link_args = ['-L{native}/lib', '-Wl,-z,max-page-size=16384']
cpp_link_args = ['-static-libstdc++', '-L{native}/lib', '-Wl,-z,max-page-size=16384']
''')
PY
export PKG_CONFIG_LIBDIR="$prefix/lib/pkgconfig"
build_xlib libXfixes-6.0.1 b695f93cd2499421ab02d22744458e650ccc88c1d4c8130d60200213abc02d58
# Raw mouse input in Windows games requires both XInput headers and libXi.
build_xlib libXi-1.8.2 d0e0555e53d6e2114eabfa44226ba162d2708501a25e18d99cfb35c094c6c104
build_xlib libXrender-0.9.12 b832128da48b39c8d608224481743403ad1691bf4e554e4be9c174df171d1b97
build_xlib libXcomposite-0.4.6 fe40bcf0ae1a09070eba24088a5eb9810efe57453779ec1e20a55080c6dc2c87
build_xlib libXxf86vm-1.1.6 96af414c73ce1d5449ad04be7f9f27fa8330f844b6dda843ef22e3e1befb3ee3
cmake -S "$base/Vulkan-Loader-1.4.357" -B "$base/loader-build-1.4.357" -G Ninja \
    -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_SYSTEM_PROCESSOR=aarch64 \
    -DCMAKE_C_COMPILER="$ndk/bin/aarch64-linux-android29-clang" \
    -DCMAKE_CXX_COMPILER="$ndk/bin/aarch64-linux-android29-clang++" \
    -DCMAKE_C_FLAGS="-I$native/include" \
    -DCMAKE_SHARED_LINKER_FLAGS="-L$native/lib -Wl,-z,max-page-size=16384" \
    -DCMAKE_FIND_ROOT_PATH="$prefix;$native;$ndk/sysroot" \
    -DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY \
    -DCMAKE_INSTALL_PREFIX="$prefix" -DCMAKE_BUILD_TYPE=Release \
    -DVULKAN_HEADERS_INSTALL_DIR="$prefix" -DBUILD_TESTS=OFF \
    -DBUILD_WSI_XCB_SUPPORT=ON -DBUILD_WSI_XLIB_SUPPORT=ON \
    -DBUILD_WSI_XLIB_XRANDR_SUPPORT=OFF -DBUILD_WSI_WAYLAND_SUPPORT=OFF
cmake --build "$base/loader-build-1.4.357" -j"${JOBS:-8}"
cmake --install "$base/loader-build-1.4.357"
unset PKG_CONFIG_LIBDIR
if [[ "$driver" == none && "$opengl" == none ]]; then
    echo "Built desktop Vulkan loader for $driver driver."
    exit 0
fi
if [[ "$opengl" == zink ]]; then
    vulkan_drivers=[]
    [[ "$driver" == none ]] || vulkan_drivers=freedreno
    if [[ ! -d "$base/build-zink-$driver" ]]; then
        meson setup "$base/build-zink-$driver" "$base/mesa" --cross-file "$base/cross.ini" \
            --prefix="$prefix" -Dplatforms=x11,wayland -Darlinux-wsi=true \
            -Dxlib-lease=disabled -Dvulkan-drivers="$vulkan_drivers" -Dfreedreno-kmds=kgsl \
            -Dgallium-drivers=zink -Dllvm=disabled -Degl=enabled -Dglx=dri \
            -Dgbm=disabled -Dgles1=disabled -Dgles2=enabled -Dopengl=true \
            -Dxmlconfig=enabled -Dzstd=disabled -Dlibunwind=disabled \
            -Dvideo-codecs=[] -Dtools=[] --wrap-mode=nofallback
    else
        meson configure "$base/build-zink-$driver" -Dxmlconfig=enabled -Dvulkan-drivers="$vulkan_drivers"
    fi
    ninja -C "$base/build-zink-$driver" -j"${JOBS:-8}"
    meson install -C "$base/build-zink-$driver"
    python3 - "$base/build-zink-$driver" "$prefix" <<'PY'
import hashlib, json, sys
from pathlib import Path
build, prefix = map(Path, sys.argv[1:])
options = json.loads((build / 'meson-info/intro-buildoptions.json').read_text())
assert next(o['value'] for o in options if o['name'] == 'xmlconfig') == 'enabled'
libraries = {}
for name in ['lib/dri/zink_dri.so', 'lib/dri/libdril_dri.so']:
    with (prefix / name).open('rb') as stream:
        libraries[name] = hashlib.file_digest(stream, 'sha256').hexdigest()
(prefix / 'arlinux-bionic-graphics.json').write_text(json.dumps({
    'protocol': 1, 'openglDriver': 'zink', 'xmlconfig': 'enabled',
    'libraries': libraries,
}, indent=2) + '\n')
PY
    exit 0
fi
if [[ ! -d "$base/build-native" ]]; then
    meson setup "$base/build-native" "$base/mesa" --cross-file "$base/cross.ini" \
        --prefix="$prefix" -Dplatforms=x11,wayland -Darlinux-wsi=true \
        -Dxlib-lease=disabled -Dvulkan-drivers=freedreno -Dfreedreno-kmds=kgsl \
        -Dgallium-drivers=[] -Dllvm=disabled -Degl=disabled -Dglx=disabled \
        -Dgbm=disabled -Dgles1=disabled -Dgles2=disabled -Dopengl=false \
        -Dxmlconfig=disabled -Dzstd=disabled -Dlibunwind=disabled \
        -Dvideo-codecs=[] -Dtools=[] --wrap-mode=nofallback
fi
ninja -C "$base/build-native" -j"${JOBS:-8}"
meson install -C "$base/build-native"
