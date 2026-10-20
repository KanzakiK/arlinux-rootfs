#!/usr/bin/env python3
"""Install the pinned official OpenCode Desktop on first use, then launch it."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.request
import shared

BINARY = Path('/opt/OpenCode/ai.opencode.desktop')
MANIFEST = Path('/usr/lib/arlinux/guest/opencode-downloads.tsv')


def configure_default_model():
    """Seed a new user's preference; never replace an existing config or paid fallback."""
    config = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'opencode'
    if any((config / name).exists() for name in ('opencode.json', 'opencode.jsonc')):
        return
    try:
        request = urllib.request.Request('https://opencode.ai/zen/v1/models',
                                         headers={'User-Agent': 'ARLinux-OpenCode'})
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024:
            raise ValueError('OpenCode model response exceeds 1 MiB')
        candidates = [item['id'] for item in json.loads(body)['data']
                      if isinstance(item, dict) and isinstance(item.get('id'), str)
                      and re.fullmatch(r'deepseek-[a-z0-9.-]*flash[a-z0-9.-]*-free', item['id'])]
        if not candidates:
            print('DeepSeek Flash Free unavailable; keeping OpenCode\'s default free model.', flush=True)
            return
        # Compare numeric version components naturally (v10 sorts after v4).
        def version_key(model):
            return tuple((1, int(part)) if part.isdigit() else (0, part)
                         for part in re.split(r'(\d+)', model))
        model = 'opencode/' + max(candidates, key=version_key)
        config.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile('w', dir=config, prefix='.arlinux-model-', delete=False) as output:
                temporary = Path(output.name)
                json.dump({'$schema': 'https://opencode.ai/config.json', 'model': model}, output, indent=2)
                output.write('\n')
            os.link(temporary, config / 'opencode.json')
        except FileExistsError:
            return
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        print(f'Default OpenCode model: {model}', flush=True)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Keeping OpenCode\'s default free model: {error}', flush=True)


def install():
    row = next(line.split('\t') for line in MANIFEST.read_text().splitlines()
               if line.startswith('opencode-desktop\t'))
    _, version, expected, url = row
    extension = url.rsplit('.', 1)[-1]
    if (len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected)
            or not url.startswith('https://') or extension not in ('deb', 'rpm')):
        raise ValueError('Invalid OpenCode download manifest')
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
                if not os.access(app / BINARY.name, os.X_OK):
                    raise RuntimeError('OpenCode executable missing from vendor package')
                app.rename(destination)
    BINARY.parent.parent.mkdir(parents=True, exist_ok=True)
    if BINARY.parent.is_symlink():
        BINARY.parent.unlink()
    if not BINARY.parent.exists():
        BINARY.parent.symlink_to(destination, target_is_directory=True)
    if not os.access(BINARY, os.X_OK):
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
        if not os.access(BINARY, os.X_OK):
            print('Checking OpenCode installation…', flush=True)
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not os.access(BINARY, os.X_OK):
            install()
    # Keep the same accessibility and rendering path for Apps and voice AI.
    # Once preparation finishes, close its terminal without closing the GUI.
    with (cache / 'desktop.log').open('ab') as log:
        subprocess.Popen([str(BINARY), '--force-renderer-accessibility',
                          '--ozone-platform=x11'], cwd='/', start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
    return 0


if __name__ == '__main__':
    try:
        status = main()
    except (OSError, ValueError, RuntimeError, StopIteration, subprocess.CalledProcessError) as error:
        print(f'OpenCode: {error}\nCheck your connection and click OpenCode to retry.', file=sys.stderr)
        status = 1
    if status and '--desktop' in sys.argv and sys.stdin.isatty():
        try:
            input('\nPress Enter to close this window. ')
        except (EOFError, KeyboardInterrupt):
            pass
    sys.exit(status)
