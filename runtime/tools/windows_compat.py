"""One instance-wide Wine/WebView2 policy, shared by all Windows launchers.

No Steam IDs, application names or engine-specific command-line injection.
Android is the sandbox boundary; ANGLE Vulkan remains the rendering backend.
"""

WEBVIEW_WINE_VERSION = 'win8'
WEBVIEW_FLAGS = (
    '--no-sandbox --use-angle=vulkan --disable-gpu-compositing '
    '--disable-direct-composition --disable-features=SkiaGraphite,kRemoveRedirectionBitmap'
)
