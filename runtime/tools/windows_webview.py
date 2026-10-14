"""Prepare the pinned WebView2 dependency for supported Steam games.

Only immutable vendor files are shared; registry settings remain in each game's
fresh Wine prefix. The GPU remains enabled through ANGLE Vulkan.
"""
import json
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import tempfile

import shared
import windows

MANIFEST = Path('/usr/lib/arlinux/guest/windows-app-downloads.tsv')
DOWNLOAD = 'webview2-fixed-arm64'
FLAGS = ('--no-sandbox --use-angle=vulkan --disable-gpu-compositing '
         '--disable-direct-composition --disable-features=SkiaGraphite,kRemoveRedirectionBitmap')


def verified_browser(destination, expected):
    record = json.loads((destination/'arlinux-runtime.json').read_text())
    if record.get('protocol') != 1 or record.get('sha256') != expected or not record.get('files'):
        raise RuntimeError('Invalid shared WebView2 runtime record')
    for name, checksum in record['files'].items():
        path = destination/name
        if path.is_symlink() or not path.resolve().is_relative_to(destination.resolve()) or shared.digest(path) != checksum:
            raise RuntimeError('Shared WebView2 runtime integrity check failed')
    browser = destination/record['browser']
    if not browser.resolve().is_relative_to(destination.resolve()) or not (browser/'msedgewebview2.exe').is_file():
        raise RuntimeError('Shared WebView2 executable is missing')
    return browser


def ensure_runtime():
    rows = [line.split('\t') for line in MANIFEST.read_text().splitlines()
            if line.startswith(DOWNLOAD+'\t')]
    if len(rows) != 1 or len(rows[0]) != 3:
        raise ValueError('Missing pinned WebView2 fixed-runtime download')
    _, expected, url = rows[0]
    if not re.fullmatch('[0-9a-f]{64}', expected) or not url.startswith('https://msedge.sf.dl.delivery.mp.microsoft.com/') or not url.endswith('.cab'):
        raise ValueError('Invalid WebView2 fixed-runtime source')
    store = shared.directory('windows-webview2')
    destination = store/expected
    with shared.locked(store/(expected+'.lock')):
        if destination.is_symlink():
            raise RuntimeError('Shared WebView2 runtime must not be redirected')
        if destination.exists():
            return verified_browser(destination, expected)
        archive = shared.download(url, expected, '.cab')
        print('Preparing Microsoft WebView2…', flush=True)
        if not shutil.which('cabextract'):
            subprocess.run(['sudo', 'apt-get', 'update'], check=True, timeout=300)
            subprocess.run(['sudo', 'apt-get', 'install', '-y', 'cabextract'], check=True, timeout=300)
        with tempfile.TemporaryDirectory(prefix='.webview-', dir=store) as temporary:
            stage = Path(temporary)/'runtime'
            stage.mkdir()
            subprocess.run(['cabextract', '-q', '-d', str(stage), str(archive)],
                           check=True, stdout=subprocess.DEVNULL)
            browsers = list(stage.glob('*/msedgewebview2.exe'))
            if len(browsers) != 1:
                raise RuntimeError('Unexpected Microsoft WebView2 archive layout')
            files = {}
            for path in stage.rglob('*'):
                if path.is_symlink():
                    raise RuntimeError('Unexpected link in Microsoft WebView2 runtime')
                if path.is_file():
                    files[path.relative_to(stage).as_posix()] = shared.digest(path)
            record = dict(protocol=1, sha256=expected,
                          browser=browsers[0].parent.relative_to(stage).as_posix(), files=files)
            (stage/'arlinux-runtime.json').write_text(json.dumps(record)+'\n')
            stage.rename(destination)
        return verified_browser(destination, expected)


def prepare_game(root, prefix, executable, environment):
    """Apply only the tested title profile; ordinary games do not download Edge."""
    env = dict(environment)
    name = PureWindowsPath(str(executable)).name
    if env.get('SteamAppId') != '2758540' or name.lower() != '我的小鲨鱼.exe':
        return env
    browser = ensure_runtime()
    # Elevated WebView hosts ignore environment browser switches. Use the
    # documented per-host machine policy, confined to this game's Wine prefix.
    windows.run(root, prefix, 'reg.exe', ['add',
        r'HKLM\Software\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments',
        '/v', name, '/t', 'REG_SZ', '/d', FLAGS, '/f'], check=True, timeout=120)
    windows.run(root, prefix, 'reg.exe', ['add',
        r'HKCU\Software\Wine\AppDefaults\msedgewebview2.exe',
        '/v', 'Version', '/t', 'REG_SZ', '/d', 'win8', '/f'], check=True, timeout=60)
    env['WEBVIEW2_BROWSER_EXECUTABLE_FOLDER'] = 'Z:'+str(windows.host_path(browser)).replace('/', '\\')
    env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = FLAGS
    return env
