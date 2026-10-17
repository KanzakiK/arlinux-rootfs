#!/usr/bin/env python3
"""Build Wine, Steamworks and the offline desktop for the Windows APK entry."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(path):
    path = Path(path)
    if path.is_symlink():
        target = path.resolve(strict=False)
        return {'link': os.readlink(path), 'target': inventory(target) if target.exists() else None}
    if path.is_file():
        return {'sha256': digest(path), 'mode': path.stat().st_mode & 0o777}
    if not path.is_dir():
        raise FileNotFoundError(path)
    return {p.relative_to(path).as_posix(): inventory(p) for p in sorted(path.rglob('*'))
            if p.is_file() or p.is_symlink()}


def source_state(repo):
    """Include staged/unstaged/new sources and recursively inspect submodules."""
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args])
    # Prepared Wine sources may live beneath a checkout's ignored build/ tree;
    # git ls-files there would silently return an empty dependency set.
    top = subprocess.run(['git', '-C', str(repo), 'rev-parse', '--show-toplevel'],
                         capture_output=True, text=True)
    if top.returncode or Path(top.stdout.strip()).resolve() != repo.resolve():
        return inventory(repo)
    tracked = git('ls-files', '--stage', '-z').split(b'\0')
    state = {}
    for record in tracked:
        if not record:
            continue
        header, raw = record.split(b'\t', 1)
        name = os.fsdecode(raw)
        path = repo / name
        if header.startswith(b'160000 '):
            state[name] = source_state(path)
        else:
            state[name] = inventory(path) if path.exists() or path.is_symlink() else None
    for raw in git('ls-files', '--others', '--exclude-standard', '-z').split(b'\0'):
        if raw:
            name = os.fsdecode(raw)
            state[name] = inventory(repo / name)
    return state


def key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def build_references(output):
    # The Wine compiler tools and native ABI headers stay in the builder's work
    # tree. They are dependencies too, even though they are never distributed.
    references = {}
    for state in Path(output).rglob('build-state.json'):
        for name, path in json.loads(state.read_text()).items():
            references[str(path)] = inventory(Path(path))
    return references


class Cache:
    def __init__(self, root, rebuild=False):
        self.root, self.rebuild = Path(root), rebuild
        self.records = {}

    def stage(self, name, inputs, build):
        identity = key(inputs)
        destination = self.root / name / identity
        receipt = destination / 'receipt.json'
        if not self.rebuild and receipt.is_file():
            try:
                record = json.loads(receipt.read_text())
                output = destination / record['generation'] / 'output'
                if (record['inputs'] == identity and record['outputs'] == inventory(output)
                        and record['references'] == build_references(output)):
                    print('OK cached ' + name, flush=True)
                    self.records[name] = record
                    return output
            except (OSError, ValueError, KeyError):
                pass
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Keep successful generations at their original absolute paths. Configure,
        # pkg-config and Wine tools embed build paths, so moving a built tree breaks it.
        generation = 'generation-' + uuid.uuid4().hex
        pending = destination / generation
        pending.mkdir(parents=True)
        try:
            build(pending / 'output')
            record = {'inputs': identity, 'generation': generation,
                      'outputs': inventory(pending / 'output'),
                      'references': build_references(pending / 'output')}
            draft = destination / 'receipt.json.part'
            draft.write_text(json.dumps(record, sort_keys=True) + '\n')
            draft.replace(receipt)
        except BaseException:
            shutil.rmtree(pending)
            raise
        self.records[name] = record
        return pending / 'output'


def run(*args, cwd, env):
    print('> ' + ' '.join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, env=env, check=True)


def build_wine(cache, framework, android, paths, common, invoke, env):
    """Build the complete standalone Wine chain, including the Steamworks ABI inputs."""
    recipes = {
        'wine-pulse': (),
        'wine-pe': ('tools/build/wine-pe.sh', 'tools/build/refresh-wine-vkd3d.py',
                    'tools/build/prepare-wine-dcomp.sh', 'tools/patches'),
        'fex': ('tools/build/fex-windows.sh', 'third_party/proton'),
        'dxvk': ('tools/build/dxvk-windows.sh', 'tools/patches/dxvk-optional-pipeline-library.patch'),
        'wine-pe-package': ('tools/package-wine-pe.py', 'tools/wine_pe_debug.py'),
        'wine-tls': ('tools/build/wine-bionic-tls.sh',),
        'wine-graphics': ('tools/build/wine-bionic-graphics.sh', 'third_party/mesa', 'graphics-protocols'),
        'wine-vulkan': ('tools/build/bionic-vulkan.py', 'third_party/libhybris', 'third_party/android-headers', 'tools/patches'),
        'wine-bionic': ('tools/build/wine-bionic.sh', 'tools/package-wine-bionic.py', 'tools/build/refresh-wine-vkd3d.py',
                        'tools/build/prepare-wine-dcomp.sh', 'tools/build/prepare-wine-gamepad.py',
                        'native/winebus', 'tools/patches', 'tools/wine_pe_debug.py', 'tools/wine_fonts.py'),
    }
    def stage(name, command, dependencies=()):
        inputs = {k: v for k, v in common.items() if k not in ('sources', 'wineSources', 'pulseRecipe')}
        inputs['sources'] = {k: v for k, v in common['sources'].items()
                             if any(k == p or k.startswith(p + '/') for p in recipes[name])}
        if name == 'wine-bionic':
            import sys
            sys.path.insert(0, str(framework / 'tools'))
            from wine_fonts import FILES, source_directory
            inputs['windowsFonts'] = {n: inventory(source_directory()/n) for n in FILES}
        if name in ('wine-pe', 'wine-bionic'):
            inputs['wineSources'] = common['wineSources']
        if name == 'wine-pulse':
            inputs['pulseRecipe'] = common['pulseRecipe']
        inputs['dependencies'] = {n: cache.records[n] for n in dependencies}
        return cache.stage(name, inputs, command)

    def pulse(out):
        out.mkdir()
        env.update(ARLINUX_PULSE_WORK=str(out / 'work'), ARLINUX_PULSE_OUTPUT=str(out / 'android'))
        try:
            invoke('bash', android / 'tools/build/pulseaudio.sh', android, key(common))
        finally:
            env.pop('ARLINUX_PULSE_WORK', None)
            env.pop('ARLINUX_PULSE_OUTPUT', None)
    pulse = stage('wine-pulse', pulse)

    wine = stage('wine-pe', lambda out: invoke('bash', 'tools/build/wine-pe.sh',
                 paths['wineSource'], paths['mingw'], out))
    build_state = json.loads((wine / 'build-state.json').read_text())
    tools = Path(build_state['tools'])
    fex = stage('fex', lambda out: invoke('bash', 'tools/build/fex-windows.sh', paths['mingw'], out))
    dxvk = stage('dxvk', lambda out: invoke('bash', 'tools/build/dxvk-windows.sh', paths['mingw'], out))

    def package_pe(out):
        import tarfile
        out.mkdir()
        archive = out / 'pe.tar.gz'
        invoke('python3', 'tools/package-wine-pe.py', '--wine', wine, '--fex', fex,
               '--dxvk', dxvk, '--addons', paths['addons'], '--output', archive)
        runtime = out / 'runtime'
        runtime.mkdir()
        with tarfile.open(archive) as bundle:
            bundle.extractall(runtime, filter='data')
    pe = stage('wine-pe-package', package_pe, ('wine-pe', 'fex', 'dxvk')) / 'runtime'
    tls = stage('wine-tls', lambda out: invoke('bash', 'tools/build/wine-bionic-tls.sh', paths['ndk'], out))
    graphics = stage('wine-graphics', lambda out: invoke('bash', 'tools/build/wine-bionic-graphics.sh',
                     framework / 'third_party/mesa', paths['ndk'], paths['bionicPrefix'],
                     framework / 'graphics-protocols', out))
    adapter = stage('wine-vulkan', lambda out: invoke('python3', 'tools/build/bionic-vulkan.py',
                    '--source', framework / 'third_party/libhybris', '--headers', framework / 'third_party/android-headers',
                    '--ndk', paths['ndk'], '--native-prefix', paths['bionicPrefix'],
                    '--graphics-prefix', graphics / 'prefix', '--output', out), ('wine-graphics',))
    env.update(BIONIC_TLS_PREFIX=str(tls / 'prefix'), BIONIC_PULSE_PREFIX=str(pulse / 'work/prefix'),
               BIONIC_GRAPHICS_PREFIX=str(graphics / 'prefix'), BIONIC_DXVK_RUNTIME=str(dxvk),
               BIONIC_SYSTEM_VULKAN_ADAPTER=str(adapter / 'libvulkan_android_desktop.so'),
               BIONIC_VULKAN_DRIVER='system', BIONIC_OPENGL='zink')

    def native(out):
        out.mkdir()
        env['BIONIC_ARCHIVE'] = str(out / 'arlinux-wine-bionic.tar.gz')
        try:
            invoke('bash', 'tools/build/wine-bionic.sh', paths['wineSource'], tools,
                   paths['mingw'], paths['ndk'], paths['bionicPrefix'],
                   framework / 'third_party/proton/FEX', pe, out / 'runtime')
            for source in pe.parent.glob('pe-*-source.tar.gz'):
                shutil.copyfile(source, out / source.name)
        finally:
            env.pop('BIONIC_ARCHIVE', None)
    native = stage('wine-bionic', native, ('wine-pe', 'wine-pe-package', 'wine-tls', 'wine-pulse', 'wine-graphics', 'wine-vulkan'))
    native_state = json.loads((native / 'runtime/build-state.json').read_text())
    paths.update(wineSource=Path(native_state['source']), wineBuild=Path(native_state['core']),
                 wineTools=tools, wineImportLibs=wine / 'files/lib/wine')
    env['WINE_IMPORT_LIBS'] = str(paths['wineImportLibs'])
    return native / 'arlinux-wine-bionic.tar.gz'


def snapshot_key(framework):
    return key({str(p.relative_to(framework)): inventory(p) for p in (
        framework / 'distributions/yibu/rootfs.lock.json', framework / 'tools/device-desktop.py')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--rebuild', action='store_true')
    parser.add_argument('--android-repo', type=Path)
    parser.add_argument('--prepare', action='store_true', help='Build the disposable Builder input')
    parser.add_argument('--snapshot-status', action='store_true')
    parser.add_argument('--register-snapshot', action='store_true')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if config.get('format') != 1:
        raise ValueError('Unsupported desktop build configuration')
    framework = Path(config['framework']).resolve(strict=True)
    snapshot = Path(config['snapshot']).resolve()
    if args.snapshot_status:
        return 0 if (snapshot.is_file() and digest(snapshot) == config.get('snapshotSha256')
                     and config.get('snapshotPreparationKey') == snapshot_key(framework)) else 3
    if args.register_snapshot:
        config['snapshotSha256'] = digest(snapshot)
        config['snapshotPreparationKey'] = snapshot_key(framework)
        pending = args.config.with_suffix('.json.part')
        pending.write_text(json.dumps(config, indent=2) + '\n')
        pending.replace(args.config)
        return 0
    if not args.prepare and (not snapshot.is_file() or digest(snapshot) != config.get('snapshotSha256')
            or config.get('snapshotPreparationKey') != snapshot_key(framework)):
        raise ValueError('Package snapshot checksum differs from the configured build input')
    paths = {name: Path(config[name]).resolve(strict=True) for name in
             ('wineSource', 'mingw', 'ndk', 'bionicPrefix', 'addons')}
    android = args.android_repo.resolve(strict=True) if args.android_repo else Path(__file__).resolve().parents[2]
    # wine-pe uses git archive while the native backend copies the source tree.
    # Reject dirty inputs so both backends compile exactly the same pinned source.
    dirty = subprocess.check_output(['git', '-C', str(paths['wineSource']),
                                     'status', '--porcelain', '--untracked-files=normal'])
    if dirty:
        raise ValueError('wineSource must be the pristine pinned Wine checkout; keep ARLinux patches in tools/patches')
    for name in ('mono', 'gecko'):
        if not (paths['addons'] / name).is_dir():
            raise ValueError('Missing vendor addon directory: ' + str(paths['addons'] / name))
    env = {name: value for name, value in os.environ.items()
           if name in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'SSL_CERT_FILE',
                       'SSL_CERT_DIR', 'http_proxy', 'https_proxy', 'no_proxy')}
    env.update(ANDROID_NDK_HOME=str(paths['ndk']), BIONIC_INCLUDE=str(paths['bionicPrefix'] / 'include'),
               BIONIC_VULKAN_DRIVER='system', BIONIC_OPENGL='zink')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    (framework / 'build/pipeline').mkdir(parents=True, exist_ok=True)
    with (framework / 'build/pipeline/.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        cache = Cache(framework / 'build/pipeline', args.rebuild)
        state = source_state(framework)
        toolchain = {str(p): inventory(p) for p in (
            paths['ndk'] / 'source.properties', paths['mingw'],
            paths['ndk'] / 'toolchains/llvm/prebuilt/linux-x86_64',
            paths['bionicPrefix'], paths['addons'])}
        common = {'engine': digest(__file__), 'config': {k: v for k, v in config.items()
                  if k not in ('snapshot', 'snapshotSha256', 'snapshotPreparationKey')}, 'sources': state,
                  'wineSources': source_state(paths['wineSource']), 'toolchain': toolchain}
        common['hostTools'] = {command: subprocess.check_output([command, '--version'], text=True)
                               for command in ('gcc', 'g++', 'make', 'cmake', 'ninja', 'meson', 'pkg-config')}
        common['hostFreeType'] = subprocess.check_output(['pkg-config', '--modversion', 'freetype2'], text=True).strip()
        common['pulseRecipe'] = {str(p.relative_to(android)): inventory(p) for p in (
            android / 'tools/build/pulseaudio.sh', android / 'tools/build/ndk-env.sh',
            android / 'toolchain.json', android / 'runtime/pulseaudio')}
        invoke = lambda *command: run(*command, cwd=framework, env=env)
        wine_archive = build_wine(cache, framework, android, paths, common, invoke, env)
        bridge_inputs = dict(common, wine=cache.records['wine-bionic'],
                             imports=cache.records['wine-pe'])
        bridge = cache.stage('steamworks', bridge_inputs, lambda out: invoke(
            'bash', 'tools/build/steamworks-bridge.sh', paths['wineSource'],
            paths['wineBuild'], paths['wineTools'], paths['mingw'], out))
        # Explicit environment prevents a stale developer override selecting another payload.
        env['ARLINUX_STEAMWORKS_PAYLOAD'] = str(bridge)
        observer = cache.stage('windows-accessibility', common, lambda out: invoke(
            'bash', 'tools/build/windows-accessibility.sh', paths['mingw'], out))
        env['ARLINUX_WINDOWS_ACCESSIBILITY'] = str(observer / 'windows-accessibility.exe')
        def assets(out):
            # A miss means sources or verified output changed. Bypass the legacy
            # existence-only asset cache; immutable download caches remain usable.
            invoke('bash', 'tools/build/linux-assets.sh', '--rebuild', 'yibu')
            shutil.copytree(framework / 'distributions/yibu/build/assets', out, symlinks=True)
        asset_inputs = dict(common, dependencies={n: cache.records[n] for n in ('steamworks', 'windows-accessibility')})
        built_assets = cache.stage('linux-assets', asset_inputs, assets)
        target_assets = framework / 'distributions/yibu/build/assets'
        if target_assets.exists():
            shutil.rmtree(target_assets)
        shutil.copytree(built_assets, target_assets, symlinks=True)
        inputs = dict(common, dependencies=cache.records.copy(),
                      assets=inventory(framework / 'distributions/yibu/build/assets'),
                      transform=digest(android / 'tools/build/webview-store-bundle.py'))
        if not args.prepare:
            inputs['snapshot'] = digest(snapshot)
        inputs['preparation'] = args.prepare

        def desktop(out):
            out.mkdir()
            invoke('python3', 'tools/bundle.py', 'pack', 'distributions/yibu', out / 'seed.zip')
            if args.prepare:
                invoke('python3', 'tools/device-desktop.py', 'prepare', out / 'seed.zip', out / 'default.zip')
                (out / 'seed.zip').unlink()
                return
            invoke('python3', 'tools/device-desktop.py', 'seal', out / 'seed.zip', snapshot, out / 'offline.zip')
            invoke('python3', android / 'tools/build/webview-store-bundle.py',
                   out / 'offline.zip', out / 'default.zip')
            invoke('python3', android / 'tools/build/verify-webview-store-bundle.py', out / 'default.zip')
            (out / 'seed.zip').unlink()
            (out / 'offline.zip').unlink()

        result = cache.stage('prepare' if args.prepare else 'desktop', inputs, desktop)
        # Publish the selected local artifact atomically, after every stage succeeded.
        pending = args.output.with_suffix('.zip.part')
        shutil.copyfile(result / 'default.zip', pending)
        pending.replace(args.output)
        archive_output = args.output.parent / 'arlinux-wine-bionic.tar.gz'
        shutil.copyfile(wine_archive, archive_output.with_suffix('.gz.part'))
        archive_output.with_suffix('.gz.part').replace(archive_output)
        # Keep the complete license/source publication inputs next to the runtime.
        for source in list(wine_archive.parent.glob('wine-source-*.tar.gz')) + list(wine_archive.parent.glob('pe-*-source.tar.gz')):
            shutil.copyfile(source, args.output.parent / source.name)
        archive_output.with_name(archive_output.name + '.sha256').write_text(digest(archive_output) + '  ' + archive_output.name + '\n')
        receipt = {'format': 1, 'desktopSha256': digest(args.output),
                   'wineArchiveSha256': digest(archive_output),
                   'configSha256': digest(args.config), 'stages': cache.records}
        draft = args.output.with_suffix('.json.part')
        draft.write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
        draft.replace(args.output.with_suffix('.json'))
        print('Desktop ready: ' + str(args.output), flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
