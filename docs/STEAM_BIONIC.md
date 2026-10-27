# Steam Bionic compatibility adapter

`python3 /usr/lib/arlinux/steam_bionic.py register STEAM_DIRECTORY` registers
`arlinux-wine-bionic` under `compatibilitytools.d`. Steam startup also registers
it directly, without a Proton depot or patch pack. Before the client starts,
installed non-runtime AppIDs without an explicit compatibility choice are
mapped to Bionic Wine. This mirrors DroidDeck Mali's per-game Windows launch
selection for titles which also ship a native Linux build; Steam still owns
the final launch. Explicit third-party and native Linux choices are preserved.
Previous ARLinux Proton selections migrate to Bionic. Restart Steam to rescan
tools.

Steam invokes `/run %verb%`; the guest adapter accepts `run` and
`waitforexitandrun`, uses the single instance-level Wine prefix
`~/.local/share/arlinux/windows-bionic/prefix` (containing `pfx`), preserves executable
arguments, and returns the native job exit status. `getcompatpath` and
`getnativepath` translate the Android host Z: drive. The runtime is automatically
prepared using the current `windows-downloads.tsv` pin and shared verified
immutable download cache. Android's WindowsRuntimeHost launches Wine outside
any guest seccomp filter and selects matching native DXVK/graphics libraries.
Only the explicitly listed game identities and WebView environment variables
cross the host boundary; guest glibc loader and graphics paths do not.

`STEAM_COMPAT_DATA_PATH` remains Steam's per-game metadata directory, not the
Wine prefix. Steam prepares the pinned Bionic runtime before handing control to
Valve. On Play, `windows_webview.prepare()` prepares the instance-wide browser
dependencies and `steamworks.session()` supplies the Steamworks bridge. Discovery
helpers without a game identity run without a Steamworks session. These paths
share the Windows launcher's Wine prefix. The adapter does not inject engine
arguments. User selections and launch arguments are retained.
`runtime/tools/windows_webview.py` owns one instance-wide WebView2 policy,
shared with Windows Launcher and built-in Windows apps. The fixed runtime and
browser arguments are identical for all hosts. Android's prefix initialization
owns the Windows 10 version identity, 144-DPI initial setting and ClearType;
neither app installers nor WebView2 preparation change the Windows version.
Both registry views use the documented `*` policy for all WebView2 apps; see
[Microsoft's loader override contract](https://learn.microsoft.com/en-us/microsoft-edge/webview2/reference/win32/webview2-idl#createcorewebview2environmentwithoptions).
These settings do not prove GPU rendering or provide a Chromium sandbox under Wine.
The first application launch prepares this common dependency even for an app
that does not use WebView2; later launches reuse the verified installed copy.
The patched Steam Proton adapter and its core build/install chain were removed.
Implementation does not establish compatibility for every game: acceptance
requires a fresh instance, hardware acceleration and actual Play/gameplay.

Run `python3 tests/test-steam-bionic.py` to verify registration, preservation of
unrecognized tools, argument boundaries, exit propagation and identity checks.
For device validation, delete and reinstall the selected test Linux instance,
use a fresh prefix, and record exact APK, bundle and runtime hashes. Reusing a
verified immutable runtime outside the instance is permitted; prefix or home
restoration is not. Authentication-only test preparation remains explicit and
private, outside application startup.

## Historical investigation (2026-10-14)

The following observations apply only to that runtime, not the current build's
acceptance status or deployment procedure.

Runtime `cd7be9eddc996bb4353c7b6cd3642dae3aab86ff300e56d51bf4c7c517cc390f`
(Wine 11.19 Bionic r3) started My Little Shark and WebView2 on a fresh instance.
DXVK identified the phone's Adreno 830 Qualcomm Vulkan driver. The game then
hit an access violation in ole32 `RevokeDragDrop` at RVA 0x84258, dereferencing
the registered drop target during cleanup; target exit was 0xc0000005.
An independent minimal controller probe returned successful MoveFocus and
navigation. Under ANGLE Vulkan its GPU child repeatedly exited, with only six
animation frames by tick 13. These results do not demonstrate rendered gameplay
or establish whether cleanup masked an earlier initialization error.

A further fresh-instance D3D11 probe also reproduced GPU child exits
(0x80000003), logged DCompositionCreateDevice E_NOTIMPL and a fatal shared
context creation failure. In that run MoveFocus returned E_ACCESSDENIED;
earlier successful focus probes do not establish that focus is fixed.
The first GPU exception and real Steam Play still require validation.
