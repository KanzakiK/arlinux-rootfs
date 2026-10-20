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
RUNTIME_INDEX = 'arlinux-wine-manifests.json'
COMPONENT_BASE = 'https://github.com/taowen/wine/releases/download/arlinux-wine-components/'


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
    files = metadata['files']
    for name, expected in files.items():
        if not isinstance(name, str) or not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
            raise ValueError('Invalid Bionic file checksum')
        path = root/name
        if not path.resolve().is_relative_to(root):
            raise ValueError('Runtime file escapes the bundle')
        if digest(path) != expected:
            raise ValueError(f'Bionic bundle checksum mismatch: {name}')
    return metadata


def runtime_url(url, filename):
    return bool(re.fullmatch(r'https://github\.com/taowen/(?:wine|FEX|dxvk|arlinux-steamworks|arlinux-windows-integration)'
                            r'/releases/download/[^/]+/'+re.escape(filename), url))


def runtime_index(archive):
    index = json.loads(archive.read_text())
    if index.get('format') == 1 and index.get('kind') == 'arlinux-bionic-components':
        return index
    if (index.get('format') != 2 or index.get('kind') != 'arlinux-bionic-manifests'
            or not isinstance(index.get('manifests'), list) or not index['manifests']):
        raise ValueError('Expected independently pinned Bionic runtime manifests')
    merged = dict(format=1, kind='arlinux-bionic-components', runtime={}, components=[])
    names = set()
    for item in index['manifests']:
        name, filename, checksum = item['name'], item['file'], item['sha256']
        if (not re.fullmatch('[a-z0-9_-]+', name) or filename != 'arlinux-'+name+'.json'
                or name in names or not re.fullmatch('[0-9a-f]{64}', checksum)
                or not runtime_url(item['url'], filename)
                or type(item['bytes']) is not int or item['bytes'] <= 0):
            raise ValueError('Invalid independent runtime manifest')
        names.add(name)
        source = shared.download(item['url'], checksum, '.json')
        if source.stat().st_size != item['bytes']:
            raise ValueError('Runtime manifest size mismatch: '+name)
        child = json.loads(source.read_text())
        if child.get('format') != 1 or child.get('kind') != 'arlinux-bionic-components':
            raise ValueError('Expected a leaf runtime component manifest')
        for key, value in child['runtime'].items():
            if key in ('files', 'originalSources'):
                previous = merged['runtime'].setdefault(key, {})
                for field, content in value.items():
                    if field in previous and (key == 'files' or previous[field] != content):
                        raise ValueError('Conflicting runtime metadata: '+field)
                    previous[field] = content
            elif key in merged['runtime'] and merged['runtime'][key] != value:
                raise ValueError('Conflicting runtime metadata: '+key)
            else:
                merged['runtime'][key] = value
        merged['components'].extend(child['components'])
    return merged


def install(archive, expected):
    if not re.fullmatch('[0-9a-f]{64}', expected) or digest(archive) != expected:
        raise ValueError('Runtime manifest SHA-256 mismatch')
    index = runtime_index(archive)
    if (index.get('format') != 1 or index.get('kind') != 'arlinux-bionic-components'
            or not index.get('components') or index['runtime'].get('protocol') != 1
            or index['runtime'].get('libc') != 'bionic'):
        raise ValueError('Expected a Bionic runtime component manifest')
    components = []
    names = set()
    for item in index['components']:
        checksum, name = item['sha256'], item['file']
        if (not re.fullmatch('[0-9a-f]{64}', checksum)
                or not re.fullmatch(r'[a-z0-9_-]+-'+checksum+r'\.tar\.gz', name)
                or not runtime_url(item['url'], item.get('asset', name)) or name in names
                or type(item['bytes']) is not int or item['bytes'] <= 0):
            raise ValueError('Invalid Bionic runtime component')
        names.add(name)
        component = shared.download(item['url'], checksum, '.tar.gz')
        if component.stat().st_size != item['bytes']:
            raise ValueError('Runtime component size mismatch: '+name)
        components.append(component)
    home = runtime_storage()
    destination = home/expected
    with (home/'install.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not destination.exists():
            print('Installing Windows runtime…', flush=True)
            with tempfile.TemporaryDirectory(prefix='install-', dir=home) as temporary:
                stage = Path(temporary)/'runtime'
                stage.mkdir()
                members = set()
                for component in components:
                    with tarfile.open(component, 'r:*') as bundle:
                        for member in bundle:
                            # Components contain files/links, not shared parent
                            # directory entries. Never overwrite another component.
                            name = member.name
                            if index.get('embeddedMetadata') and name == 'bionic-runtime.json':
                                continue
                            if (name in members or name == 'bionic-runtime.json'
                                    or '\\' in name or ':' in name
                                    or any(part in ('', '.', '..') for part in name.split('/'))
                                    or member.isdir()):
                                raise ValueError('Invalid or duplicate runtime path: '+name)
                            members.add(name)
                            bundle.extract(member, stage, filter='data')
                (stage/'bionic-runtime.json').write_text(json.dumps(index['runtime'])+'\n')
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
        identity = os.environ.get('ARLINUX_WINE_CANDIDATE') or json.loads((home/'current.json').read_text())['sha256']
    if not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{64}', identity):
        raise ValueError('Invalid runtime identity')
    root = home/identity
    metadata = json.loads((root/'bionic-runtime.json').read_text())
    if metadata.get('protocol') != 1 or metadata.get('libc') != 'bionic':
        raise ValueError('Only Bionic Wine is supported')
    return root


def ensure_runtime():
    # The debug host supplies an instance-scoped candidate selection. It uses
    # the same verified component installer and never changes the public latest
    # lookup or its cache. Missing candidates fail instead of falling back.
    candidate = os.environ.get('ARLINUX_WINE_CANDIDATE', '')
    if candidate:
        if not re.fullmatch('[0-9a-f]{64}', candidate):
            raise ValueError('Invalid candidate Wine SHA-256')
        if not (runtime_storage()/candidate).exists():
            install(shared.directory('downloads')/(candidate+'.json'), candidate)
        return runtime(candidate)
    try:
        selected = json.loads(LATEST_SELECTION.read_text())
        age = time.time() - selected.get('checkedAt', 0)
        if selected.get('manifestSHA256') == digest(MANIFEST) and 0 <= age < 3600:
            return runtime(selected['sha256'])
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        pass
    expected, source = latest_runtime()
    install(source, expected)
    remember_latest(expected)
    return runtime(expected)


def remember_latest(identity):
    LATEST_SELECTION.parent.mkdir(parents=True, exist_ok=True)
    temporary = LATEST_SELECTION.with_suffix('.tmp')
    temporary.write_text(json.dumps({'sha256': identity, 'checkedAt': time.time(),
                                    'manifestSHA256': digest(MANIFEST)})+'\n')
    temporary.replace(LATEST_SELECTION)


def release_asset(row):
    name, repository, tag, filename = row
    if (not re.fullmatch('[a-z0-9_-]+', name)
            or not re.fullmatch('taowen/(wine|FEX|dxvk|arlinux-steamworks|arlinux-windows-integration)', repository)
            or tag != 'arlinux-'+name+'-latest' or filename != 'runtime.tar.gz'):
        raise ValueError('Invalid runtime release endpoint')
    endpoint = f'https://api.github.com/repos/{repository}/releases/tags/{tag}'
    try:
        result = subprocess.run(['curl', '-fsSL', '--connect-timeout', '10', '--max-time', '30',
                                 endpoint], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError:
        # Preserve GitHub's public digest fallback when the unauthenticated API
        # is rate limited. Download size is then recorded after hash validation.
        class Assets(HTMLParser):
            def __init__(self):
                super().__init__()
                self.checksums = []
                self.link = False

            def handle_starttag(self, tag_name, attrs):
                attrs = dict(attrs)
                if tag_name == 'a' and attrs.get('href') == f'/{repository}/releases/download/{tag}/{filename}':
                    self.link = True
                if tag_name == 'clipboard-copy' and attrs.get('aria-label') == 'Copy to clipboard digest for '+filename:
                    self.checksums.append(attrs.get('value', ''))

        page = subprocess.run(['curl', '-fsSL', '--connect-timeout', '10', '--max-time', '30',
                               f'https://github.com/{repository}/releases/expanded_assets/{tag}'],
                              check=True, capture_output=True, text=True)
        assets = Assets()
        assets.feed(page.stdout)
        if not assets.link or len(assets.checksums) != 1 or not re.fullmatch('sha256:[0-9a-f]{64}', assets.checksums[0]):
            raise ValueError('Runtime release has no verified digest: '+name)
        checksum = assets.checksums[0][7:]
        return dict(name=name, file=name+'-'+checksum+'.tar.gz', asset=filename,
                    sha256=checksum, bytes=None,
                    url=f'https://github.com/{repository}/releases/download/{tag}/{filename}')
    release = json.loads(result.stdout)
    if release.get('draft') or release.get('tag_name') != tag:
        raise ValueError('Invalid runtime release')
    asset = next((a for a in release.get('assets', []) if a.get('name') == filename), None)
    if (not asset or asset.get('state') != 'uploaded'
            or not isinstance(asset.get('digest'), str)
            or not re.fullmatch('sha256:[0-9a-f]{64}', asset['digest'])
            or type(asset.get('size')) is not int or asset['size'] <= 0
            or type(asset.get('id')) is not int or asset['id'] <= 0):
        raise ValueError('Runtime release has no verified asset: '+name)
    checksum = asset['digest'][7:]
    return dict(name=name, file=name+'-'+checksum+'.tar.gz', asset=filename,
                sha256=checksum, bytes=asset['size'],
                url=f'https://github.com/{repository}/releases/download/{tag}/{filename}')


def latest_runtime():
    """GitHub releases are the download index; no public JSON selection."""
    from concurrent.futures import ThreadPoolExecutor
    rows = [line.split('\t') for line in MANIFEST.read_text().splitlines()
            if line.strip() and not line.startswith('#')]
    if not rows or any(len(row) != 4 for row in rows) or len({r[0] for r in rows}) != len(rows):
        raise ValueError('Invalid runtime release endpoints')
    with ThreadPoolExecutor(max_workers=4) as pool:
        components = list(pool.map(release_asset, rows))
    merged = {}
    for item in components:
        archive = shared.download(item['url'], item['sha256'], '.tar.gz')
        if item['bytes'] is not None and archive.stat().st_size != item['bytes']:
            raise ValueError('Runtime release size mismatch')
        item['bytes'] = archive.stat().st_size
        with tarfile.open(archive) as packed:
            member = packed.getmember('bionic-runtime.json')
            if not member.isfile() or member.size > 4*1024*1024:
                raise ValueError('Invalid embedded runtime metadata')
            metadata = json.load(packed.extractfile(member))
        if metadata.get('protocol') != 1 or metadata.get('libc') != 'bionic':
            raise ValueError('Invalid runtime component metadata')
        for key, value in metadata.items():
            if key in ('files', 'originalSources', 'compatibility'):
                target = merged.setdefault(key, {})
                for field, content in value.items():
                    if field in target and (key == 'files' or target[field] != content):
                        raise ValueError('Incompatible runtime releases: '+field)
                    target[field] = content
            elif key == 'sources':
                continue
            elif key in merged and merged[key] != value:
                raise ValueError('Incompatible runtime metadata: '+key)
            else:
                merged[key] = value
    # This is an internal cache receipt, never a published download manifest.
    index = dict(format=1, kind='arlinux-bionic-components', embeddedMetadata=True,
                 runtime=merged, components=components)
    encoded = (json.dumps(index, sort_keys=True, indent=2)+'\n').encode()
    checksum = hashlib.sha256(encoded).hexdigest()
    source = shared.directory('downloads')/(checksum+'.json')
    with shared.locked(source.with_suffix('.lock')):
        with tempfile.NamedTemporaryFile(dir=source.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(encoded)
        temporary.replace(source)
    return checksum, source

def host_path(path):
    """Map guest files to Android backing files (including per-instance HOME)."""
    path = Path(path).resolve()
    files = Path(os.environ['BIONICX_FILES']).resolve()
    if path.is_relative_to('/arlinux-shared'):
        return files/'arlinux-shared'/path.relative_to('/arlinux-shared')
    if path.is_relative_to(files):
        return path
    return Path(os.environ['BIONICX_ROOTFS'])/str(path).lstrip('/')


def guest_path(path):
    files = Path(os.environ['BIONICX_FILES']).resolve()
    path = Path(path)
    if path.is_relative_to(files/'arlinux-shared'):
        return Path('/arlinux-shared')/path.relative_to(files/'arlinux-shared')
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


def request(root, prefix, executable, arguments=(), overrides='', stdio=False, diagnostics=None, timeout=300, task=True):
    exe = str(executable)
    if exe.startswith('/'):
        exe = str(host_path(exe))
    argv = [str(host_path(value)) if str(value).startswith('/') and
        not re.fullmatch('/[A-Za-z][A-Za-z0-9:_-]*', str(value)) else str(value)
        for value in arguments]
    payload = dict(runtime=root.name, prefix=str(host_path(prefix/'pfx')), exe=exe,
                   args=argv, dllOverrides=overrides, stdio=stdio, task=task)
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


def run(root, prefix, executable, arguments=(), env=None, check=False, capture=False, timeout=600, task=False):
    """Wait for a command; interactive tasks also retain their child processes."""
    env = env or {}
    diagnostics = {name: env[name] for name in ('WINEDEBUG', 'ARLINUX_EXCEPTION_LOG', 'ARLINUX_VULKAN_CAPTURE',
        'SteamAppId', 'SteamGameId', 'SteamOverlayGameId',
        'WEBVIEW2_BROWSER_EXECUTABLE_FOLDER', 'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS') if name in env}
    response = request(root, prefix, executable, arguments, env.get('WINEDLLOVERRIDES', ''),
                       diagnostics=diagnostics, task=task)
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
    import windows_webview
    env = windows_webview.prepare(root, prefix, env)
    windows_a11y.ensure(root, prefix, executable.stem, env)
    if executable.suffix.lower() == '.lnk':
        return run(root, prefix, 'start.exe', [str(executable), *arguments], env=env, timeout=None, task=True).returncode
    return run(root, prefix, executable, arguments, env=env, timeout=None, task=True).returncode


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
