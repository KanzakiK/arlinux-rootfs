#!/usr/bin/env python3
"""Audit a sealed WebView store bundle using Python 3.11+ and zstd."""
import argparse
from contextlib import contextmanager
import shutil
import hashlib
import json
import re
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path
import importlib.util


# Shared by the Windows/WSL build entry and Gradle's final packaging gate.
REQUIRED_RUNTIME = {
    'usr/bin/arlinux-steam',
    *('usr/lib/arlinux/' + name for name in (
        'steam.py', 'steam_bionic.py', 'steam_fex.py', 'steamworks.py',
        'windows.py', 'windows_webview.py', 'windows_apps.py', 'shared.py',
        'guest/windows-downloads.tsv')),
}


@contextmanager
def decompress(stream):
    try:
        import zstandard
    except ImportError:
        # WSL build hosts already provide the zstd CLI.
        with tempfile.TemporaryFile() as compressed:
            shutil.copyfileobj(stream, compressed)
            compressed.seek(0)
            process = subprocess.Popen(['zstd', '-dc'], stdin=compressed, stdout=subprocess.PIPE)
            try:
                yield process.stdout
                if process.wait() != 0:
                    raise ValueError('Rootfs decompression failed')
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                process.stdout.close()
    else:
        with zstandard.ZstdDecompressor().stream_reader(stream) as decoded:
            yield decoded


def verify(path, framework=None, receipt=None):
    if receipt is not None:
        record = json.loads(Path(receipt).read_text())
        with Path(path).open('rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        stage = record.get('stages', {}).get('desktop', {})
        if (record.get('format') != 1 or record.get('desktopSha256') != checksum
                or stage.get('outputs', {}).get('default.zip', {}).get('sha256') != checksum
                or not re.fullmatch(r'[0-9a-f]{64}', str(stage.get('inputs', '')))):
            raise ValueError('Desktop does not match its pipeline build-cache receipt')
    required = {
        # The WebView backend can install catalog-verified packages using
        # native APT when the optional Spark CLI is absent.
        'usr/bin/apt-get',
        'usr/bin/dpkg',
        'usr/bin/dpkg-deb',
        'usr/bin/python3',
    }
    required |= REQUIRED_RUNTIME
    expected_sources = {}
    expected_assets = {}
    if framework:
        spec = importlib.util.spec_from_file_location('desktop_runtime', Path(__file__).with_name('desktop-runtime.py'))
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        expected_sources = {name: hashlib.sha256(source.read_bytes()).hexdigest()
                            for name, source in runtime.runtime_files(framework).items()}
        expected_assets = {name: hashlib.sha256(source.read_bytes()).hexdigest()
                           for name, source in runtime.bundle_files(framework).items()}
        required.update(expected_sources)
    found = set()
    with zipfile.ZipFile(path) as bundle:
        manifest = json.loads(bundle.read('manifest.json'))
        names = bundle.namelist()
        if len(names) != len(set(names)) or set(names) != set(manifest['files']) | {'manifest.json'}:
            raise ValueError('Bundle entries differ from manifest')
        for name, expected in expected_assets.items():
            if name not in names or hashlib.sha256(bundle.read(name)).hexdigest() != expected:
                raise ValueError('Missing or stale installation asset: ' + name)
        for name, expected in expected_sources.items():
            outer = name.removeprefix('usr/lib/arlinux/')
            if outer.startswith('guest/') and outer in names:
                if hashlib.sha256(bundle.read(outer)).hexdigest() != expected:
                    raise ValueError('Stale installation helper in bundle: ' + outer)
        for name, expected in manifest['files'].items():
            with bundle.open(name) as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                    raise ValueError('Checksum mismatch: ' + name)
        with bundle.open('rootfs.tar.zst') as compressed, decompress(compressed) as decoded:
            with tarfile.open(fileobj=decoded, mode='r|') as root:
                for member in root:
                    name = member.name.removeprefix('./').rstrip('/')
                    if name in expected_sources:
                        if not member.isfile() or hashlib.file_digest(root.extractfile(member), 'sha256').hexdigest() != expected_sources[name]:
                            raise ValueError('Stale runtime source in bundle: ' + name)
                    if name == 'opt/spark-store/bin' or name.startswith('opt/spark-store/bin/'):
                        raise ValueError('Electron payload remains: ' + name)
                    if name in required:
                        if not (member.isfile() or member.issym() or member.islnk()):
                            raise ValueError('Required runtime is not a file: ' + name)
                        if member.isfile() and member.size == 0:
                            raise ValueError('Empty runtime file: ' + name)
                        if name in REQUIRED_RUNTIME and not member.isfile():
                            raise ValueError('Required runtime must be bundled as a regular file: ' + name)
                        found.add(name)
    if missing := required - found:
        raise ValueError('Missing desktop runtime: ' + ', '.join(sorted(missing)))
    print(json.dumps({'bundle': str(path), 'checksums': 'verified', 'electron': 'absent',
                      'requiredBackend': sorted(found)}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle')
    parser.add_argument('--framework', type=Path, help='Reject runtime files differing from current rootfs sources')
    parser.add_argument('--receipt', type=Path, help='Require the pipeline build-cache receipt for this artifact')
    args = parser.parse_args()
    verify(args.bundle, args.framework, args.receipt)
