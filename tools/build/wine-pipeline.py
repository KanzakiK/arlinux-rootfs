#!/usr/bin/env python3
"""Build and publish the independent Android Bionic Wine runtime artifacts."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_cache import Cache, digest, inventory, key, run, source_state, support_sources

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
        'wine-graphics': ('tools/build/wine-bionic-graphics.sh', 'third_party/mesa', 'third_party/libxshmfence', 'graphics-protocols'),
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
                     framework / 'graphics-protocols', framework / 'third_party/libxshmfence', out))
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



def build_bionic_deps(cache, framework, android, ndk):
    files = ['toolchain.json'] + ['tools/build/' + name for name in (
        'ndk-env.sh', 'ndk-wayland.sh', 'ndk-deps.sh', 'ndk-xcb.sh',
        'android-cross.ini.tpl', 'native.ini.tpl', 'stubs')]
    inputs = dict(recipe=inventory(framework / 'tools/build/bionic-deps.sh'),
                  sources={name: inventory(android / name) for name in files},
                  ndk=inventory(ndk / 'source.properties'),
                  compiler=inventory(ndk / 'toolchains/llvm/prebuilt/linux-x86_64/bin/clang'))
    out = cache.stage('bionic-deps', inputs, lambda out: run(
        'bash', framework / 'tools/build/bionic-deps.sh', android, ndk, out,
        cwd=framework, env=os.environ.copy()))
    return out / 'prefix'


def build_bionic_x11(cache, framework, ndk, base):
    source = framework / 'third_party/libX11'
    dirty = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'])
    if dirty:
        raise ValueError('libX11 must be a clean pinned fork checkout')
    inputs = dict(recipe=inventory(framework / 'tools/build/bionic-x11.sh'),
                  source=source_state(source), base=cache.records['bionic-deps'],
                  ndk=inventory(ndk / 'source.properties'))
    out = cache.stage('bionic-x11', inputs, lambda out: run(
        'bash', framework / 'tools/build/bionic-x11.sh', base, ndk, source, out,
        cwd=framework, env=os.environ.copy()))
    return out / 'prefix'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--android-repo', required=True, type=Path)
    parser.add_argument('--rebuild', action='store_true')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    framework = Path(config['framework']).resolve(strict=True)
    paths = {name: Path(config[name]).resolve(strict=True) for name in ('wineSource', 'mingw', 'ndk', 'addons')}
    if any(str(path).startswith('/mnt/') for path in paths.values()):
        raise ValueError('Wine build tools, vendor inputs and build trees must reside on the Linux filesystem')
    android = args.android_repo.resolve(strict=True)
    dirty = subprocess.check_output(['git', '-C', str(paths['wineSource']), 'status', '--porcelain', '--untracked-files=normal'])
    if dirty:
        raise ValueError('wineSource must be the pristine pinned checkout')
    root = framework / 'build/pipeline'
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.wine.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        cache = Cache(root, args.rebuild)
        base = build_bionic_deps(cache, framework, android, paths['ndk'])
        paths['bionicPrefix'] = build_bionic_x11(cache, framework, paths['ndk'], base)
        env = {name: value for name, value in os.environ.items() if name in (
            'PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
            'http_proxy', 'https_proxy', 'no_proxy', 'ARLINUX_WINDOWS_FONTS')}
        env.update(ANDROID_NDK_HOME=str(paths['ndk']), BIONIC_INCLUDE=str(paths['bionicPrefix'] / 'include'),
                   BIONIC_VULKAN_DRIVER='system', BIONIC_OPENGL='zink')
        toolchain = {str(p): inventory(p) for p in (
            paths['ndk'] / 'source.properties', paths['mingw'],
            paths['ndk'] / 'toolchains/llvm/prebuilt/linux-x86_64', paths['bionicPrefix'], paths['addons'])}
        common = dict(engine=digest(__file__), config=config, sources=source_state(framework),
                      wineSources=source_state(paths['wineSource']), toolchain=toolchain)
        common['hostTools'] = {name: subprocess.check_output([name, '--version'], text=True)
                               for name in ('gcc', 'g++', 'make', 'cmake', 'ninja', 'meson', 'pkg-config')}
        common['hostFreeType'] = subprocess.check_output(['pkg-config', '--modversion', 'freetype2'], text=True).strip()
        common['pulseRecipe'] = {str(p.relative_to(android)): inventory(p) for p in (
            android / 'tools/build/pulseaudio.sh', android / 'tools/build/ndk-env.sh',
            android / 'toolchain.json', android / 'runtime/pulseaudio')}
        invoke = lambda *command: run(*command, cwd=framework, env=env)
        archive = build_wine(cache, framework, android, paths, common, invoke, env)
        bridge = cache.stage('steamworks', dict(common, wine=cache.records['wine-bionic'],
            imports=cache.records['wine-pe']), lambda out: invoke('bash', 'tools/build/steamworks-bridge.sh',
                paths['wineSource'], paths['wineBuild'], paths['wineTools'], paths['mingw'], out))
        observer = cache.stage('windows-accessibility', common, lambda out: invoke(
            'bash', 'tools/build/windows-accessibility.sh', paths['mingw'], out))
        tray = None
        if (framework / 'tools/build/windows-tray.sh').is_file():
            tray = cache.stage('windows-tray', common, lambda out: invoke(
                'bash', 'tools/build/windows-tray.sh', paths['mingw'], out))
        def support(out):
            out.mkdir()
            shutil.copytree(bridge, out / 'steamworks')
            shutil.copyfile(observer / 'windows-accessibility.exe', out / 'windows-accessibility.exe')
            if tray is not None:
                shutil.copyfile(tray / 'windows-tray.exe', out / 'windows-tray.exe')
        support = cache.stage('runtime-support', dict(sources=support_sources(framework),
            dependencies={name: cache.records[name] for name in ('steamworks', 'windows-accessibility', 'windows-tray') if name in cache.records}), support)
        output = framework / 'build/artifacts/wine'
        output.mkdir(parents=True, exist_ok=True)
        target = output / 'arlinux-wine-bionic.tar.gz'
        shutil.copyfile(archive, target.with_suffix('.gz.part'))
        target.with_suffix('.gz.part').replace(target)
        target.with_name(target.name + '.sha256').write_text(digest(target) + '  ' + target.name + '\n')
        for source in list(archive.parent.glob('wine-source-*.tar.gz')) + list(archive.parent.glob('pe-*-source.tar.gz')):
            shutil.copyfile(source, output / source.name)
        record = dict(format=1, wineArchiveSha256=digest(target), support=str(support),
                      supportSources=support_sources(framework), stages=cache.records)
        pending = output / 'runtime.json.part'
        pending.write_text(json.dumps(record, indent=2) + '\n')
        pending.replace(output / 'runtime.json')
        print('Independent Wine runtime ready: ' + str(target), flush=True)


if __name__ == '__main__':
    main()
