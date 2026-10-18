"""Install Bionic Wine and launch Windows programs through the Android host."""
import argparse
import fcntl
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tarfile
import tempfile
import time
import shared

MANIFEST = Path('/usr/lib/arlinux/guest/windows-downloads.tsv')
LATEST_SELECTION = Path('/var/lib/arlinux/windows-runtime-latest.json')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def storage():
    return Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))/'arlinux/windows-bionic'


def instance_prefix():
    """Return the single Wine prefix owned by this Linux instance.

    Steam games and Windows launcher apps deliberately share this prefix.  The
    game install roots remain separate, but all Wine state and ``C:\\Program
    Files`` contents live in this one instance-level tree.
    """
    prefix = storage()/'prefix'
    prefix.mkdir(parents=True, exist_ok=True)
    return prefix


def runtime_storage():
    return shared.directory('windows-bionic')


def validate(root):
    root = root.resolve()
    metadata = json.loads((root/'bionic-runtime.json').read_text())
    if metadata.get('protocol') != 1 or metadata.get('libc') != 'bionic':
        raise ValueError('Only Bionic Wine bundles are supported')
    required = ('files/lib/wine/aarch64-unix/wine', 'files/bin/wineserver',
                'files/lib/wine/aarch64-unix/ntdll.so',
                'files/lib/wine/aarch64-windows/libarm64ecfex.dll',
                'files/lib/wine/aarch64-windows/libwow64fex.dll',
                'files/lib/wine/aarch64-unix/libarm64ecfex.so',
                'files/lib/wine/aarch64-unix/libwow64fex.so',
                'files/share/wine/wine.inf')
    files = metadata.get('files')
    if not isinstance(files, dict) or not all(name in files for name in required):
        raise ValueError('Incomplete Bionic Wine manifest')
    for name, expected in files.items():
        if not isinstance(name, str) or not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
            raise ValueError('Invalid Bionic file checksum')
        path = root/name
        if not path.resolve().is_relative_to(root):
            raise ValueError('Runtime file escapes the bundle')
        if digest(path) != expected:
            raise ValueError(f'Bionic bundle checksum mismatch: {name}')
    for name in (required[0], required[1], required[2], required[5], required[6]):
        with (root/name).open('rb') as stream:
            header = stream.read(20)
        if header[:6] != b'\x7fELF\x02\x01' or header[18:20] != b'\xb7\x00':
            raise ValueError(f'Expected ARM64 ELF: {name}')
    # PT_INTERP distinguishes the supported Android executable from glibc.
    for name in required[:2]:
        binary = (root/name).read_bytes()
        if b'/system/bin/linker64\0' not in binary or b'/lib/ld-linux-aarch64.so.1\0' in binary:
            raise ValueError(f'Expected the Bionic loader: {name}')
    return metadata


def install(archive, expected):
    if not re.fullmatch('[0-9a-f]{64}', expected) or digest(archive) != expected:
        raise ValueError('Archive SHA-256 mismatch')
    home = runtime_storage()
    destination = home/expected
    with (home/'install.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not destination.exists():
            print('Installing Windows runtime…', flush=True)
            with tempfile.TemporaryDirectory(prefix='install-', dir=home) as temporary:
                stage = Path(temporary)/'runtime'
                stage.mkdir()
                with tarfile.open(archive, 'r:*') as bundle:
                    bundle.extractall(stage, filter='data')
                validate(stage)
                stage.rename(destination)
        else:
            validate(destination)
        pointer = home/'current.json'
        temporary = pointer.with_suffix('.tmp')
        temporary.write_text(json.dumps({'sha256': expected})+'\n')
        temporary.replace(pointer)
    print(f'Installed Bionic Wine: {expected[:12]}', flush=True)


def runtime(identity=None):
    home = runtime_storage()
    if identity is None:
        identity = json.loads((home/'current.json').read_text())['sha256']
    if not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{64}', identity):
        raise ValueError('Invalid runtime identity')
    root = home/identity
    metadata = json.loads((root/'bionic-runtime.json').read_text())
    if metadata.get('protocol') != 1 or metadata.get('libc') != 'bionic':
        raise ValueError('Only Bionic Wine is supported')
    return root


def ensure_runtime():
    # A changed release pin installs a new immutable bundle before selecting it.
    rows = [line.split('\t') for line in MANIFEST.read_text().splitlines()
            if line.strip() and not line.startswith('#')]
    if not rows:
        try:
            return runtime()
        except FileNotFoundError:
            raise RuntimeError('Install a Bionic bundle using --install BUNDLE --sha256 SHA256') from None
    if len(rows) != 1 or len(rows[0]) != 3:
        raise ValueError('Invalid Windows runtime download manifest')
    version, expected, url = rows[0]
    if not re.fullmatch('[0-9a-f]{64}', expected) or not url.startswith('https://github.com/taowen/wine/releases/download/'):
        raise ValueError('Invalid Bionic runtime source')
    latest = '/releases/download/latest/' in url
    if latest:
        # Cache successful release lookups briefly, never pin an instance forever.
        # A changed APK manifest also invalidates the selection immediately.
        try:
            selected = json.loads(LATEST_SELECTION.read_text())
            age = time.time() - selected.get('checkedAt', 0)
            if selected.get('manifestSHA256') == digest(MANIFEST) and 0 <= age < 3600:
                return runtime(selected['sha256'])
        except (FileNotFoundError, ValueError, KeyError, TypeError):
            pass
        expected, url = latest_runtime()
    try:
        active = runtime()
        if active.name == expected:
            if latest:
                validate(active)
                remember_latest(expected)
            return active
    except FileNotFoundError:
        pass
    print(f'Preparing shared {version}…', flush=True)
    install(shared.download(url, expected, '.tar.gz'), expected)
    if latest:
        remember_latest(expected)
    return runtime()


def remember_latest(identity):
    LATEST_SELECTION.parent.mkdir(parents=True, exist_ok=True)
    temporary = LATEST_SELECTION.with_suffix('.tmp')
    temporary.write_text(json.dumps({'sha256': identity, 'checkedAt': time.time(),
                                    'manifestSHA256': digest(MANIFEST)})+'\n')
    temporary.replace(LATEST_SELECTION)


def latest_runtime():
    endpoint = 'https://api.github.com/repos/taowen/wine/releases/tags/latest'
    try:
        result = subprocess.run(['curl', '-fsSL', '--connect-timeout', '10', '--max-time', '30',
                                 endpoint], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError:
        return latest_runtime_web()
    release = json.loads(result.stdout)
    for asset in release.get('assets', []):
        if asset.get('name') != 'arlinux-wine-bionic.tar.gz':
            continue
        checksum = asset.get('digest', '')
        identity = asset.get('id')
        if (not isinstance(checksum, str) or not re.fullmatch('sha256:[0-9a-f]{64}', checksum)
                or type(identity) is not int or identity <= 0 or asset.get('state') != 'uploaded'):
            raise ValueError('Invalid latest Bionic Wine release asset')
        # The immutable asset ID also avoids resolving a different upload halfway through.
        return checksum[7:], f'https://api.github.com/repos/taowen/wine/releases/assets/{identity}'
    raise ValueError('Latest Bionic Wine release has no runtime asset')


def latest_runtime_web():
    """Resolve GitHub's published digest when the public API is rate limited.

    Never accept the APK's old pin or infer a digest from a downloaded archive.
    A replacement between this lookup and download fails SHA-256 verification.
    """
    class Assets(HTMLParser):
        def __init__(self):
            super().__init__()
            self.digests = []
            self.runtime_link = False

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'a' and attrs.get('href') == '/taowen/wine/releases/download/latest/arlinux-wine-bionic.tar.gz':
                self.runtime_link = True
            if tag == 'clipboard-copy' and attrs.get('aria-label') == 'Copy to clipboard digest for arlinux-wine-bionic.tar.gz':
                self.digests.append(attrs.get('value', ''))

    result = subprocess.run(['curl', '-fsSL', '--connect-timeout', '10', '--max-time', '30',
        'https://github.com/taowen/wine/releases/expanded_assets/latest'],
        check=True, capture_output=True, text=True)
    assets = Assets()
    assets.feed(result.stdout)
    if (not assets.runtime_link or len(assets.digests) != 1 or
            not re.fullmatch('sha256:[0-9a-f]{64}', assets.digests[0])):
        raise ValueError('Latest Bionic Wine release has no verified runtime digest')
    return assets.digests[0][7:], 'https://github.com/taowen/wine/releases/download/latest/arlinux-wine-bionic.tar.gz'


def host_path(path):
    """Map guest files to Android backing files (including per-instance HOME)."""
    path = Path(path).resolve()
    files = Path(os.environ['BIONICX_FILES']).resolve()
    if path.is_relative_to('/arlinux-shared'):
        return files/'shared'/path.relative_to('/arlinux-shared')
    if path.is_relative_to(files):
        return path
    return Path(os.environ['BIONICX_ROOTFS'])/str(path).lstrip('/')


def guest_path(path):
    files = Path(os.environ['BIONICX_FILES']).resolve()
    path = Path(path)
    if path.is_relative_to(files/'shared'):
        return Path('/arlinux-shared')/path.relative_to(files/'shared')
    root = Path(os.environ['BIONICX_ROOTFS'])
    if path.is_relative_to(root):
        return Path('/')/path.relative_to(root)
    return path


def environment(root, prefix):
    # These are guest adapter settings, never a command for executing native Wine.
    env = os.environ.copy()
    env.update(ARLINUX_WINDOWS_RUNTIME=root.name, ARLINUX_WINDOWS_PREFIX=str(prefix),
               WINEPREFIX=str(prefix/'pfx'))
    return env


def request(root, prefix, executable, arguments=(), overrides='', stdio=False, diagnostics=None, timeout=300):
    exe = str(executable)
    if exe.startswith('/'):
        exe = str(host_path(exe))
    argv = [str(host_path(value)) if str(value).startswith('/') and
        not re.fullmatch('/[A-Za-z][A-Za-z0-9:_-]*', str(value)) else str(value)
        for value in arguments]
    payload = dict(runtime=root.name, prefix=str(host_path(prefix/'pfx')), exe=exe,
                   args=argv, dllOverrides=overrides, stdio=stdio)
    if diagnostics:
        payload['environment'] = diagnostics
    return _host_request(payload, timeout, stdio)


def _host_request(payload, timeout=10, stdio=False):
    files = Path(os.environ['BIONICX_FILES']).resolve()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect('\0arlinux-windows-' + str(files.stat().st_uid))
        client.sendall(json.dumps(payload).encode()+b'\n')
        line = bytearray()
        while len(line) <= 32768:
            byte = client.recv(1)
            if not byte:
                raise RuntimeError('Android Windows host disconnected')
            if byte == b'\n':
                break
            line.extend(byte)
        else:
            raise RuntimeError('Windows host response too large')
        response = json.loads(line)
        if 'error' in response:
            raise RuntimeError(response['error'])
        if stdio:
            client.settimeout(None)
            return response, client
        client.close()
        return response
    except BaseException:
        client.close()
        raise


def initialize(root, prefix, env=None):
    # Android owns builtin wineboot and matching DXVK setup.
    run(root, prefix, 'cmd.exe', ['/c', 'exit', '0'], env=env, check=True)


def cancel_job(job):
    """Stop one recorded launcher, not its shared wineserver or detached children."""
    if not isinstance(job, str) or not re.fullmatch(r'[0-9a-f-]{36}', job):
        raise ValueError('Invalid Windows job identity')
    result = _host_request({'operation': 'cancel-job', 'job': job})
    if result.get('ok') is not True or result.get('scope') != 'launcher':
        raise RuntimeError('Windows host did not acknowledge launcher cancellation')


class WindowsWaitTimeout(TimeoutError):
    """Waiting expired; ownership is explicit and the task has not been cancelled."""
    def __init__(self, response):
        self.job = response['job']
        self.log = guest_path(response['log'])
        super().__init__(f'Windows wait timed out; job {self.job} may still be running; log: {self.log}')

    def cancel_launcher(self):
        cancel_job(self.job)


def run(root, prefix, executable, arguments=(), env=None, check=False, capture=False, timeout=600):
    env = env or {}
    diagnostics = {name: env[name] for name in ('WINEDEBUG', 'ARLINUX_EXCEPTION_LOG',
        'SteamAppId', 'SteamGameId', 'SteamOverlayGameId',
        'WEBVIEW2_BROWSER_EXECUTABLE_FOLDER', 'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS') if name in env}
    response = request(root, prefix, executable, arguments, env.get('WINEDLLOVERRIDES', ''), diagnostics=diagnostics)
    deadline = time.monotonic()+timeout if timeout is not None else None
    exit_path = guest_path(response['exit'])
    while not exit_path.is_file():
        if deadline is not None and time.monotonic() >= deadline:
            raise WindowsWaitTimeout(response)
        time.sleep(.2)
    output = guest_path(response['log']).read_text(errors='replace')
    code = int(exit_path.read_text())
    if not capture and output:
        print(output, end='', flush=True)
    result = subprocess.CompletedProcess([str(executable), *arguments], code, output, '')
    if check:
        result.check_returncode()
    return result


def launch(executable, arguments=(), prefix=None):
    executable = executable.resolve(strict=True)
    root = ensure_runtime()
    if prefix is not None and prefix.resolve() != instance_prefix().resolve():
        raise ValueError('Bionic Wine uses one instance prefix')
    prefix = instance_prefix()
    env = environment(root, prefix)
    import windows_a11y
    initialize(root, prefix, env)
    windows_a11y.ensure(root, prefix, executable.stem, env)
    if executable.suffix.lower() == '.lnk':
        return run(root, prefix, 'start.exe', [str(executable), *arguments], env=env, timeout=None).returncode
    return run(root, prefix, executable, arguments, env=env, timeout=None).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', type=Path, metavar='BUNDLE')
    parser.add_argument('--sha256')
    parser.add_argument('--prefix', type=Path, help='Wine data directory (contains pfx)')
    parser.add_argument('executable', nargs='?', type=Path)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.install:
        if not args.sha256:
            parser.error('--install requires --sha256')
        install(args.install, args.sha256)
    elif args.sha256:
        parser.error('--sha256 requires --install')
    if args.executable:
        return launch(args.executable, args.arguments, args.prefix)
    if not args.install:
        parser.error('Provide an executable or --install BUNDLE --sha256 SHA256')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RuntimeError, tarfile.TarError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'arlinux-windows: {error}')
