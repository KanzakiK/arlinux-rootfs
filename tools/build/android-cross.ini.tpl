[binaries]
c = '@NDK_BIN@/aarch64-linux-android@ANDROID_API@-clang'
cpp = '@NDK_BIN@/aarch64-linux-android@ANDROID_API@-clang++'
ar = '@NDK_BIN@/llvm-ar'
strip = '@NDK_BIN@/llvm-strip'
pkg-config = 'pkg-config'
wayland_scanner = '@WAYLAND_SCANNER@'

[host_machine]
system = 'android'
cpu_family = 'aarch64'
cpu = 'aarch64'
endian = 'little'

[built-in options]
c_args = ['-fPIC', '-fvisibility=hidden', '-D_GNU_SOURCE']
c_link_args = ['-Wl,--build-id=sha1']
pkg_config_path = '@PREFIX@/lib/pkgconfig'

[properties]
pkg_config_libdir = '@PREFIX@/lib/pkgconfig'
