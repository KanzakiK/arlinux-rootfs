#!/usr/bin/env python3
"""Install the current official OpenCode Desktop on first use, then launch it."""
import argparse
import configparser
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.request
from urllib.parse import urlparse
import shared

BINARY = Path('/opt/OpenCode/ai.opencode.desktop')
LAUNCHER = Path('/opt/OpenCode/.arlinux-launch')
UPDATE_URL = 'https://opencode.ai/update/api/latest/desktop/opencode'


def official_json(address):
    request = urllib.request.Request(address, headers={'User-Agent': 'ARLinux-OpenCode'})
    with urllib.request.urlopen(request, timeout=15) as response:
        if not response.geturl().startswith('https://'):
            raise ValueError('Insecure OpenCode metadata redirect')
        body = response.read(1024 * 1024 + 1)
    if len(body) > 1024 * 1024:
        raise ValueError('OpenCode metadata exceeds 1 MiB')
    return json.loads(body)


def latest_installer():
    # V2 publishes through its own update service; GitHub latest still tracks V1.
    release = official_json(UPDATE_URL)
    if not isinstance(release, dict):
        raise ValueError('Invalid official OpenCode release')
    version = release['version']
    if (release.get('channel') != 'latest' or release.get('name') != 'desktop'
            or release.get('distribution') != 'opencode' or release.get('active') is not True
            or not isinstance(version, str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version)):
        raise ValueError('Invalid official OpenCode release')
    filename = ('opencode-desktop-linux-arm64.deb' if Path('/usr/bin/apt-get').exists()
                else 'opencode-desktop-linux-aarch64.rpm')
    asset = release['metadata']['files'][filename]
    expected, url = asset['sha256'], asset['url']
    if not isinstance(url, str):
        raise ValueError('Invalid official OpenCode installer URL')
    parsed = urlparse(url)
    if (not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected)
            or parsed.scheme != 'https' or parsed.netloc != 'opencode.ai'
            or parsed.path != f'/files/bin/{version}/{filename}' or parsed.query or parsed.fragment):
        raise ValueError('Invalid official OpenCode installer metadata')
    return version, expected, url


def configure_default_model():
    """Seed a new user's preference; never replace an existing config or paid fallback."""
    config = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'opencode'
    if any((config / name).exists() for name in ('opencode.json', 'opencode.jsonc')):
        return
    settings = {'$schema': 'https://opencode.ai/config.json',
                'permission': {'external_directory': 'allow'}}
    try:
        candidates = [item['id'] for item in official_json('https://opencode.ai/zen/v1/models')['data']
                      if isinstance(item, dict) and isinstance(item.get('id'), str)
                      and re.fullmatch(r'deepseek-[a-z0-9.-]*flash[a-z0-9.-]*-free', item['id'])]
        if not candidates:
            print('DeepSeek Flash Free unavailable; keeping OpenCode\'s default free model.', flush=True)
        else:
            # Compare numeric version components naturally (v10 sorts after v4).
            def version_key(model):
                return tuple((1, int(part)) if part.isdigit() else (0, part)
                             for part in re.split(r'(\d+)', model))
            settings['model'] = 'opencode/' + max(candidates, key=version_key)
            print(f'Default OpenCode model: {settings["model"]}', flush=True)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Keeping OpenCode\'s default free model: {error}', flush=True)
    try:
        config.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile('w', dir=config, prefix='.arlinux-model-', delete=False) as output:
                temporary = Path(output.name)
                json.dump(settings, output, indent=2)
                output.write('\n')
            os.link(temporary, config / 'opencode.json')
        except FileExistsError:
            return
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    except OSError as error:
        print(f'Could not save initial OpenCode preferences: {error}', flush=True)


def install():
    version, expected, url = latest_installer()
    extension = url.rsplit('.', 1)[-1]
    print(f'Preparing OpenCode {version}. The first download may take a few minutes.\n'
          'Internet access is required. Subsequent launches use the installed app.', flush=True)
    package = shared.download(url, expected, '.' + extension)
    env = dict(os.environ, DEBIAN_FRONTEND='noninteractive')
    if extension == 'deb':
        subprocess.run(['sudo', 'apt-get', 'update'], env=env, check=True)
        dependencies = subprocess.check_output(
            ['dpkg-deb', '-f', str(package), 'Depends'], text=True).strip()
        if dependencies:
            subprocess.run(['sudo', 'apt-get', 'satisfy', '-y', '--no-install-recommends',
                            dependencies], env=env, check=True)
    else:
        # The official ARM64 RPM contains an ordinary Linux application payload.
        subprocess.run(['sudo', 'pacman', '-S', '--needed', '--noconfirm',
                        'libarchive', 'gtk3', 'nss', 'libxss', 'libxtst', 'libsecret',
                        'alsa-plugins', 'libpulse', 'cups', 'libdrm', 'mesa'], check=True)
    # Share only the vendor's self-contained application, not distro libraries.
    payloads = shared.directory('opencode')
    destination = payloads / expected
    with shared.locked(payloads / 'extract.lock'):
        if not destination.is_dir():
            with tempfile.TemporaryDirectory(prefix='extract-', dir=payloads) as temporary:
                stage = Path(temporary)
                if extension == 'deb':
                    subprocess.run(['dpkg-deb', '-x', str(package), str(stage)], check=True)
                else:
                    subprocess.run(['bsdtar', '-xpf', str(package), '-C', str(stage)], check=True)
                app = stage / 'opt/OpenCode'
                # The vendor may rename its binary without changing the package
                # version. Read the package's desktop entry, not a filename list.
                executables = set()
                for entry in (stage / 'usr/share/applications').glob('*.desktop'):
                    desktop = configparser.ConfigParser(interpolation=None, strict=False)
                    desktop.read(entry)
                    command = shlex.split(desktop.get('Desktop Entry', 'Exec', fallback=''))
                    if not command or not command[0].startswith('/opt/OpenCode/'):
                        continue
                    relative = Path(command[0]).relative_to('/opt/OpenCode')
                    candidate = app / relative
                    if candidate.resolve().is_relative_to(app.resolve()) and os.access(candidate, os.X_OK):
                        executables.add(relative)
                if len(executables) != 1:
                    raise RuntimeError('Vendor desktop entries do not identify one OpenCode executable')
                (app / LAUNCHER.name).symlink_to(executables.pop())
                app.rename(destination)
    BINARY.parent.parent.mkdir(parents=True, exist_ok=True)
    if BINARY.parent.is_symlink():
        BINARY.parent.unlink()
    if not BINARY.parent.exists():
        BINARY.parent.symlink_to(destination, target_is_directory=True)
    if not os.access(LAUNCHER, os.X_OK):
        raise RuntimeError('OpenCode executable missing after installation')
    # Keep one Apps entry: the package ships two vendor launchers. Standard
    # per-user desktop overrides hide them without modifying package files.
    applications = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'applications'
    applications.mkdir(parents=True, exist_ok=True)
    for name in ('ai.opencode.desktop.desktop', 'opencode-desktop.desktop'):
        (applications / name).write_text('[Desktop Entry]\nType=Application\nName=OpenCode\nHidden=true\n')
    configure_default_model()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop', action='store_true', help='Keep errors visible in the launcher terminal')
    parser.parse_args()
    cache = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'arlinux/opencode'
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / 'install.lock').open('w') as lock:
        if not any(os.access(path, os.X_OK) for path in (LAUNCHER, BINARY)):
            print('Checking OpenCode installation…', flush=True)
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not any(os.access(path, os.X_OK) for path in (LAUNCHER, BINARY)):
            install()
    # Keep the same accessibility and rendering path for Apps and voice AI.
    # Once preparation finishes, close its terminal without closing the GUI.
    env = dict(os.environ)
    # Bun's WebAssembly signal setup can terminate syscall-translated guests
    # with SIGSYS. Use OpenCode's upstream portable permission scanner instead.
    # Inline config merges with user settings; keep explicit caller overrides.
    env.setdefault('OPENCODE_CONFIG_CONTENT',
                   '{"experimental":{"portable_shell_scanner":true}}')
    # The Electron server spawns shell tools outside the desktop's bus discovery.
    # Publish the live desktop address to its children, including arlinux.a11y.
    try:
        published = subprocess.check_output(['xprop', '-root', 'AT_SPI_BUS'],
                                            text=True, stderr=subprocess.DEVNULL, timeout=3)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        published = ''
    address = re.search(r'AT_SPI_BUS\(STRING\) = "([^"]+)"', published)
    if address:
        env['AT_SPI_BUS_ADDRESS'] = address[1]
    with (cache / 'desktop.log').open('ab') as log:
        binary = LAUNCHER if os.access(LAUNCHER, os.X_OK) else BINARY
        subprocess.Popen([str(binary), '--force-renderer-accessibility',
                          '--ozone-platform=x11'], cwd='/', start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env)
    return 0


if __name__ == '__main__':
    try:
        status = main()
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'OpenCode: {error}\nCheck your connection and click OpenCode to retry.', file=sys.stderr)
        status = 1
    if status and '--desktop' in sys.argv and sys.stdin.isatty():
        try:
            input('\nPress Enter to close this window. ')
        except (EOFError, KeyboardInterrupt):
            pass
    sys.exit(status)
