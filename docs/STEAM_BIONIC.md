# Steam Bionic compatibility adapter

`python3 /usr/lib/arlinux/steam_bionic.py register STEAM_DIRECTORY` registers
`arlinux-wine-bionic` under `compatibilitytools.d`. Steam startup also registers
it directly, without a Proton depot or patch pack. Bionic Wine is the ARLinux
Windows default; explicit third-party and native Linux choices are preserved.
Previous ARLinux Proton selections migrate to Bionic. Restart Steam to rescan tools.

Steam invokes `/run %verb%`; the guest adapter accepts `run` and
`waitforexitandrun`, uses `STEAM_COMPAT_DATA_PATH/pfx`, preserves executable
arguments, and returns the native job exit status. `getcompatpath` and
`getnativepath` translate the Android host Z: drive. The runtime is automatically
prepared using the current `windows-downloads.tsv` pin and shared verified
immutable download cache. Android's WindowsRuntimeHost launches Wine outside
any guest seccomp filter and selects matching native DXVK/graphics libraries.
Only the explicitly listed game identities and WebView environment variables
cross the host boundary; guest glibc loader and graphics paths do not.

This is experimental. Steamworks integration and real Steam Play acceptance
remain unverified. There is no automatic WebView2 dependency installation in
this adapter yet. No game-specific graphics policy is installed automatically.
The patched Steam Proton adapter and its core build/install chain were removed.

Run `python3 tests/test-steam-bionic.py` to verify registration, preservation of
unrecognized tools, argument boundaries, exit propagation and identity checks.
For device validation, delete and reinstall the selected test Linux instance,
use a fresh prefix, and record exact APK, bundle and runtime hashes. Reusing a
verified immutable runtime outside the instance is permitted; prefix or home
restoration is not. Authentication-only test preparation remains explicit and
private, outside application startup.

2026-10-14 evidence: runtime `cd7be9eddc996bb4353c7b6cd3642dae3aab86ff300e56d51bf4c7c517cc390f`
(Wine 11.19 Bionic r3) started My Little Shark and WebView2 on a fresh instance.
DXVK identified the phone's Adreno 830 Qualcomm Vulkan driver. The game then
hit an access violation in ole32 `RevokeDragDrop` at RVA 0x84258, dereferencing
the registered drop target during cleanup; target exit was 0xc0000005.
An independent minimal controller probe returned successful MoveFocus and
navigation. Under ANGLE Vulkan its GPU child repeatedly exited, with only six
animation frames by tick 13. These results do not demonstrate rendered gameplay
or establish whether cleanup masked an earlier initialization error.

DroidDeck also maintains compatibility patches: its Components project builds
version-matched ntdll/wineserver packs with hash matching and signed indexes;
DroidDeck-Proton provides a complete GE-Proton-based runtime with its Wine fixes.
Relevant primary sources:
- https://github.com/Droid-Deck/DroidDeck-Components/tree/main/droiddeck-esync
- https://github.com/Droid-Deck/DroidDeck/blob/4ac78621cc550c3d262f23a2c7e545cf98a77d13/tools/linuxfs/overlay/usr/local/bin/droiddeck-esync
- https://github.com/The412Banner/DroidDeck-Proton

A further fresh-instance D3D11 probe also reproduced GPU child exits
(0x80000003), logged DCompositionCreateDevice E_NOTIMPL and a fatal shared
context creation failure. In that run MoveFocus returned E_ACCESSDENIED;
earlier successful focus probes do not establish that focus is fixed.
The first GPU exception and real Steam Play still require validation.
