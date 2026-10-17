#!/usr/bin/env python3
"""Assemble an experimental Bionic backend with matching Wine/FEX PE modules."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
from wine_pe_debug import optimize

SYSTEM_LIBS = {'libc.so', 'libm.so', 'libdl.so', 'libz.so', 'liblog.so', 'libandroid.so', 'libnativewindow.so'}


def verify_zink(prefix):
    stamp = prefix / 'arlinux-bionic-graphics.json'
    if not stamp.is_file():
        raise RuntimeError('Rebuild graphics with tools/build/wine-bionic-graphics.sh; missing Zink build record')
    record = json.loads(stamp.read_text())
    if (record.get('protocol'), record.get('openglDriver'), record.get('xmlconfig')) != (1, 'zink', 'enabled'):
        raise RuntimeError('Zink must be built with xmlconfig=enabled for Wine initialization')
    for name in ['lib/dri/zink_dri.so', 'lib/dri/libdril_dri.so']:
        with (prefix / name).open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != record.get('libraries', {}).get(name):
            raise RuntimeError('Zink build record does not match installed library: ' + name)
    return record


def verify_components(pe_runtime):
    """Reject PE inputs that silently omit required source-built components."""
    records = {}
    for name in ('arlinux-dcomp.json', 'arlinux-vkd3d.json'):
        path = pe_runtime / name
        if not path.is_file():
            raise RuntimeError('Rebuild Wine PE modules; missing required component record: ' + name)
        records[name] = json.loads(path.read_text())
    patch = Path(__file__).parent / 'patches/wine-dcomp-content-lifetime.patch'
    dcomp = records['arlinux-dcomp.json']
    if (dcomp.get('commit') != '318eda0d8fa08ee94faadf6dc5ad85870339b327' or
            dcomp.get('patchSHA256') != hashlib.sha256(patch.read_bytes()).hexdigest()):
        raise RuntimeError('Rebuild Wine PE modules with the current DirectComposition fixes')
    expected = json.loads((Path(__file__).parent / 'patches/wine-staging-vkd3d/manifest.json').read_text())
    if records['arlinux-vkd3d.json'] != expected:
        raise RuntimeError('Rebuild Wine PE modules with the current VKD3D refresh')
    for arch in ('aarch64', 'i386', 'x86_64'):
        for dll in ('dcomp', 'd3d12', 'd3d12core'):
            if not (pe_runtime / 'files/lib/wine' / (arch + '-windows') / (dll + '.dll')).is_file():
                raise RuntimeError('Missing required Wine PE module: ' + arch + '/' + dll)
    for arch in ('aarch64', 'i386', 'x86_64'):
        for driver in ('winex11.drv',):
            if not (pe_runtime / 'files/lib/wine' / (arch + '-windows') / driver).is_file():
                raise RuntimeError('Missing required Wine PE driver: ' + arch + '/' + driver)
    data = pe_runtime / 'files/share/wine'
    if not (data / 'wine.inf').is_file() or not any((data / 'fonts').glob('*.ttf')):
        raise RuntimeError('Missing required Wine registry template or fonts')
    return records


def archive_runtime(root, archive):
    if archive.exists() or archive.with_name(archive.name + '.sha256').exists():
        raise FileExistsError('Runtime archive already exists: ' + str(archive))
    if archive.resolve().is_relative_to(root.resolve()):
        raise ValueError('Archive must be outside the runtime directory')
    metadata = json.loads((root / 'bionic-runtime.json').read_text())
    for name, expected in metadata['files'].items():
        with (root / name).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                raise RuntimeError('Runtime checksum mismatch before compression: ' + name)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='wine-archive-', dir=archive.parent) as temp:
        temporary = Path(temp) / 'runtime.tar.gz'
        with temporary.open('wb') as output, gzip.GzipFile(filename='', mode='wb', fileobj=output,
                                                         compresslevel=1, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|') as bundle:
                for path in sorted(root.rglob('*')):
                    entry = bundle.gettarinfo(str(path), path.relative_to(root).as_posix())
                    entry.uid = entry.gid = entry.mtime = 0
                    entry.uname = entry.gname = ''
                    if entry.isfile():
                        with path.open('rb') as source:
                            bundle.addfile(entry, source)
                    else:
                        bundle.addfile(entry)
        with temporary.open('rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        temporary.rename(archive)
    archive.with_name(archive.name + '.sha256').write_text(checksum + '  ' + archive.name + '\n')
    return checksum


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['core', 'fex', 'native-prefix', 'ndk', 'pe-runtime', 'output']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--dependency-prefix', type=Path, action='append', default=[])
    parser.add_argument('--graphics-prefix', type=Path)
    parser.add_argument('--dxvk-runtime', type=Path,
                        help='DXVK build with optional KHR_pipeline_library, containing ARCH-windows directories')
    parser.add_argument('--vulkan-driver', choices=['system', 'turnip', 'none'], default='system')
    parser.add_argument('--system-vulkan-adapter', type=Path,
                        help='Bionic libvulkan_android_desktop.so from tools/build/bionic-vulkan.py')
    parser.add_argument('--archive', type=Path, help='Also create a deterministic tar.gz and SHA-256 sidecar')
    parser.add_argument('--wine-source-archive', type=Path,
                        help='Source archive produced by wine-pe.sh; defaults to PE runtime/wine-source.tar.gz')
    args = parser.parse_args()
    if args.archive and (args.archive.exists() or args.archive.resolve().is_relative_to(args.output.resolve())):
        parser.error('Archive must be a new file outside the runtime output directory')
    if args.vulkan_driver == 'system' and (not args.system_vulkan_adapter or not args.system_vulkan_adapter.is_file()):
        parser.error('System Vulkan requires --system-vulkan-adapter; build the native desktop WSI first')
    if args.vulkan_driver == 'system' and not args.dxvk_runtime:
        parser.error('System Vulkan requires --dxvk-runtime from tools/build/bionic-dxvk.sh')
    compat_layer = args.system_vulkan_adapter.with_name('libVkLayer_hybris_compat.so') if args.vulkan_driver == 'system' else None
    if compat_layer and (not compat_layer.is_file() or not compat_layer.with_name('VkLayer_hybris_compat.json').is_file()):
        parser.error('Build the system adapter and its matching Bionic hybris compatibility layer together')
    if args.vulkan_driver != 'none' and not args.graphics_prefix:
        parser.error('A graphics prefix containing the desktop Vulkan loader is required')
    config_header = (args.core / 'include/config.h').read_text()
    if args.vulkan_driver != 'none' and not re.search(r'^#define SONAME_LIBVULKAN ', config_header, re.MULTILINE):
        parser.error('Selected Vulkan backend requires a Wine build with SONAME_LIBVULKAN enabled')
    opengl = bool(re.search(r'^#define SONAME_LIBGL ', config_header, re.MULTILINE))
    graphics_record = None
    if opengl:
        if not args.graphics_prefix:
            parser.error('OpenGL requires a graphics prefix with Zink')
        graphics_record = verify_zink(args.graphics_prefix)
    components = verify_components(args.pe_runtime)
    original = json.loads((args.pe_runtime / 'arlinux-runtime.json').read_text())
    wine_commit = '46af030d975f331ff6304a34a6b91c6147285c6d'
    if original['wine_commit'] != wine_commit or \
            original['fex_commit'] != '82510eb452b258959ef982be58a9c3c1bafc82a4':
        raise RuntimeError('Expected the matching packaged Wine and FEX PE modules')
    source_archive = args.wine_source_archive or (args.pe_runtime / 'wine-source.tar.gz')
    if not source_archive.is_file():
        raise RuntimeError('Missing reproducibility source archive: ' + str(source_archive))
    source_commit_file = args.pe_runtime / 'wine-commit'
    if source_commit_file.is_file() and source_commit_file.read_text().strip() != wine_commit:
        raise RuntimeError('Wine source archive commit does not match the packaged PE runtime')
    with source_archive.open('rb') as stream:
        source_archive_sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
    source_asset = 'wine-source-' + source_archive_sha256 + '.tar.gz'
    source_url = ('https://github.com/taowen/wine/releases/download/arlinux-wine-source-' +
                  source_archive_sha256 + '/' + source_asset)
    for name in ['libarm64ecfex.dll', 'libwow64fex.dll']:
        if not (args.pe_runtime / 'files/lib/wine/aarch64-windows' / name).is_file():
            raise RuntimeError('Missing Windows CPU module: ' + name)
    source_target = args.output.parent / source_asset
    if source_target.exists():
        if hashlib.sha256(source_target.read_bytes()).hexdigest() != source_archive_sha256:
            raise RuntimeError('Existing source asset has different contents')
    elif source_archive.resolve() != source_target.resolve():
        shutil.copyfile(source_archive, source_target)
    args.output.mkdir(parents=True, exist_ok=False)
    source = args.pe_runtime / 'files'
    destination = args.output / 'files'

    def ignore(directory, names):
        path = Path(directory)
        if path == source / 'lib/wine':
            return ['aarch64-unix']
        if path == source / 'bin':
            return [name for name in names if name in {'wine', 'wine64', 'wineserver', 'wine-preloader', 'wine64-preloader'}]
        return []

    shutil.copytree(source, destination, symlinks=True, ignore=ignore)
    # Keep the HID driver's private Unix ABI paired with the native backend.
    for arch in ('aarch64', 'i386', 'x86_64'):
        driver = args.core / 'dlls/winebus.sys' / (arch + '-windows/winebus.sys')
        target = destination / 'lib/wine' / (arch + '-windows/winebus.sys')
        if target.is_symlink():
            target.unlink()
        shutil.copyfile(driver, target)
    dcomp_record = components['arlinux-dcomp.json']
    configuration = destination / 'etc/dxvk.conf'
    configuration.parent.mkdir(parents=True, exist_ok=True)
    configuration.write_text('[msedgewebview2.exe]\n'
                             'dxgi.enableDummyCompositionSwapchain = True\n')
    if args.dxvk_runtime:
        for arch in ['aarch64', 'x86_64', 'i386']:
            target = destination / 'lib/wine/dxvk' / (arch + '-windows')
            target.mkdir(parents=True, exist_ok=True)
            for name in ['dxgi', 'd3d8', 'd3d9', 'd3d10core', 'd3d11']:
                src = args.dxvk_runtime / (arch + '-windows') / (name + '.dll')
                if not src.is_file():
                    raise RuntimeError('Missing DXVK module: ' + str(src))
                dst = target / src.name
                if dst.is_symlink():
                    dst.unlink()
                shutil.copyfile(src, dst)
    unix = destination / 'lib/wine/aarch64-unix'
    unix.mkdir(parents=True)
    readelf = args.ndk / 'bin/llvm-readelf'
    strip = args.ndk / 'bin/llvm-strip'
    # These are opened by Wine at runtime rather than linked as DT_NEEDED.
    pending = re.findall(r'^#define SONAME_LIB(?:FONTCONFIG|FREETYPE|GNUTLS|VULKAN|GL|EGL|GLESV2|X[A-Z0-9_]+) "([^"]+)"',
                         config_header, re.MULTILINE)
    # Ship Turnip alongside the system driver so Adreno can use modern Vulkan.
    turnip = args.vulkan_driver != 'none'
    if turnip:
        pending.append('libvulkan_freedreno.so')
    prefixes = [args.native_prefix, *args.dependency_prefix]
    if args.graphics_prefix:
        prefixes.append(args.graphics_prefix)
    hashes = {}

    def install(src, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise RuntimeError('Duplicate native binary: ' + str(target))
        shutil.copyfile(src, target)
        target.chmod(0o755)
        subprocess.run([str(strip), '--strip-debug', str(target)], check=True)
        header = subprocess.check_output([str(readelf), '-h', str(target)], text=True)
        if 'AArch64' not in header:
            raise RuntimeError('Expected an ARM64 native binary: ' + str(target))
        dynamic = subprocess.check_output([str(readelf), '-d', str(target)], text=True)
        pending.extend(re.findall(r'\(NEEDED\).*\[([^]]+)\]', dynamic))

    install(args.core / 'loader/wine', unix / 'wine')
    install(args.core / 'server/wineserver', destination / 'bin/wineserver')
    for src in sorted((args.core / 'dlls').glob('*/*.so')):
        install(src, unix / src.name)
    for name in ['libarm64ecfex.so', 'libwow64fex.so']:
        install(args.fex / name, unix / name)
    if args.vulkan_driver == 'system':
        install(args.system_vulkan_adapter, unix / 'libvulkan_android_desktop.so')
        install(compat_layer, unix / compat_layer.name)
    if opengl:
        dri = destination / 'lib/dri'
        dri.mkdir(parents=True, exist_ok=True)
        for name in ['zink_dri.so', 'libdril_dri.so']:
            src = args.graphics_prefix / 'lib/dri' / name
            if not src.is_file():
                raise RuntimeError('Missing Zink DRI module: ' + str(src))
            install(src.resolve(), dri / name)
    while pending:
        name = pending.pop()
        if name in SYSTEM_LIBS or (unix / name).exists():
            continue
        libraries = [prefix / subdir / name for prefix in prefixes
                     for subdir in ['lib', 'lib/pulseaudio', 'lib/aarch64-linux-gnu']]
        library = next((path for path in libraries if path.is_file()), None)
        if library is None:
            raise RuntimeError('Missing Bionic dependency: ' + name)
        install(library.resolve(), unix / name)
    loader = subprocess.check_output([str(readelf), '-l', str(unix / 'wine')], text=True)
    if '/system/bin/linker64' not in loader:
        raise RuntimeError('Wine loader does not use the Android linker')
    (destination / 'bin/wine').symlink_to('../lib/wine/aarch64-unix/wine')
    config = destination / 'etc/fonts/fonts.conf'
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
                      '<fontconfig><dir>/system/fonts</dir><cachedir prefix="xdg">fontconfig</cachedir></fontconfig>\n')
    drivers = [] if args.vulkan_driver == 'none' else [args.vulkan_driver]
    if turnip and 'turnip' not in drivers:
        drivers.append('turnip')
    for backend in drivers:
        icd = destination / ('share/vulkan/icd.d/' + backend + '_icd.aarch64.json')
        icd.parent.mkdir(parents=True, exist_ok=True)
        if backend == 'system':
            driver = {'file_format_version': '1.0.0', 'ICD': {'api_version': '1.3.0',
                      'library_path': '../../../lib/wine/aarch64-unix/libvulkan_android_desktop.so'}}
        else:
            original_icd = next((args.graphics_prefix / 'share/vulkan/icd.d').glob('*freedreno*.json'))
            driver = json.loads(original_icd.read_text())
            driver['ICD']['library_path'] = '../../../lib/wine/aarch64-unix/libvulkan_freedreno.so'
        icd.write_text(json.dumps(driver, indent=2) + '\n')
    if compat_layer:
        manifest = json.loads(compat_layer.with_name('VkLayer_hybris_compat.json').read_text())
        manifest['layer']['library_path'] = '../../../lib/wine/aarch64-unix/' + compat_layer.name
        target = destination / 'share/vulkan/explicit_layer.d/VkLayer_hybris_compat.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(manifest, indent=2) + '\n')
    # Ship the LGPL-derived backend and its source preparation alongside Wine.
    gamepad_sources = Path(__file__).resolve().parents[1]
    gamepad_destination = destination / 'share/arlinux/winebus'
    gamepad_destination.mkdir(parents=True, exist_ok=True)
    for name in ('bus_arlinux.h', 'README.md'):
        shutil.copyfile(gamepad_sources / 'native/winebus' / name, gamepad_destination / name)
    shutil.copyfile(gamepad_sources / 'tools/build/prepare-wine-gamepad.py',
                    gamepad_destination / 'prepare-wine-gamepad.py')
    shutil.copyfile(gamepad_sources / 'third_party/wine/COPYING.LIB', gamepad_destination / 'COPYING.LIB')
    packaging = optimize(args.output, strip)
    for path in sorted(destination.rglob('*')):
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as stream:
                hashes[path.relative_to(args.output).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
    metadata = dict(protocol=1, libc='bionic', experimental=True, wine='11.19',
                    wineCommit=wine_commit,
                    wineSource=dict(repository='https://github.com/taowen/wine',
                                    commit=wine_commit, archiveURL=source_url,
                                    archiveName=source_asset,
                                    archiveSHA256=source_archive_sha256),
                    fexCommit='82510eb452b258959ef982be58a9c3c1bafc82a4',
                    originalSources=original['sources'], packaging=packaging, vulkanDriver=args.vulkan_driver,
                    vulkanCompat='hybris' if compat_layer else 'none',
                    openglDriver='zink' if opengl else 'none',
                    graphicsBuild=graphics_record,
                    backends=dict(gamepad=True, vulkan=(unix / 'winevulkan.so').exists(),
                                  opengl=opengl,
                                  audio=(unix / 'winepulse.so').exists(),
                                  tls=bool(list(unix.glob('libgnutls.so*')))),
                    limitations=([] if opengl else ['No OpenGL backend']) + ([] if args.vulkan_driver != 'none' else
                                 ['Vulkan driver not packaged']), files=hashes)
    if dcomp_record:
        metadata['directComposition'] = dcomp_record
    vkd3d_record = args.pe_runtime / 'arlinux-vkd3d.json'
    if vkd3d_record.is_file():
        metadata['vkd3d'] = json.loads(vkd3d_record.read_text())
        shutil.copyfile(vkd3d_record, args.output / 'arlinux-vkd3d.json')
    (args.output / 'bionic-runtime.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print('Packaged Bionic Wine:', len(hashes), 'files')
    if args.archive:
        print('Runtime archive SHA-256:', archive_runtime(args.output, args.archive))


if __name__ == '__main__':
    main()
