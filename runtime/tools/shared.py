"""App-owned cross-instance downloads; never place accounts or prefixes here.

The Android host exposes files/arlinux-shared at /arlinux-shared, independently
of instance selection, deletion and reinstall.
There is deliberately no per-HOME fallback: an old host must be upgraded.
"""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import hashlib
import json
from pathlib import Path
import re
import subprocess
import shutil
import time
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

    def lookup(options):
        try:
            result = subprocess.run(['curl', '-fsSL', '--connect-timeout', '2', '--max-time', '5',
                                     *options, endpoint], check=True, capture_output=True, text=True,
                                    timeout=6)
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
        except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
            pass
        return None

    # Metadata is small: race valid responses instead of waiting for a blocked
    # direct API request before the accelerated asset transfer can even begin.
    with ThreadPoolExecutor(max_workers=5) as pool:
        jobs = [pool.submit(lookup, options) for options in github_route_options(endpoint, [])]
        for job in as_completed(jobs):
            asset = job.result()
            if asset:
                for pending in jobs:
                    pending.cancel()
                return asset
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



# Destination hints from SteamCommunity302. They never change the request Host,
# TLS SNI, certificate verification, release identity or expected SHA-256.
GITHUB_CONTENT_HOSTS = ('release-assets.githubusercontent.com', 'objects.githubusercontent.com',
                        'raw.githubusercontent.com', 'media.githubusercontent.com')


def github_route_options(url, headers):
    """Share the Chinese-only route policy between metadata and payload requests."""
    language = Path('/etc/arlinux-steam-language')
    host = urlparse(url).hostname
    if (host not in ('github.com', 'api.github.com', 'codeload.github.com', *GITHUB_CONTENT_HOSTS)
            or not language.is_file() or language.read_text().strip() != 'zh'):
        return [headers]
    routes = [headers]
    for number, address in enumerate(('20.205.243.166', '20.207.73.82', '20.27.177.113', '20.233.83.145'), 1):
        destinations = {'github.com': address, 'api.github.com': f'{number}.ghapi.steam302.xyz',
                        'codeload.github.com': f'{number}.ghcodel.steam302.xyz'}
        destinations.update({name: f'{number}.ghcontent.steam302.xyz' for name in GITHUB_CONTENT_HOSTS})
        options = [*headers, '--noproxy', ','.join(destinations)]
        for name, edge in destinations.items():
            options.extend(('--connect-to', f'{name}:443:{edge}:443'))
        routes.append(options)
    return routes


def github_transfer(sources, partial, expected):
    """Keep the winning live connection instead of reconnecting after a probe."""
    routes = [(url, options) for url, headers in sources
              for options in github_route_options(url, headers)]
    if len(routes) == len(sources):
        return False

    def response_mode(header, offset):
        try:
            blocks = re.split(rb'\r?\n\r?\n', header.read_bytes())
            block = next(block for block in reversed(blocks) if block.startswith(b'HTTP/'))
            lines = block.splitlines()
            status = lines[0].split()[1]
            if status == b'200':
                return 'replace'
            if status == b'206':
                fields = dict(line.lower().split(b':', 1) for line in lines[1:] if b':' in line)
                value = fields.get(b'content-range', b'').strip()
                match = re.fullmatch(rb'bytes ([0-9]+)-([0-9]+)/([0-9]+)', value)
                if match and int(match[1]) == offset and offset <= int(match[2]) < int(match[3]):
                    return 'append'
        except (OSError, StopIteration, IndexError):
            pass
        return None

    def stop(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        process.wait()

    remaining = list(enumerate(routes))
    while remaining:
        offset = partial.stat().st_size if partial.is_file() else 0
        workers = []
        try:
            started = time.monotonic()
            for index, (url, options) in remaining:
                body = partial.with_name(partial.name + f'.route-{index}')
                header = body.with_name(body.name + '.headers')
                body.unlink(missing_ok=True)
                header.unlink(missing_ok=True)
                # Each candidate holds only its suffix; no copy of the existing
                # download is needed. Redirect headers remain private and temporary.
                process = subprocess.Popen(['curl', '-fsSL', '--connect-timeout', '5',
                    '--speed-limit', '1024', '--speed-time', '30', '--max-redirs', '10',
                    *(['--range', f'{offset}-'] if offset else []), *options,
                    '--dump-header', str(header), '--output', str(body), url],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                workers.append((index, process, body, header))
            eligible = []
            while time.monotonic() - started < 8:
                eligible = [worker for worker in workers if worker[2].is_file()
                            and worker[2].stat().st_size and response_mode(worker[3], offset)]
                complete = [worker for worker in eligible if worker[1].poll() == 0]
                if complete or eligible and time.monotonic() - started >= 4:
                    if complete:
                        eligible = complete
                    break
                if all(worker[1].poll() is not None for worker in workers):
                    break
                time.sleep(.1)
            if not eligible:
                return False
            winner = max(eligible, key=lambda worker: worker[2].stat().st_size)
            index, process, body, header = winner
            rate = body.stat().st_size / max(.1, time.monotonic() - started)
            print(f'Selected live GitHub route {index}: {rate / 1024:.0f} KiB/s',
                  flush=True, file=sys.stderr)
            for worker in workers:
                if worker is not winner:
                    stop(worker[1])
            minimum = min(262144, int(rate / 4)) if rate >= 65536 else 1024
            window_at, window_bytes = time.monotonic(), body.stat().st_size
            last_progress = window_at
            while process.poll() is None:
                time.sleep(.25)
                now, size = time.monotonic(), body.stat().st_size
                if now - last_progress >= 5:
                    total = size + offset if response_mode(header, offset) == 'append' else size
                    print(f'GitHub download: {total / 1048576:.1f} MiB received',
                          flush=True, file=sys.stderr)
                    last_progress = now
                if now - window_at >= 15:
                    if (size - window_bytes) / (now - window_at) < minimum:
                        stop(process)
                        break
                    window_at, window_bytes = now, size
            mode = response_mode(header, offset)
            if mode == 'append':
                with partial.open('ab') as output, body.open('rb') as source:
                    shutil.copyfileobj(source, output)
            elif mode == 'replace':
                body.replace(partial)
            if process.returncode == 0 and mode and digest(partial) == expected:
                return True
            if process.returncode == 0:
                partial.unlink(missing_ok=True)
            remaining = [(i, route) for i, route in remaining if i != index]
            print('GitHub connection slowed or failed; resuming verified download',
                  flush=True, file=sys.stderr)
        finally:
            for _, process, body, header in workers:
                stop(process)
                body.unlink(missing_ok=True)
                header.unlink(missing_ok=True)
    return False


def download(url, expected, suffix, *, progress=True):
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
        if partial.is_file() and digest(partial) == expected:
            partial.replace(target)
            return target
        try:
            def candidates():
                for source in ranked_sources(urls):
                    if re.fullmatch(r'https://api\.github\.com/repos/[^/]+/[^/]+/releases/assets/[1-9][0-9]*', source):
                        sources = [(source, ['-H', 'Accept: application/octet-stream'])]
                    else:
                        api = github_asset(source, expected)
                        sources = ([(api, ['-H', 'Accept: application/octet-stream'])] if api else []) + [(source, [])]
                    yield sources
            failure = None
            for sources in candidates():
                if github_transfer(sources, partial, expected):
                    partial.replace(target)
                    return target
                for source, headers in sources:
                    try:
                        print('Downloading verified installer…', flush=True, file=sys.stderr)
                        for attempt in range(2):
                            try:
                                subprocess.run(['curl', '-fL', *([] if progress else ['-sS']), '--retry', '2', '--connect-timeout', '10',
                                                '--speed-limit', '1024', '--speed-time', '30',
                                                '--continue-at', '-', *headers, '-o', str(partial), source],
                                               check=True, stdout=sys.stderr)
                                break
                            except subprocess.CalledProcessError as error:
                                # Some official mirrors do not support byte ranges.
                                if attempt == 0 and error.returncode in (33, 36):
                                    partial.unlink(missing_ok=True)
                                    continue
                                if attempt == 0 and error.returncode in (18, 28, 52, 55, 56):
                                    # A transient disconnect does not mean the fastest CDN is down.
                                    continue
                                raise
                        if digest(partial) != expected:
                            # Never append a different CDN's bytes to a corrupt response.
                            partial.unlink(missing_ok=True)
                            raise ValueError('Shared download SHA-256 mismatch')
                        partial.replace(target)
                        return target
                    except (subprocess.CalledProcessError, ValueError) as error:
                        failure = error
            if failure:
                raise failure
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
