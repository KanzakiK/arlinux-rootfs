# Bionic Wine Steamworks bridge

The game stays in ARLinux Bionic Wine; the authenticated native ARM64 Steam
client supplies Steamworks services over a private same-UID Unix socket. This
builds the standalone lsteamclient frontend and moio9 RPC bridge, not a Proton
distribution. It does not replace or patch Steam's installed Proton tools.
The upstream revision and both licenses ship with the payload.

Build on Linux with matching Wine headers, Android Unix build, Wine host tools,
LLVM MinGW, Android NDK and ARM64 glibc cross compiler:

```sh
WINE_IMPORT_LIBS="$PWD/build/wine-bionic/runtime-1/files/lib/wine" \
  tools/build/steamworks-bridge.sh \
  build/wine-bionic/source build/wine-bionic/full \
  build/windows-test/wine-11.19-arlinux/tools \
  build/windows-test/llvm-mingw-20260826-ucrt-ubuntu-22.04-x86_64/bin \
  build/steamworks-payload
```

`ANDROID_NDK_HOME` and `BIONIC_INCLUDE` override the NDK and Bionic X11 header
locations. The normal `tools/build/linux-assets.sh` build embeds this payload
(or `ARLINUX_STEAMWORKS_PAYLOAD`) and includes all its hashes in the cache key.
An offline bundle can also be refreshed using the Android repository's
`tools/build/steamworks-bundle.py`.

`frontend-arena.patch` is local to this independently built bridge frontend.
Its interface pointers must remain inside the loaded module. When the frontend
itself is named steamclient.dll, borrowing the ordinary .data section overwrites
its live critical section and interface cache. A separate aligned in-image arena
preserves both module membership and control data. No game binary is changed.

Compile `client-check.c` with i686/x86_64 LLVM MinGW and `-luser32`, then run it
through the registered ARLinux compatibility tool with an owned SteamAppId and
active native Steam session. The optional argument points to an installed game's
original steam_api[64].dll. It tests window creation, 32 repeated interface calls,
and the game's SteamAPI_Init. It never prints account identifiers or tokens.
Running any Steamworks probe changes Steam's running-app list; close it and
restart Steam normally before first-Play acceptance. The probe does not substitute
for a fresh-instance game and GPU test.

The payload builds i386, x86_64 and ARM64EC frontends. The ARM64EC DLL must
be installed at `aarch64-windows/lsteamclient.dll` beside the ARM64 launcher.
Bionic Wine redirects 64-bit builtin module loading there; an x86_64 facade
alone does not initialize the ARM64 Unix bridge handle. Missing this module
can abort 64-bit SteamAPI initialization (observed with Helltaker). Both
runtime validation and offline bundling require it. The 32-bit and x86_64
facades remain available for their respective game imports.

`user023-web-ticket.patch` preserves the legacy SteamUser interface and adds
SteamUser023's inserted GetAuthTicketForWebApi slot. Authentication requests go
to native SteamUser023 and callback 168 travels over the existing callback RPC;
no ticket or success result is fabricated. This fixes Electron steamworks.js
0.3.2 games timing out during login after SteamAPI_Init succeeds. Diagnostic
validation on X300 reached Revenge on Gold Diggers' complete main menu; final
fresh-instance Steam Play/gameplay acceptance is still required.
