"""Install the ARLinux Wine runtime and run a Windows executable.

Wine owns Windows initialization; FEX provides its x86/x64 CPU modules.
Steam's Proton installation and game prefixes are untouched.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile
import shared


MANIFEST = Path('/usr/lib/arlinux/guest/windows-downloads.tsv')


def ensure_runtime():
    """Download the pinned standalone Wine release when no runtime is installed."""
    if (runtime_storage()/'current.json').is_file():
        return runtime()
    entries = [line for line in MANIFEST.read_text().splitlines() if line.strip() and not line.startswith('#')]
    if not entries:
        raise RuntimeError('The standalone Wine bundle has not been published yet. Install a built bundle using --install BUNDLE --sha256 SHA256')
    fields = '\n'.join(entries).split('\t')
    if len(fields) != 3:
        raise ValueError('Invalid Windows runtime download manifest')
    version, expected, url = fields
    if (len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected)
            or not url.startswith('https://github.com/taowen/wine/releases/download/')):
        raise ValueError('Invalid Windows runtime download source or checksum')
    print(f'Preparing shared {version}. The first installation needs internet access.', flush=True)
    archive = shared.download(url, expected, '.tar.gz')
    install(archive, expected)
    return runtime()


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def validate(root):
    manifest = json.loads((root/'arlinux-runtime.json').read_text())
    if (manifest.get('format') != 2 or manifest.get('kind') != 'wine'
            or manifest.get('architecture') != 'aarch64'):
        raise ValueError('Install a standalone Wine bundle; Proton bundles are not supported')
    required = ('files/bin/wine', 'files/bin/wineserver',
                'files/lib/wine/aarch64-unix/ntdll.so',
                'files/lib/wine/aarch64-windows/libarm64ecfex.dll',
                'files/lib/wine/aarch64-windows/libwow64fex.dll',
                'files/lib/wine/aarch64-unix/libarm64ecfex.so',
                'files/lib/wine/aarch64-unix/libwow64fex.so',
                'files/share/wine/wine.inf')
    files = manifest.get('files', {})
    if not isinstance(files, dict) or not all(name in files for name in required):
        raise ValueError('Incomplete Wine bundle manifest')
    for name, expected in files.items():
        if (not isinstance(name, str) or not isinstance(expected, str) or len(expected) != 64
                or any(c not in '0123456789abcdef' for c in expected)):
            raise ValueError('Invalid Wine file checksum')
        path = root/name
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Runtime file escapes the bundle')
        if digest(path) != expected:
            raise ValueError(f'Wine bundle checksum mismatch: {name}')
    for name in (*required[:3], *required[5:7]):
        with (root/name).open('rb') as source:
            header = source.read(20)
        if header[:6] != b'\x7fELF\x02\x01' or header[18:20] != b'\xb7\x00':
            raise ValueError(f'Not a native ARM64 ELF: {name}')
    return manifest


def storage():
    return Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))/'arlinux/windows'


def runtime_storage():
    return shared.directory('windows')


def install(archive, expected):
    """Install atomically; never overwrite binaries used by a running process."""
    actual = digest(archive)
    if actual != expected.lower():
        raise ValueError('Archive SHA-256 mismatch')
    home = runtime_storage()
    runtimes = home/'runtimes'
    runtimes.mkdir(parents=True, exist_ok=True)
    destination = runtimes/actual
    with (home/'install.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not destination.exists():
            print('Installing Windows runtime. The first installation may take a few minutes.', flush=True)
            with tempfile.TemporaryDirectory(prefix='install-', dir=runtimes) as temporary:
                stage = Path(temporary)/'runtime'
                stage.mkdir()
                with tarfile.open(archive, 'r:*') as bundle:
                    bundle.extractall(stage, filter='data')
                manifest = validate(stage)
                if manifest.get('development'):
                    print('This is an experimental Windows runtime.', flush=True)
                stage.rename(destination)
        else:
            validate(destination)
        pointer = home/'current.json'
        temporary = pointer.with_suffix('.tmp')
        temporary.write_text(json.dumps({'sha256': actual})+'\n')
        temporary.replace(pointer)
    print(f'Installed Windows runtime: {actual[:12]}', flush=True)


def runtime():
    home = runtime_storage()
    pointer = home/'current.json'
    if not pointer.is_file():
        raise RuntimeError('Install a runtime first: arlinux-windows --install BUNDLE --sha256 SHA256')
    identity = json.loads(pointer.read_text()).get('sha256', '')
    if not isinstance(identity, str) or len(identity) != 64 or any(c not in '0123456789abcdef' for c in identity):
        raise ValueError('Invalid runtime identity')
    root = home/'runtimes'/identity
    # The immutable install is checked once during installation. Do not hash
    # gigabytes of runtime files on every application startup.
    if not (root/'arlinux-runtime.json').is_file():
        raise RuntimeError('Installed Windows runtime is missing')
    metadata = json.loads((root/'arlinux-runtime.json').read_text())
    if metadata.get('format') != 2 or metadata.get('kind') != 'wine':
        raise RuntimeError('Replace the old Proton bundle with the new Wine bundle using --install; no fallback is used')
    return root


def environment(root, prefix):
    """One environment for application launches and diagnostic observers."""
    env = os.environ.copy()
    for name in ('LD_PRELOAD', 'FEX_ROOTFS', 'FEX_ENV', 'FEX_APP_CONFIG',
                 'FEX_APP_CONFIG_LOCATION', 'WINEPREFIX', 'WINELOADER',
                 'WINESERVER', 'WINEDLLPATH', 'WINEARCH'):
        env.pop(name, None)
    env.update(WINEPREFIX=str(prefix/'pfx'), WINEARCH='win64',
               WINELOADER=str(root/'files/bin/wine'),
               WINESERVER=str(root/'files/bin/wineserver'),
               WINEDLLPATH=str(root/'files/lib/wine'),
               WINEDATADIR=str(root/'files/share/wine'),
               FEX_APP_CONFIG_LOCATION=str(root/'files/share/fex-emu'))
    # Preserve the user's logging preferences, IME and graphics configuration.
    env.setdefault('WINEDEBUG', '-all')
    # Keep application-specific settings (e.g. the official Paint.NET launcher).
    graphics = 'dxgi,d3d11,d3d10core,d3d9,d3d8=n,b'
    env['WINEDLLOVERRIDES'] = graphics + (';'+env['WINEDLLOVERRIDES'] if env.get('WINEDLLOVERRIDES') else '')
    return env


def initialize(root, prefix, env):
    """Use Wine's own prefix updater once per runtime, never Proton's game setup."""
    prefix.mkdir(parents=True, exist_ok=True)
    identity = root.name
    marker = prefix/'arlinux-wine.json'
    with (prefix/'wine-init.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if marker.is_file() and json.loads(marker.read_text()).get('runtime') == identity:
            return
        print('Preparing Wine. The first launch may take a few minutes.', flush=True)
        boot_env = dict(env)
        # An app may select native .NET before it has been installed; wineboot
        # is a native ARM64 Wine program and must not load that x64 dependency.
        boot_env['WINEDLLOVERRIDES'] = 'mscoree=b'
        subprocess.run([env['WINELOADER'], 'wineboot', '-u'], env=boot_env, check=True)
        for arch, directory in (('aarch64', 'system32'), ('i386', 'syswow64')):
            for dll in ('dxgi', 'd3d11', 'd3d10core', 'd3d9', 'd3d8'):
                target = prefix/'pfx/drive_c/windows'/directory/(dll+'.dll')
                if target.is_symlink():
                    target.unlink()
                shutil.copyfile(root/f'files/lib/wine/dxvk/{arch}-windows/{dll}.dll', target)
        temporary = marker.with_suffix('.tmp')
        temporary.write_text(json.dumps({'runtime': identity})+'\n')
        temporary.replace(marker)


def launch(executable, arguments, prefix):
    executable = executable.resolve(strict=True)
    if not executable.is_file():
        raise ValueError('Expected a Windows executable file')
    root = ensure_runtime()
    identity = hashlib.sha256(os.fsencode(executable)).hexdigest()[:24]
    prefix = prefix.resolve() if prefix else storage()/'prefixes'/identity
    env = environment(root, prefix)
    initialize(root, prefix, env)
    return subprocess.call([env['WINELOADER'], str(executable), *arguments],
                           cwd=executable.parent, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', type=Path, metavar='BUNDLE')
    parser.add_argument('--sha256', help='Published SHA-256 of the runtime archive')
    parser.add_argument('--prefix', type=Path, help='Optional shared Wine data directory (contains pfx)')
    parser.add_argument('executable', nargs='?', type=Path)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if platform.machine() not in ('aarch64', 'arm64'):
        parser.error('This runtime requires an ARM64 Linux environment')
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
    except (OSError, ValueError, RuntimeError, tarfile.TarError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'arlinux-windows: {error}')
