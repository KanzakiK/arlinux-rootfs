#!/usr/bin/env python3
"""Open the user's file manager, installing a desktop-appropriate fallback if absent."""
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys

from gi.repository import Gio, GLib


def main():
    home = str(Path.home())
    default = Gio.AppInfo.get_default_for_type('inode/directory', False)
    if default and default.get_id() != 'arlinux-files.desktop':
        if default.launch([Gio.File.new_for_path(home)], None):
            return
        raise RuntimeError('The configured default file manager could not be launched')

    desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').upper().split(':')
    # Match the file managers already selected by our distribution recipes.
    command = 'dolphin' if 'KDE' in desktop else 'pcmanfm-qt' if 'LXQT' in desktop else 'thunar'
    cache = Path(os.environ.get('XDG_CACHE_HOME', Path.home()/'.cache'))/'arlinux/files'
    cache.mkdir(parents=True, exist_ok=True)
    with (cache/'install.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not shutil.which(command):
            print(f'Installing {command} from this distribution\'s repositories…', flush=True)
            if shutil.which('apt-get'):
                env = dict(os.environ, DEBIAN_FRONTEND='noninteractive')
                subprocess.run(['sudo', 'apt-get', 'update'], env=env, check=True)
                subprocess.run(['sudo', 'apt-get', 'install', '-y', '--no-install-recommends',
                                command], env=env, check=True)
            elif shutil.which('pacman'):
                # Arch does not support partial upgrades.
                subprocess.run(['sudo', 'pacman', '-Syu', '--needed', '--noconfirm', command], check=True)
            else:
                raise RuntimeError('No supported distribution package manager found')
    os.execvp(command, [command, home])


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, GLib.Error, subprocess.CalledProcessError) as error:
        print(f'File Manager: {error}\nClose this window and click File Manager to retry.',
              file=sys.stderr, flush=True)
        if sys.stdin.isatty():
            try:
                input('\nPress Enter to close this window. ')
            except (EOFError, KeyboardInterrupt):
                pass
        sys.exit(1)
