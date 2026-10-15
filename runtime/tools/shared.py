"""App-owned cross-instance downloads; never place accounts or prefixes here.

The Android host exposes its private files/shared directory at /arlinux-shared.
There is deliberately no per-HOME fallback: an old host must be upgraded.
"""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlparse, unquote

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


def github_asset(url, expected):
    """Use GitHub's official asset API when its web download host is unreachable."""
    parsed = urlparse(url)
    match = re.fullmatch(r'/([^/]+)/([^/]+)/releases/download/([^/]+)/([^/]+)', parsed.path)
    if parsed.scheme != 'https' or parsed.netloc != 'github.com' or not match:
        return None
    owner, repo, tag, filename = match.groups()
    endpoint = f'https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}'
    try:
        result = subprocess.run(['curl', '-fsSL', '--connect-timeout', '10', '--max-time', '30',
                                 endpoint], check=True, capture_output=True, text=True)
        release = json.loads(result.stdout)
        for asset in release.get('assets', []):
            if asset.get('name') != unquote(filename):
                continue
            identity = asset.get('id')
            if not isinstance(identity, int) or identity <= 0:
                return None
            checksum = asset.get('digest')
            if checksum is not None and checksum != 'sha256:' + expected:
                return None
            return f'https://api.github.com/repos/{owner}/{repo}/releases/assets/{identity}'
    except (subprocess.CalledProcessError, json.JSONDecodeError, AttributeError):
        pass
    return None


def ranked_sources(urls):
    """Compare bounded real transfers across official mirrors, never log signed URLs."""
    language = Path('/etc/arlinux-steam-language')
    if len(urls) < 2 or not language.is_file() or language.read_text().strip() != 'zh':
        return urls

    def probe(url):
        try:
            result = subprocess.run(['curl', '-fsSL', '--connect-timeout', '2', '--max-time', '4',
                '--range', '0-262143', '--output', '/dev/null', '--write-out',
                '%{http_code} %{size_download} %{speed_download}', url],
                capture_output=True, text=True, timeout=5)
            status, size, speed = result.stdout.strip().split()
            # curl 28 is expected if a server ignores Range and streams the whole file.
            if result.returncode in (0, 28) and status in ('200', '206') and float(size) >= 16384:
                return float(speed)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        return 0

    with ThreadPoolExecutor(max_workers=3) as pool:
        rates = list(pool.map(probe, urls))
    ordered = sorted(zip(urls, rates), key=lambda item: -item[1])
    if ordered[0][1]:
        print('Selected official download CDN: ' + urlparse(ordered[0][0]).hostname,
              flush=True, file=sys.stderr)
    return [url for url, speed in ordered]


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
            candidates = []
            for source in ranked_sources(urls):
                if re.fullmatch(r'https://api\.github\.com/repos/[^/]+/[^/]+/releases/assets/[1-9][0-9]*', source):
                    candidates.append((source, ['-H', 'Accept: application/octet-stream']))
                    continue
                api = github_asset(source, expected)
                if api:
                    candidates.append((api, ['-H', 'Accept: application/octet-stream']))
                candidates.append((source, []))
            for index, (source, headers) in enumerate(candidates):
                try:
                    print('Downloading verified installer…', flush=True, file=sys.stderr)
                    for attempt in range(2):
                        try:
                            subprocess.run(['curl', '-fL', '--retry', '2', '--connect-timeout', '10',
                                            '--speed-limit', '1024', '--speed-time', '30',
                                            '--continue-at', '-', *headers, '-o', str(partial), source],
                                           check=True, stdout=sys.stderr)
                            break
                        except subprocess.CalledProcessError as error:
                            # Some official mirrors do not support byte ranges.
                            if attempt == 0 and error.returncode in (33, 36):
                                partial.unlink(missing_ok=True)
                                continue
                            raise
                    if digest(partial) != expected:
                        # Never append a different CDN's bytes to a corrupt response.
                        partial.unlink(missing_ok=True)
                        raise ValueError('Shared download SHA-256 mismatch')
                    partial.replace(target)
                    return target
                except (subprocess.CalledProcessError, ValueError):
                    if index == len(candidates) - 1:
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
