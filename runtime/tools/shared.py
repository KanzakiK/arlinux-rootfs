"""App-owned cross-instance downloads; never place accounts or prefixes here.

The Android host exposes its private files/shared directory at /arlinux-shared.
There is deliberately no per-HOME fallback: an old host must be upgraded.
"""
from contextlib import contextmanager
import fcntl
import hashlib
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path('/arlinux-shared')


def directory(name):
    if not ROOT.is_dir():
        raise RuntimeError('Update ARLinux: the host must provide /arlinux-shared')
    if not re.fullmatch(r'[a-z0-9][a-z0-9/-]*', name) or '..' in name:
        raise ValueError('Invalid shared directory')
    path = ROOT / name
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def locked(path):
    with path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def download(url, expected, suffix):
    """Keep one verified vendor artifact, with a cross-instance download lock."""
    urls = [url] if isinstance(url, str) else list(url)
    if (not re.fullmatch(r'[0-9a-f]{64}', expected)
            or not re.fullmatch(r'\.[a-z0-9.]+', suffix)
            or not urls or any(not u.startswith('https://') for u in urls)):
        raise ValueError('Invalid shared download')
    target = directory('downloads') / (expected + suffix)
    with locked(target.with_suffix(target.suffix + '.lock')):
        if target.is_file() and digest(target) == expected:
            return target
        partial = target.with_suffix(target.suffix + '.part')
        try:
            for url in urls:
                try:
                    subprocess.run(['curl', '-fL', '--retry', '3', '--connect-timeout', '20',
                                    '--speed-limit', '1024', '--speed-time', '60',
                                    '-o', str(partial), url], check=True, stdout=sys.stderr)
                    if digest(partial) != expected:
                        raise ValueError('Shared download SHA-256 mismatch')
                    partial.replace(target)
                    return target
                except (subprocess.CalledProcessError, ValueError):
                    if url == urls[-1]:
                        raise
        finally:
            partial.unlink(missing_ok=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Fetch a verified shared installer')
    parser.add_argument('sha256')
    parser.add_argument('suffix')
    parser.add_argument('urls', nargs='+')
    args = parser.parse_args()
    # stdout is reserved for the pathname consumed by shell installers.
    print(download(args.urls, args.sha256, args.suffix))
