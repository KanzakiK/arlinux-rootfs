#!/usr/bin/env bash
# Compile Bionic Wine prerequisites with the Linux NDK in a private Linux tree.
set -euo pipefail
[[ $# == 3 ]] || { echo 'Usage: bionic-deps.sh ANDROID_SOURCES LINUX_NDK OUTPUT' >&2; exit 2; }
sources="$(realpath "$1")"
ndk="$(realpath "$2")"
output="$(realpath -m "$3")"
[[ "$(uname -s)" == Linux && "$output" != /mnt/* && "$ndk" != /mnt/* ]] || {
    echo 'Bionic Wine prerequisites require Linux tools and a Linux filesystem build directory.' >&2; exit 2;
}
[[ ! -e "$output" ]] || { echo 'Output already exists.' >&2; exit 2; }
work="$output/work"
mkdir -p "$work/tools/build"
cp "$sources/toolchain.json" "$work/"
for recipe in ndk-env.sh ndk-wayland.sh ndk-deps.sh ndk-xcb.sh android-cross.ini.tpl native.ini.tpl; do
    cp "$sources/tools/build/$recipe" "$work/tools/build/"
done
cp -a "$sources/tools/build/stubs" "$work/tools/build/"
export ARLINUX_DIR="$work" ANDROID_NDK_HOME="$ndk" NDK_PREFIX="$output/prefix" JOBS="${JOBS:-8}"
unset ANDROID_HOME ANDROID_SDK_ROOT ARLINUX_BASH NINJA CC CXX CFLAGS CXXFLAGS LDFLAGS PKG_CONFIG_PATH PKG_CONFIG_LIBDIR
export PATH="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin:$PATH"
for recipe in ndk-wayland ndk-deps ndk-xcb; do
    bash "$work/tools/build/$recipe.sh"
done
