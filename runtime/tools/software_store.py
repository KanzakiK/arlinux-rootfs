#!/usr/bin/env python3
"""Install Debian's repository-provided Synaptic on first use, then exec its GUI."""
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    if not shutil.which('apt-get') or not shutil.which('dpkg-query'):
        raise RuntimeError('This software store requires a Debian-family instance')
    cache = Path(os.environ.get('XDG_CACHE_HOME', Path.home()/'.cache'))/'arlinux/software-store'
    cache.mkdir(parents=True, exist_ok=True)
    with (cache/'install.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not shutil.which('synaptic', path=os.defpath + ':/usr/sbin:/sbin'):
            print('Installing Synaptic from this distribution\'s configured repositories…', flush=True)
            env = dict(os.environ, DEBIAN_FRONTEND='noninteractive')
            subprocess.run(['sudo', 'apt-get', 'update'], env=env, check=True)
            subprocess.run(['sudo', 'apt-get', 'install', '-y', '--no-install-recommends',
                            'synaptic'], env=env, check=True)
    # Keep the on-demand entry after installation instead of exposing the
    # vendor's separate pkexec entry, which requires a system polkit service.
    applications = Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))/'applications'
    applications.mkdir(parents=True, exist_ok=True)
    try:
        with (applications/'synaptic.desktop').open('x') as entry:
            entry.write('[Desktop Entry]\nType=Application\nName=Synaptic\nHidden=true\n')
    except FileExistsError:
        pass  # Preserve an existing user override.
    # Synaptic's repository package is an X11 APT frontend. Guest sudo changes
    # only the virtual Linux identity; Android's app UID and isolation remain.
    env = dict(os.environ, GDK_BACKEND='x11')
    os.execvpe('sudo', ['sudo', 'synaptic'], env)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'Software Store: {error}\nClose this window and click Software Store to retry.',
              file=sys.stderr, flush=True)
        if sys.stdin.isatty():
            try:
                input('\nPress Enter to close this window. ')
            except (EOFError, KeyboardInterrupt):
                pass
        sys.exit(1)
