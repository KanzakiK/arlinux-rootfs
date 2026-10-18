"""Explicit compatibility policy; launch mechanisms must not identify titles.

Keep title workarounds here with their failure boundary. Renderer overrides
never replace an explicit user selection. WebView settings apply only to the
matched host; Wine's browser version applies to the shared fixed runtime.
"""
from dataclasses import dataclass
from pathlib import PureWindowsPath


@dataclass(frozen=True)
class GameProfile:
    executable: str
    renderer: str = ''
    webview_flags: str = ''


# Native Unity/Mono reload fails under FEX; preserve explicit game choices.
WINDOWS_DEFAULTS = ('1289310',)  # Helltaker
# Legacy Unity D3D9 pipelines fail on Mali; the shipped D3D11 renderer works.
GAME_PROFILES = {
    '312990': GameProfile('Expendabros.exe', renderer='-force-d3d11'),
    # This title embeds WebView2. Keep ANGLE Vulkan while avoiding unsupported
    # direct composition; Android remains the sandbox boundary for Wine apps.
    '2758540': GameProfile('我的小鲨鱼.exe', webview_flags=(
        '--no-sandbox --use-angle=vulkan --disable-gpu-compositing '
        '--disable-direct-composition --disable-features=SkiaGraphite,kRemoveRedirectionBitmap')),
}
# The one fixed ARM64 WebView runtime requires this Wine version identity.
WEBVIEW_WINE_VERSION = 'win8'
POWERBI_WEBVIEW_FLAGS = '--no-sandbox --use-angle=d3d11'


def game_profile(appid, executable):
    profile = GAME_PROFILES.get(appid)
    if profile and PureWindowsPath(str(executable)).name.casefold() == profile.executable.casefold():
        return profile
    return None


def renderer_arguments(appid, arguments):
    profile = game_profile(appid, arguments[0])
    if profile and profile.renderer and not any(arg.lower().startswith('-force-') for arg in arguments[1:]):
        return [*arguments, profile.renderer]
    return arguments
