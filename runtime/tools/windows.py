"""Install Bionic Wine and launch Windows programs through the Android host."""
import argparse
import fcntl
import hashlib
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


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def storage():
    return Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))/'arlinux/windows-bionic'


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
    try:
        active = runtime()
        if active.name == expected:
            return active
    except FileNotFoundError:
        pass
    print(f'Preparing shared {version}…', flush=True)
    install(shared.download(url, expected, '.tar.gz'), expected)
    return runtime()


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


def request(root, prefix, executable, arguments=(), overrides='', stdio=False, diagnostics=None):
    files = Path(os.environ['BIONICX_FILES']).resolve()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(300)
    try:
        client.connect('\0arlinux-windows-' + str(files.stat().st_uid))
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


def run(root, prefix, executable, arguments=(), env=None, check=False, capture=False, timeout=600):
    env = env or {}
    diagnostics = {name: env[name] for name in ('WINEDEBUG', 'ARLINUX_EXCEPTION_LOG') if name in env}
    response = request(root, prefix, executable, arguments, env.get('WINEDLLOVERRIDES', ''), diagnostics=diagnostics)
    deadline = time.monotonic()+timeout
    exit_path = guest_path(response['exit'])
    while not exit_path.is_file():
        if time.monotonic() >= deadline:
            raise RuntimeError('Windows process timed out; log: '+str(guest_path(response['log'])))
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
    identity = hashlib.sha256(os.fsencode(executable)).hexdigest()[:24]
    prefix = prefix.resolve() if prefix else storage()/'prefixes'/identity
    env = environment(root, prefix)
    import windows_a11y
    initialize(root, prefix, env)
    windows_a11y.ensure(root, prefix, executable.stem, env)
    return run(root, prefix, executable, arguments, env=env).returncode


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
