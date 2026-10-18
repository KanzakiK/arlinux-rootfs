#!/usr/bin/env python3
"""Internal hosted-runner adapter; recipes remain behind build.sh."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request


ROOTFS = {'yibu', 'debian', 'arch', 'omarchy', 'plasma', 'lxqt'}
LINUX_GPU = {'linux-mesa', 'linux-hybris'}

def run(*args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, **kwargs)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def request():
    data = json.loads(os.environ['ARLINUX_COMPONENT_REQUEST'])
    framework = Path(__file__).resolve().parents[2]
    plan = json.loads((framework / 'tools/build/github-components.json').read_text())
    stage = plan['stages'].get(data.get('stage'))
    if not stage or os.environ.get('GITHUB_REPOSITORY') != stage['repository']:
        raise ValueError('Component must run in its owning repository')
    for name in ('framework', 'android'):
        if not re.fullmatch('[0-9a-f]{40}', data.get(name, '')):
            raise ValueError('Expected a pinned ' + name + ' commit')
    identity = data.pop('identity')
    actual = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    data['identity'] = identity
    if identity != actual:
        raise ValueError('Component request identity differs from its inputs')
    expected_arch = 'arm64' if stage['runner'].endswith('-arm') else 'x64'
    if os.environ.get('RUNNER_ARCH', '').lower() != expected_arch:
        raise ValueError('Unexpected hosted runner architecture')
    return data, framework


def download(url, output, expected):
    if not re.fullmatch('[0-9a-f]{64}', expected):
        raise ValueError('Download needs a pinned SHA-256')
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_file() and sha(output) == expected:
        return output
    temporary = output.with_suffix(output.suffix + '.part')
    with urllib.request.urlopen(url, timeout=120) as source, temporary.open('wb') as dest:
        shutil.copyfileobj(source, dest)
    if sha(temporary) != expected:
        raise ValueError('Download SHA-256 mismatch: ' + url)
    temporary.replace(output)
    return output


def prepare(data, framework):
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise RuntimeError('Hosted-runner bootstrap cannot run on a workstation')
    if data['stage'] == 'windows-fonts':
        root = framework.parent
        run(sys.executable, '-m', 'pip', 'install', 'zstandard==0.25.0')
    else:
        root = Path('/opt/arlinux')
        run('sudo', 'mkdir', '-p', root)
        run('sudo', 'chown', '-R', f'{os.getuid()}:{os.getgid()}', root)
        for name in ('framework', 'android'):
            shutil.move(str(framework.parent / name), root / name)
        framework = root / 'framework'
        # Only remove optional software on the ephemeral GitHub runner.
        # Never run this cleanup in a workstation or self-hosted environment.
        run('sudo', 'rm', '-rf', '/usr/share/dotnet', '/usr/local/lib/android',
            '/opt/ghc', '/usr/local/share/boost', '/opt/hostedtoolcache/CodeQL')
        packages = ['autoconf', 'automake', 'libtool', 'build-essential', 'bison', 'flex',
            'curl', 'git', 'cmake', 'ninja-build', 'patchelf', 'pkg-config', 'python3',
            'python3-venv', 'python3-pip', 'python3-mako', 'python3-zstandard',
            'debootstrap', 'qemu-user-static', 'binfmt-support', 'util-linux', 'zstd',
            'libarchive-tools', 'jq', 'gcc-aarch64-linux-gnu', 'g++-aarch64-linux-gnu',
            'glslang-tools', 'wayland-protocols', 'libfreetype-dev', 'libexpat1-dev',
            'libwayland-dev', 'libx11-dev', 'libx11-xcb-dev', 'libxcb1-dev',
            'libegl-dev', 'libgl-dev', 'libgles-dev', 'libglvnd-dev', 'libvulkan-dev',
            'libdrm-dev', 'libxrandr-dev', 'libxfixes-dev', 'libxshmfence-dev',
            'libxxf86vm-dev', 'libxcb-dri3-dev', 'libxcb-present-dev', 'libxcb-sync-dev',
            'ccache', 'gettext', 'libgettextpo-dev', 'libssl-dev', 'unzip', 'autopoint', 'intltool', 'python-is-python3']
        run('sudo', 'apt-get', 'update')
        run('sudo', 'apt-get', 'install', '-y', '--no-install-recommends', *packages,
            env=dict(os.environ, DEBIAN_FRONTEND='noninteractive'))
        run('python3', '-m', 'venv', root / 'python')
        run(root / 'python/bin/pip', 'install', 'meson==1.12.0', 'mako==1.3.10', 'zstandard==0.25.0')
        bin_dir = root / 'bin'
        bin_dir.mkdir(exist_ok=True)
        cross = bin_dir / 'aarch64-linux-gnu-pkg-config'
        cross.write_text('#!/bin/sh\nexport PKG_CONFIG_LIBDIR=/usr/lib/aarch64-linux-gnu/pkgconfig:/usr/share/pkgconfig\nexec pkg-config "$@"\n')
        cross.chmod(0o755)
        if data['stage'] in ROOTFS | LINUX_GPU:
            run('git', '-C', framework, 'submodule', 'update', '--init', '--depth', '1',
                'distributions/'+(data['stage'] if data['stage'] in ROOTFS else 'yibu'), 'third_party/mesa', 'third_party/libhybris', 'third_party/android-headers')
        else:
            run('git', '-C', framework, 'submodule', 'update', '--init', '--depth', '1')
            run('git', '-C', framework / 'third_party/proton', 'submodule', 'update', '--init', '--recursive', '--depth', '1', 'FEX')
        for marker in [framework/'.git', *framework.glob('third_party/*/.git'), *framework.glob('distributions/*/.git')]:
            if marker.exists():
                run('git', 'config', '--global', '--add', 'safe.directory', marker.parent)
        with Path(os.environ['GITHUB_PATH']).open('a') as out:
            out.write(str(root / 'python/bin')+'\n'+str(bin_dir)+'\n')
    with Path(os.environ['GITHUB_ENV']).open('a') as out:
        out.write('ARLINUX_FRAMEWORK='+framework.as_posix()+'\n')
        out.write('ARLINUX_WORKSPACE='+root.as_posix()+'\n')
    if data['stage'] != 'windows-fonts':
        paths = [str(root/'cache')]
        if data['stage'] in ROOTFS:
            paths.append(str(framework/'build'))
        else:
            paths.append(str(framework/'build/pipeline'/data['stage']))
            if data['stage'] in LINUX_GPU:
                paths.append(str(framework/'build/linux'))
            if data['stage'].startswith('wine-pe-'):
                paths.append(str(framework/'build/wine-pe/*/tools'))
                paths.append(str(framework/'build/wine-pe/*/source'))
            if data['stage'] == 'wine-bionic':
                paths.append(str(framework/'build/wine-bionic'))
        with Path(os.environ['GITHUB_OUTPUT']).open('a') as out:
            out.write('cache-paths<<ARLINUX_CACHE_PATHS\n'+'\n'.join(paths)+'\nARLINUX_CACHE_PATHS\n')


def toolchains(root, framework):
    lock = json.loads((framework / 'tools/build/github-inputs.json').read_text())
    cache = root / 'cache/downloads'
    tools = root / 'toolchains'
    tools.mkdir(exist_ok=True)
    for name in ('mingw', 'ndk'):
        item = lock[name]
        archive = download(item['url'], cache / item['file'], item['sha256'])
        destination = tools / name
        if not destination.exists():
            temporary = tools / (name+'-extract')
            temporary.mkdir(exist_ok=True)
            if archive.suffix == '.zip':
                run('unzip', '-q', archive, '-d', temporary)
            else:
                with tarfile.open(archive) as source:
                    source.extractall(temporary, filter='data')
            entries = list(temporary.iterdir())
            if len(entries) != 1 or not entries[0].is_dir():
                raise ValueError('Unexpected toolchain archive layout')
            entries[0].rename(destination)
            temporary.rmdir()
    addons = root / 'vendor/addons'
    for item in lock['addons']:
        archive = download(item['url'], cache / item['file'], item['sha256'])
        destination = addons / item['directory']
        destination.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive) as source:
            source.extractall(destination, filter='data')
    mono = addons / 'mono'
    alias = mono / 'wine-mono'
    if not alias.exists():
        alias.symlink_to('wine-mono-11.3.0')
    launcher = tools / 'mingw-ccache/bin'
    launcher.mkdir(parents=True, exist_ok=True)
    for compiler in (tools/'mingw/bin').iterdir():
        target = launcher/compiler.name
        if target.exists() or target.is_symlink():
            continue
        if 'clang' in compiler.name and compiler.is_file():
            target.write_text('#!/bin/sh\nexec ccache "'+str(compiler)+'" "$@"\n')
            target.chmod(0o755)
        else:
            target.symlink_to(compiler)
    run('ccache', '--max-size', '2G')
    return dict(format=1, framework=str(framework), wineSource=str(framework/'third_party/wine'),
        ndk=str(tools/'ndk'), mingw=str(launcher), addons=str(addons))


def import_dependency(root, dependency, visited=None):
    if visited is None:
        visited = set()
    if dependency['identity'] in visited:
        return
    visited.add(dependency['identity'])
    directory = root / 'incoming' / dependency['identity']
    directory.mkdir(parents=True, exist_ok=True)
    manifest = download(dependency['manifestUrl'], directory/'component.json', dependency['manifestSha256'])
    record = json.loads(manifest.read_text())
    if record['identity'] != dependency['identity']:
        raise ValueError('Dependency identity mismatch')
    for parent in record.get('dependencies', []):
        import_dependency(root, parent, visited)
    for part in record['parts']:
        download(part['url'], directory/part['name'], part['sha256'])
    archive = directory / 'capsule.tar.zst'
    with archive.open('wb') as dest:
        for part in record['parts']:
            with (directory/part['name']).open('rb') as source:
                shutil.copyfileobj(source, dest)
    if sha(archive) != record['archiveSha256']:
        raise ValueError('Reassembled component checksum mismatch')
    decoded = directory / 'capsule.tar'
    run('zstd', '-q', '-d', '-f', archive, '-o', decoded)
    def capsule_filter(member, destination):
        original_link = None
        if member.issym() and member.linkname.startswith('/'):
            target = Path(member.linkname)
            if not target.is_relative_to(root):
                raise ValueError('Component link escapes build workspace')
            original_link = member.linkname
            member = member.replace(linkname=os.path.relpath(target, root/Path(member.name).parent))
        filtered = tarfile.data_filter(member, destination)
        return filtered.replace(linkname=original_link) if original_link else filtered
    with tarfile.open(decoded) as source:
        # Capsules use paths relative to the one fixed build workspace.
        for member in source:
            if member.name.startswith('/') or '..' in Path(member.name).parts:
                raise ValueError('Unsafe component capsule path')
        source.extractall(root, filter=capsule_filter)
    decoded.unlink()


def build(data, framework):
    root = Path(os.environ['ARLINUX_WORKSPACE'])
    stage = data['stage']
    if stage == 'windows-fonts':
        output = root / 'vendor/fonts'
        output.mkdir(parents=True, exist_ok=True)
        for name in ('arial.ttf', 'arialbd.ttf', 'ariali.ttf', 'arialbi.ttf'):
            shutil.copyfile(Path(os.environ['WINDIR'])/'Fonts'/name, output/name)
        return
    visited = set()
    for dependency in data['dependencies']:
        import_dependency(root, dependency, visited)
    config = root / 'product.json'
    if stage in LINUX_GPU:
        env = dict(os.environ, ARLINUX_CACHE_DIR=str(root/'cache/rootfs'))
        run('bash', framework/'build.sh', 'gpu', '--component', stage.removeprefix('linux-'), env=env)
    elif stage in ROOTFS:
        config.write_text(json.dumps(dict(format=1, framework=str(framework))))
        output = framework / ('build/artifacts/rootfs/'+stage+'/default.zip')
        run('sudo', '-E', 'env', 'PATH='+os.environ['PATH'], 'HOME='+os.environ['HOME'],
            'ARLINUX_CACHE_DIR='+str(root/'cache/rootfs'),
            'ARLINUX_REQUIRE_GPU_CACHE=1',
            'bash', framework/'build.sh', 'rootfs', '--config', config,
            '--android-repo', root/'android', '--distribution', stage, '--output', output)
    else:
        config.write_text(json.dumps(toolchains(root, framework)))
        env = dict(os.environ, ARLINUX_WINDOWS_FONTS=str(root/'vendor/fonts'), JOBS='4',
            CCACHE_DIR=str(root/'cache/ccache'), CCACHE_BASEDIR=str(framework))
        run('bash', framework/'build.sh', 'wine', '--config', config,
            '--android-repo', root/'android', '--target', stage, '--require-dependencies', env=env)


def publish(data, framework):
    root = Path(os.environ['ARLINUX_WORKSPACE'])
    stage = data['stage']
    output = root / 'export'
    output.mkdir(exist_ok=True)
    record = dict(data)
    paths = []
    if stage == 'windows-fonts':
        paths = [root/'vendor/fonts']
    elif stage in ROOTFS:
        paths = [framework/('build/artifacts/rootfs/'+stage)]
    else:
        sys.path.insert(0, str(framework/'tools/build'))
        from pipeline_cache import inventory, build_references
        descriptor = json.loads((framework/'build/artifacts/components'/f'{stage}.json').read_text())
        state = descriptor['records'][stage]
        path = Path(descriptor['output'])
        if inventory(path) != state['outputs'] or build_references(path) != state['references']:
            raise ValueError('Component output differs from its build-cache receipt')
        paths = [path.parent, path.parent.parent/'receipt.json',
                 *(Path(name) for name in state['references'])]
        if stage == 'wine-product':
            # Consumers need distributable archives, not the native compiler work tree.
            final = framework/'build/artifacts/wine'
            final.mkdir(parents=True, exist_ok=True)
            for source in path.iterdir():
                if source.is_file():
                    shutil.copyfile(source, final/source.name)
            paths = [final]
    archive = output / 'capsule.tar'
    # Compiler tools can point at generated source/header trees outside the
    # output directory. Preserve those references at the same absolute path.
    # Toolchains, pinned checkouts and declared pipeline dependencies are
    # provisioned separately and must not be duplicated into every capsule.
    position = 0
    while position < len(paths):
        path = paths[position]
        position += 1
        for link in ([path] if path.is_symlink() else path.rglob('*') if path.is_dir() else []):
            if not link.is_symlink():
                continue
            target = link.resolve(strict=True)
            if not target.is_relative_to(root):
                raise ValueError('Build reference is outside the component workspace')
            if any(target == parent or target.is_relative_to(parent) for parent in paths):
                continue
            if any(target.is_relative_to(parent) for parent in (
                    root/'toolchains', framework/'third_party', framework/'build/pipeline')):
                continue
            paths.append(target)
    with tarfile.open(archive, 'w') as target:
        seen = set()
        for path in paths:
            relative = path.resolve().relative_to(root.resolve())
            if relative in seen:
                continue
            seen.add(relative)
            target.add(path, arcname=relative.as_posix())
    compressed = archive.with_suffix('.tar.zst')
    import zstandard
    with archive.open('rb') as source, compressed.open('wb') as dest:
        with zstandard.ZstdCompressor(level=3, threads=4).stream_writer(dest) as writer:
            shutil.copyfileobj(source, writer)
    archive.unlink()
    record['archiveSha256'] = sha(compressed)
    tag = 'arlinux-'+stage+'-'+data['identity'][:24]
    repository = os.environ['GITHUB_REPOSITORY']
    record['parts'] = []
    with compressed.open('rb') as source:
        while block := source.read(1024*1024*1024):
            name = f'capsule-{len(record["parts"]):03d}.zst.part'
            part = output/name
            part.write_bytes(block)
            record['parts'].append(dict(name=name, sha256=sha(part),
                url=f'https://github.com/{repository}/releases/download/{tag}/{name}'))
    manifest = output/'component.json'
    manifest.write_text(json.dumps(record,sort_keys=True,indent=2)+'\n')
    # Component releases are immutable build inputs. Never touch application
    # releases, Wine latest, or a moving download manifest here.
    existing = subprocess.run(['gh','api',f'repos/{repository}/releases/tags/{tag}'],
                              capture_output=True,text=True)
    if existing.returncode:
        run('gh','release','create',tag,'--repo',repository,'--prerelease','--title',tag,
            '--notes','Verified ARLinux build component; not an application release.')
        assets = {}
    else:
        assets = {asset['name']:asset for asset in json.loads(existing.stdout)['assets']}
    # Upload the manifest last as the completion marker. An interrupted upload
    # can resume, but an already published asset must never change silently.
    for file in [*(output/part['name'] for part in record['parts']), manifest]:
        if file.name in assets:
            if assets[file.name].get('digest') != 'sha256:'+sha(file):
                raise ValueError('Immutable component release conflicts with rebuilt output: '+file.name)
        else:
            run('gh','release','upload',tag,'--repo',repository,file)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare','build','publish'))
    args = parser.parse_args()
    data, framework = request()
    globals()[args.action](data, framework)
