"""Connect the Bionic game to the authenticated native Steam session."""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import time

import windows

PAYLOAD = Path('/usr/lib/arlinux/steamworks')


@contextmanager
def session(runtime, prefix, environment):
    appid = environment.get('SteamAppId', '')
    if not appid.isascii() or not appid.isdecimal() or int(appid) == 0:
        raise ValueError('Steamworks needs a nonzero numeric SteamAppId')
    steam = Path(os.environ['STEAM_COMPAT_CLIENT_INSTALL_PATH']).resolve(strict=True)
    library = steam/'steamrtarm64/steamclient.so'
    if not library.is_file():
        raise RuntimeError('Native ARM64 Steam client library is missing')
    required = ['lsteambridge-server', 'aarch64-windows/steam.exe',
                'aarch64-unix/lsteamclient.so', 'i386-windows/lsteamclient.dll',
                'x86_64-windows/lsteamclient.dll']
    if any(not (PAYLOAD/name).is_file() for name in required):
        raise RuntimeError('The Bionic Steamworks bridge is not installed')
    directory = Path(os.environ['XDG_RUNTIME_DIR'])/'steamworks'
    directory.mkdir(mode=0o700, exist_ok=True)
    endpoint = directory/(appid+'.sock')
    # A game owns one bridge for its entire launch. A lock prevents a second
    # Play from unlinking a socket still used by the first launch.
    import shared
    with shared.locked(directory/(appid+'.lock')):
        env = dict(os.environ, **environment)
        env.pop('LD_PRELOAD', None)
        env['LD_LIBRARY_PATH'] = str(steam/'steamrtarm64')
        env['LSTEAM_BRIDGE_SOCKET'] = str(endpoint)
        env['LSTEAM_BRIDGE_WORKDIR'] = str(steam)
        prefix.mkdir(parents=True, exist_ok=True)
        log = prefix/'steamworks.log'
        with log.open('w') as errors:
            process = subprocess.Popen([str(PAYLOAD/'lsteambridge-server'), str(library)],
                env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=errors)
        try:
            deadline = time.monotonic()+30
            while True:
                if process.poll() is not None:
                    raise RuntimeError('Steamworks bridge could not connect to the Steam session; log: '+str(log))
                try:
                    metadata = endpoint.lstat()
                    if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid():
                        raise RuntimeError('Unsafe Steamworks socket')
                    with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as probe:
                        probe.settimeout(.2)
                        probe.connect(str(endpoint))
                    break
                except (FileNotFoundError, ConnectionRefusedError):
                    if time.monotonic() > deadline:
                        raise RuntimeError('Steamworks bridge did not become ready')
                    time.sleep(.1)
            windows.initialize(runtime, prefix, environment)
            facade = prefix/'pfx/drive_c/Program Files (x86)/Steam'
            facade.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PAYLOAD/'aarch64-windows/steam.exe', facade/'steam.exe')
            shutil.copyfile(PAYLOAD/'i386-windows/lsteamclient.dll', facade/'steamclient.dll')
            shutil.copyfile(PAYLOAD/'x86_64-windows/lsteamclient.dll', facade/'steamclient64.dll')
            yield facade/'steam.exe'
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            try:
                metadata = endpoint.lstat()
                if stat.S_ISSOCK(metadata.st_mode) and metadata.st_uid == os.getuid():
                    endpoint.unlink()
            except FileNotFoundError:
                pass
