#!/usr/bin/env python3
"""Internal sealing stage for the WSL-built package cache. See docs/BUILD.md."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import posixpath
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

from bundle import verify


def omit_desktop_resource(name: str, directory: bool = False, symlink: str | None = None) -> bool:
    """Trim optional resources while keeping CJK Sans, translations and legal notices."""
    name = name.removeprefix('./').rstrip('/')
    optional_fonts = {
        'usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc',
        'usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc',
    }
    if name in optional_fonts:
        return True
    if symlink:
        target = (symlink.lstrip('/') if symlink.startswith('/') else
                  posixpath.normpath(posixpath.join(posixpath.dirname(name), symlink)))
        if (target in optional_fonts or target.startswith(('usr/share/man/', 'usr/share/locale/'))) and omit_desktop_resource(target):
            return True
    parts = name.split('/')
    if parts[:3] == ['usr', 'share', 'locale'] and len(parts) > 3:
        language = parts[3].split('_', 1)[0].split('@', 1)[0].split('.', 1)[0]
        return language not in {'en', 'zh', 'C', 'POSIX'} and parts[3] != 'locale.alias'
    if parts[:3] == ['usr', 'share', 'man']:
        return True
    if parts[:3] == ['usr', 'share', 'doc'] and len(parts) > 4 and not directory:
        notices = ('copyright', 'license', 'licence', 'copying', 'notice', 'authors', 'legal', 'credits')
        return not any(part.lower().startswith(notices) for part in parts[4:])
    return False


def rewrite(seed: Path, output: Path, replacements: dict[str, bytes | Path]) -> None:
    verify(seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    pending = output.with_suffix('.zip.part')
    with zipfile.ZipFile(seed) as source, zipfile.ZipFile(pending, 'w') as target:
        manifest = json.loads(source.read('manifest.json'))
        if manifest['distributionId'] not in ('debian', 'yibu', 'arch', 'omarchy', 'plasma'):
            raise ValueError('Unsupported offline desktop distribution')
        for name in sorted(set(manifest['files']) | set(replacements)):
            value = replacements.get(name)
            digest = hashlib.sha256()
            stream = (value.open('rb') if isinstance(value, Path) else
                      io.BytesIO(value) if isinstance(value, bytes) else source.open(name))
            with stream, target.open(name, 'w', force_zip64=True) as dest:
                while block := stream.read(1024 * 1024):
                    digest.update(block)
                    dest.write(block)
            manifest['files'][name] = digest.hexdigest()
        target.writestr('manifest.json', json.dumps(manifest, indent=2) + '\n')
    verify(pending)
    pending.replace(output)


def required_snapshot_files(distribution: str) -> set[str]:
    common = {'usr/share/arlinux/offline-desktop', 'usr/share/arlinux/packages.tsv'}
    if distribution in ('arch', 'omarchy'):
        return common | {'usr/bin/pacman',
                         'var/lib/arlinux/runtime-epoch-1', 'usr/share/arlinux/offline-distribution',
                         'usr/bin/xterm' if distribution == 'arch' else 'usr/bin/foot'} | (
                             {'usr/bin/hyprctl'} if distribution == 'omarchy' else set())
    if distribution == 'plasma':
        return common | {'usr/bin/plasmashell', 'usr/bin/dolphin', 'usr/bin/konsole', 'usr/bin/kate',
                         'usr/share/arlinux/offline-distribution'}
    return common | {'usr/bin/thunar', 'usr/bin/mousepad'}


def validate_snapshot(snapshot: Path, distribution: str = "debian") -> None:
    """Reject incomplete or outdated package snapshots before compression."""
    required = required_snapshot_files(distribution)
    providers = {'mesa-libgallium', 'libgbm1', 'libgl1-mesa-dri', 'libglx-mesa0', 'libegl-mesa0'}
    seen, installed = set(), set()
    with tarfile.open(snapshot, 'r|') as source:
        for member in source:
            name = member.name.removeprefix('./').rstrip('/')
            if name == 'opt/OpenCode' or name.startswith('opt/OpenCode/'):
                raise ValueError('OpenCode must be installed on demand')
            seen.add(name)
            if name == 'usr/share/arlinux/offline-desktop':
                if source.extractfile(member).read() != b'1\n':
                    raise ValueError('Device preparation did not finish')
            elif name == 'usr/share/arlinux/offline-distribution':
                if source.extractfile(member).read().decode().strip() != distribution:
                    raise ValueError('Build snapshot belongs to a different distribution')
            elif name == 'usr/share/arlinux/packages.tsv' and distribution in ('arch', 'omarchy'):
                packages = dict(line.split('\t', 1) for line in source.extractfile(member).read().decode().splitlines())
                if 'arlinux' not in packages.get('mesa', ''):
                    raise ValueError('Build snapshot is missing the ARLinux Mesa package')
            elif name == 'var/lib/dpkg/status':
                for block in source.extractfile(member).read().decode().split('\n\n'):
                    fields = dict(line.split(': ', 1) for line in block.splitlines()
                                  if ': ' in line and not line.startswith(' '))
                    if (fields.get('Status') == 'install ok installed'
                            and '+arlinux.' in fields.get('Version', '')):
                        installed.add(fields.get('Package'))
    if not required <= seen:
        raise ValueError('Incomplete build snapshot: ' + ', '.join(sorted(required - seen)))
    if distribution in ('debian', 'yibu', 'plasma') and not providers <= installed:
        raise ValueError('Build snapshot is missing ARLinux Mesa packages: ' +
                         ', '.join(sorted(providers - installed)))


def seal(seed: Path, snapshot: Path, output: Path) -> None:
    with zipfile.ZipFile(seed) as archive:
        distribution = json.loads(archive.read('manifest.json'))['distributionId']
    validate_snapshot(snapshot, distribution)
    # Start with an unconfigured seed so no preparation entry point can ship.
    with zipfile.ZipFile(seed) as archive:
        if {'device-build', 'offline-desktop'} & set(archive.namelist()):
            raise ValueError('Seal against the original seed, not a preparation or offline ZIP')
        final_first_boot = archive.read('guest/first-boot.sh')
        # A prepared snapshot owns distro packages, not framework code. Keep
        # runtime entry points from this build's seed so reusing an offline
        # package snapshot cannot silently ship old Steam/Proton helpers.
        managed = {}
        wrappers = {'usr/local/bin/bwrap', 'usr/bin/arlinux-steam',
                    'usr/bin/arlinux-windows', 'usr/bin/arlinux-windows-app', 'usr/bin/arlinux-opencode'}
        seed_rootfs = subprocess.run(['zstd', '-dc'], input=archive.read('rootfs.tar.zst'),
                                    stdout=subprocess.PIPE, check=True)
        with tarfile.open(fileobj=io.BytesIO(seed_rootfs.stdout)) as tar:
            for member in tar:
                name = member.name.removeprefix('./').rstrip('/')
                if (not name.startswith('usr/lib/arlinux/') and name not in wrappers
                        and not name.startswith('usr/share/applications/arlinux-')
                        and not name.startswith('usr/share/pixmaps/arlinux-')
                        and name not in ('usr/share/dbus-1/services/org.arlinux.HostedInput.service',
                                         'usr/share/ibus/component/arlinux-hosted.xml',
                                         'usr/share/glib-2.0/schemas/90-arlinux-ibus.gschema.override')):
                    continue
                if member.isdir():
                    continue
                if distribution in ('arch', 'omarchy') and name.startswith('usr/lib/arlinux/mesa-packages/'):
                    continue
                if '..' in name.split('/') or name.startswith('/'):
                    raise ValueError('Unsafe runtime seed entry: ' + name)
                if not (member.isfile() or member.issym() or member.islnk()):
                    raise ValueError('Unsupported runtime seed entry: ' + name)
                data = tar.extractfile(member).read() if member.isfile() else None
                if name == 'usr/lib/arlinux/guest/first-boot.sh':
                    data = final_first_boot
                    member.size = len(data)
                managed[name] = (member, data)
        gpu_files = set()
        for overlay in ('gpu-qualcomm.tar.zst', 'gpu-generic.tar.zst'):
            result = subprocess.run(['zstd', '-dc'], input=archive.read(overlay),
                                    stdout=subprocess.PIPE, check=True)
            with tarfile.open(fileobj=io.BytesIO(result.stdout)) as tar:
                gpu_files.update(m.name.removeprefix('./') for m in tar if not m.isdir())
    schema_prefix = 'usr/share/glib-2.0/schemas/'
    refresh_schemas = schema_prefix + '90-arlinux-ibus.gschema.override' in managed
    dropped = {
        'etc/machine-id', 'etc/resolv.conf', 'var/lib/dbus/machine-id',
        'etc/pulse/client.conf.d/arlinux.conf', 'usr/bin/arlinux-app', 'usr/bin/sudo',
        'usr/share/applications/arlinux-app.desktop',
        'usr/share/arlinux/desktop-packages-installed',
    } | gpu_files | managed.keys()
    if refresh_schemas:
        dropped.add(schema_prefix + 'gschemas.compiled')
    prefixes = ('var/cache/', 'var/log/', 'var/tmp/', 'var/lib/apt/lists/',
                'var/run', 'var/lock', 'usr/lib/mesa/', 'usr/lib/hybris/',
                'usr/lib/arlinux/')
    allowed = {'etc', 'usr', 'opt', 'var', 'bin', 'sbin', 'lib', 'lib64'}
    seen = set()
    with tempfile.TemporaryDirectory(prefix='arlinux-seal-') as temp:
        compressed = Path(temp) / 'rootfs.tar.zst'
        schemas = Path(temp) / 'schemas'
        if refresh_schemas:
            schemas.mkdir()
        with compressed.open('wb') as dest:
            compressor = subprocess.Popen(['zstd', '-T4', '-19', '-c'], stdin=subprocess.PIPE, stdout=dest)
            try:
                with tarfile.open(snapshot, 'r|') as source, tarfile.open(fileobj=compressor.stdin, mode='w|') as target:
                    for member in source:
                        name = member.name.removeprefix('./').rstrip('/')
                        if '..' in name.split('/') or name.startswith('/'):
                            raise ValueError('Unsafe snapshot entry: ' + name)
                        if name == 'opt/OpenCode' or name.startswith('opt/OpenCode/'):
                            raise ValueError('OpenCode must be installed on demand, not exported in the offline desktop')
                        schema_data = None
                        if refresh_schemas and name.startswith(schema_prefix) and member.isfile() and name.endswith(('.xml', '.override')):
                            schema_data = source.extractfile(member).read()
                            (schemas / Path(name).name).write_bytes(schema_data)
                        if name.split('/')[0] not in allowed or name in dropped or name.startswith(prefixes):
                            continue
                        if omit_desktop_resource(name, member.isdir(), member.linkname if member.issym() else None):
                            continue
                        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                            continue
                        if member.issym() and member.linkname.startswith(('/data/', '/sdcard/')):
                            raise ValueError('Device-specific symlink: ' + name)
                        member.name = './' + name
                        member.uid = member.gid = member.mtime = 0
                        member.uname = member.gname = ''
                        member.pax_headers = {}
                        body = io.BytesIO(schema_data) if schema_data is not None else source.extractfile(member) if member.isfile() else None
                        if name in ('etc/passwd', 'etc/group', 'etc/passwd-', 'etc/group-'):
                            data = b''.join(line for line in body if not line.startswith(b'arlinux:'))
                            body = io.BytesIO(data)
                            member.size = len(data)
                        elif name == 'var/lib/dpkg/status':
                            data = body.read()
                            body = io.BytesIO(data)
                        elif name == 'usr/share/arlinux/offline-desktop':
                            if body.read() != b'1\n':
                                raise ValueError('Device preparation did not finish')
                            body = io.BytesIO(b'1\n')
                        target.addfile(member, body)
                        seen.add(name)
                    for name, (member, data) in sorted(managed.items()):
                        member.name = './' + name
                        member.uid = member.gid = member.mtime = 0
                        member.uname = member.gname = ''
                        member.pax_headers = {}
                        target.addfile(member, io.BytesIO(data) if data is not None else None)
                        seen.add(name)
                    if refresh_schemas:
                        # The package cache owns schema definitions, while this
                        # build owns overrides. Compile both together; a seed's
                        # compiled database may predate installed GUI packages.
                        for name, (member, data) in managed.items():
                            if name.startswith(schema_prefix) and member.isfile() and name.endswith(('.xml', '.override')):
                                (schemas / Path(name).name).write_bytes(data)
                        subprocess.run(['glib-compile-schemas', '--strict', str(schemas)], check=True)
                        data = (schemas / 'gschemas.compiled').read_bytes()
                        name = schema_prefix + 'gschemas.compiled'
                        member = tarfile.TarInfo('./' + name)
                        member.mode = 0o644
                        member.size = len(data)
                        target.addfile(member, io.BytesIO(data))
                        seen.add(name)
                    for name in ('etc/machine-id',):
                        member = tarfile.TarInfo('./' + name)
                        member.mode = 0o644
                        target.addfile(member, io.BytesIO())
                compressor.stdin.close()
                if compressor.wait() != 0:
                    raise RuntimeError('rootfs compression failed')
            finally:
                if compressor.poll() is None:
                    compressor.kill()
                    compressor.wait()
        required = required_snapshot_files(distribution) | {'usr/bin/arlinux-opencode'}
        if not required <= seen:
            raise ValueError('Incomplete package-cache desktop: ' + ', '.join(sorted(required - seen)))
        with compressed.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        rewrite(seed, output, {'rootfs.tar.zst': compressed,
                              'rootfs-seed-id': (digest + '\n').encode(),
                              'offline-desktop': b'1\n'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sealing = sub.add_parser('seal')
    sealing.add_argument('seed', type=Path)
    sealing.add_argument('snapshot', type=Path)
    sealing.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.command == 'seal':
        seal(args.seed, args.snapshot, args.output)
