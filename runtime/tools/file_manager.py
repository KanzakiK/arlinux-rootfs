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
    installing = sys.argv[1:] == ['--install']
    default = Gio.AppInfo.get_default_for_type('inode/directory', False)
    if not installing and default and default.get_id() != 'arlinux-files.desktop':
        # Match running_app.py: launch in the owned tree, not the session daemon.
        if isinstance(default, Gio.DesktopAppInfo):
            entry = GLib.KeyFile()
            entry.load_from_file(default.get_filename(), GLib.KeyFileFlags.NONE)
            entry.set_boolean('Desktop Entry', 'DBusActivatable', False)
            default = Gio.DesktopAppInfo.new_from_keyfile(entry)
        if default.launch([Gio.File.new_for_path(home)], None):
            return
        raise RuntimeError('The configured default file manager could not be launched')

    desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').upper().split(':')
    # Match the file managers already selected by our distribution recipes.
    command = 'dolphin' if 'KDE' in desktop else 'pcmanfm-qt' if 'LXQT' in desktop else 'thunar'
    if not shutil.which(command) and not installing:
        # Ordinary launches have no terminal. Only installation needs progress
        # output and an interactive retryable error message.
        os.execvp('foot', ['foot', 'arlinux-files', '--install'])
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
        else:
            import gi
            gi.require_version('Gtk', '3.0')
            from gi.repository import Gtk
            dialog = Gtk.MessageDialog(message_type=Gtk.MessageType.ERROR,
                                       buttons=Gtk.ButtonsType.CLOSE, text='File Manager')
            dialog.format_secondary_text(str(error))
            dialog.run()
            dialog.destroy()
        sys.exit(1)
