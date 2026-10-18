#!/usr/bin/env bash
# Build a standalone Steamworks bridge for ARLinux Bionic Wine. No installed
# Steam compatibility tool or Proton distribution is read or modified.
set -euo pipefail
if [[ $# != 5 ]]; then
    echo 'Usage: steamworks-bridge.sh WINE_SOURCE WINE_BUILD WINE_TOOLS LLVM_MINGW_BIN OUTPUT' >&2
    exit 2
fi
repo=$(cd -- "${BASH_SOURCE[0]%/*}/../.." && pwd -P)
wine=$(realpath "$1")
wine_build=$(realpath "$2")
wine_tools=$(realpath "$3")
export PATH="$(realpath "$4"):$PATH"
output=$(realpath -m "$5")
ndk=${ANDROID_NDK_HOME:-/opt/android-sdk/ndk/29.0.14206865}
cxx=$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android29-clang++
up=$repo/build/steam-bridge-upstream
revision=9782c5154cf6217661b05bed30b160556f8c7885
if [[ ! -d $up/.git ]]; then
    git clone https://github.com/moio9/steam-arm64-termux.git "$up"
fi
git -C "$up" fetch origin "$revision"
git -C "$up" checkout --detach "$revision"
[[ $(git -C "$up" rev-parse HEAD) == "$revision" ]]
# The upstream recipe extracts only the independently built lsteamclient
# component and ports it to Bionic. It never builds or installs Proton.
src=$up/public-source/lsteamclient/work/proton/lsteamclient
if [[ ! -f $src/bridge_proxy.inc ]]; then
    bash "$up/public-source/lsteamclient/prepare-proton-source.sh"
fi
git -C "${src%/lsteamclient}" sparse-checkout set --no-cone \
    '/lsteamclient/*' '!/lsteamclient/steamworks_sdk_*/' '/lsteamclient/steamworks_sdk_154/*'
# Modern SteamUser023 inserts the Web API authentication method. Keep legacy
# layouts and forward genuine ticket/callback traffic to native Steam.
if ! grep -q 'LSTEAM_BRIDGE_WEB_API_TICKET' "$up/steam-bridge/protocol.h"; then
    patch -d "$up" -p1 < "$repo/native/steamworks/user023-web-ticket.patch"
fi
# The standalone frontend has no separate Valve DLL data section to borrow.
if ! grep -q 'static DECLSPEC_ALIGN(16) BYTE bridge_arena' "$src/steamclient_main.c"; then
    patch -d "$src" -p1 < "$repo/native/steamworks/frontend-arena.patch"
fi
mkdir -p "$output/aarch64-unix" "$output/aarch64-windows" "$output/objects"
aarch64-linux-gnu-g++ -O2 -std=gnu++17 -I"$up/steam-bridge" \
    -I"$src/steamworks_sdk_154" "$up/steam-bridge/server.cpp" -ldl \
    -o "$output/lsteambridge-server"
export AR_STEAM_SRC=$src AR_STEAM_OUTPUT=$output AR_STEAM_WINE=$wine AR_STEAM_UP=$up AR_STEAM_CXX=$cxx
find "$src" -maxdepth 1 \( -name 'cppISteam*.cpp' -o -name 'unix*.cpp' \) -print0 |
    xargs -0 -n 1 -P "${JOBS:-6}" bash -c '
    "$AR_STEAM_CXX" -c -fPIC -O2 -std=gnu++17 -pthread \
      -Wno-pragma-pack -Wno-format-extra-args -D__WINESRC__ -DNOMINMAX -DWINE_UNIX_LIB \
      -DSTEAM_API_EXPORTS -Dprivate=public -Dprotected=public -DLSTEAM_BRIDGE_PROXY \
      -I"$AR_STEAM_WINE/include" -I"${BIONIC_INCLUDE:-/mnt/c/games/arlinux/build/ndk-prefix/include}" \
      -I"$AR_STEAM_UP/steam-bridge" -I"$AR_STEAM_SRC" \
      "$0" -o "$AR_STEAM_OUTPUT/objects/$(basename "$0").o"'
"$cxx" -shared -pthread -static-libstdc++ -Wl,-soname,lsteamclient.so -Wl,--no-undefined \
    "$output"/objects/*.o "$wine_build/dlls/ntdll/ntdll.so" -ldl \
    -o "$output/aarch64-unix/lsteamclient.so"
# Wine resolves the Unix counterpart using the basename loaded by Steam API.
cp "$output/aarch64-unix/lsteamclient.so" "$output/aarch64-unix/steamclient.so"
cp "$output/aarch64-unix/lsteamclient.so" "$output/aarch64-unix/steamclient64.so"
# ARM64 Wine redirects x64 builtins to aarch64-windows. Without the
# ARM64EC frontend the copied x64 facade has no Unix library handle.
for arch in i686 x86_64 arm64ec; do
    folder=${arch/i686/i386}-windows
    imports=$folder
    if [[ $arch == arm64ec ]]; then
        folder=aarch64-windows
        imports=aarch64-windows
    fi
    mkdir -p "$output/$folder"
    "$wine_tools/tools/winegcc/winegcc" --target=$arch-windows \
      --winebuild="$wine_tools/tools/winebuild/winebuild" \
      -O2 -Wno-pragma-pack -shared -Wl,--wine-builtin -D__WINESRC__ -D__WINE_PE_BUILD \
      -DSTEAM_API_EXPORTS -Dprivate=public -Dprotected=public -DLSTEAM_BRIDGE_PROXY \
      -I"$wine/include" -I"$wine/include/msvcrt" -I"$wine_build/include" -I"$src" \
      -L"${WINE_IMPORT_LIBS:?Set WINE_IMPORT_LIBS to the matching PE lib/wine directory}/$imports" \
      -o "$output/$folder/lsteamclient.dll" "$src"/*.c "$src/lsteamclient.spec" -luser32 -lws2_32
done
aarch64-w64-mingw32-clang -O2 -municode "$repo/native/steamworks/steam-launch.c" \
    -ladvapi32 -o "$output/aarch64-windows/steam.exe"
cp "$up/steam-bridge/LICENSE" "$output/LICENSE.bridge"
cp "$src/LICENSE" "$output/LICENSE.lsteamclient"
printf '%s\n' "$revision" > "$output/upstream-revision"
tar --exclude=.git -czf "$output/steamworks-source.tar.gz" -C "$up" \
    steam-bridge public-source/lsteamclient/work/proton/lsteamclient
