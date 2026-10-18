"""Product shell tray API backed by Wine's icon registry, not accessibility."""
import json
from pathlib import Path
import socket
import windows

CLIENT = Path('/usr/lib/arlinux/windows-tray.exe')


def call(command):
    root = windows.runtime()
    prefix = windows.storage() / 'prefix'
    if not (prefix / 'pfx/drive_c').is_dir():
        raise FileNotFoundError('Wine prefix is not initialized')
    _, client = windows.request(root, prefix, CLIENT, stdio=True, timeout=8)
    try:
        client.settimeout(6)
        client.sendall((command + '\n').encode())
        data = bytearray()
        while b'\n' not in data:
            chunk = client.recv(65536)
            if not chunk:
                raise RuntimeError('Wine tray client disconnected')
            data.extend(chunk)
            if len(data) > 2 * 1024 * 1024:
                raise RuntimeError('Wine tray reply exceeds limit')
        result = json.loads(data.partition(b'\n')[0])
        if isinstance(result, dict) and 'error' in result:
            raise RuntimeError(result['error'])
        return result
    finally:
        try:
            client.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        client.close()


def snapshot():
    try:
        return call('list')
    except FileNotFoundError:
        return {'process': 0, 'icons': []}


def activate(process, token, action, x, y):
    if action not in ('open', 'menu'):
        raise ValueError('Unknown tray operation')
    if not call(f'{action} {int(process)} {int(token)} {int(x)} {int(y)}'):
        raise RuntimeError('托盘图标已移除，请重新打开托盘。')
