#!/usr/bin/env python3
"""Build the optional native ARM64 Vulkan diagnostic product on its owning runner."""
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile

from pipeline_cache import Cache, digest, inventory, source_state


def run(*args):
    subprocess.run(list(map(str, args)), check=True)


def main():
    framework = Path(__file__).resolve().parents[2]
    source = framework/'third_party/gfxreconstruct'
    if os.environ.get('GITHUB_ACTIONS') != 'true' or platform.machine() not in ('aarch64', 'arm64'):
        raise RuntimeError('Capture compilation requires the ARM64 GitHub runner')
    inputs = dict(recipe=digest(__file__), source=source_state(source),
                  staging=inventory(framework/'third_party/libhybris/tools/capture_stage.py'),
                  packages=subprocess.check_output(['dpkg-query', '-W'], text=True),
                  compiler=subprocess.check_output(['c++', '--version'], text=True))
    cache = Cache(framework/'build/pipeline')

    def build(output):
        work = framework/'build/linux/vulkan-capture'
        install = work/'install'
        run('ccache', '--max-size', '2G')
        run('cmake', '-S', source, '-B', work/'build', '-G', 'Ninja',
            '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_WERROR=OFF',
            '-DGFXRECON_ENABLE_OPENXR=OFF', '-DGFXRECON_TOCPP_SUPPORT=OFF',
            '-DRUN_TESTS=OFF', '-DGFXRECON_INCLUDE_TEST_APPS=OFF',
            '-DCMAKE_C_COMPILER_LAUNCHER=ccache', '-DCMAKE_CXX_COMPILER_LAUNCHER=ccache',
            '-DCMAKE_INSTALL_PREFIX='+str(install))
        run('cmake', '--build', work/'build', '--parallel', '4')
        run('cmake', '--install', work/'build')
        runtime = install/'runtime'
        runtime.mkdir(exist_ok=True)
        for name in ('libz.so.1', 'liblz4.so.1', 'libzstd.so.1', 'libxxhash.so.0',
                     'libxcb-keysyms.so.1', 'libXrandr.so.2', 'libXrender.so.1', 'libXext.so.6'):
            shutil.copy2(Path('/usr/lib/aarch64-linux-gnu')/name, runtime/name)
        provenance = dict(inputs=inputs, files={str(p.relative_to(install)): digest(p)
                         for p in install.rglob('*') if p.is_file() and p.name != 'manifest.json'})
        (install/'manifest.json').write_text(json.dumps(provenance, indent=2)+'\n')
        output.mkdir()
        sys.path.insert(0, str(framework/'third_party/libhybris/tools'))
        from capture_stage import stage_tools
        metadata = {}
        stage_tools(install, output, metadata, digest)
        (output/'capture-tools/provenance.json').write_text(json.dumps(metadata, indent=2)+'\n')

    output = cache.stage('vulkan-capture', inputs, build)
    descriptor = framework/'build/artifacts/components/vulkan-capture.json'
    descriptor.parent.mkdir(parents=True, exist_ok=True)
    descriptor.write_text(json.dumps(dict(format=1, stage='vulkan-capture', output=str(output),
                                           records=cache.records), sort_keys=True)+'\n')
    product = framework/'build/artifacts/capture'
    product.mkdir(parents=True, exist_ok=True)
    archive = product/'capture.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as dest:
        for path in sorted((output/'capture-tools').rglob('*')):
            if path.is_file():
                info = zipfile.ZipInfo(path.relative_to(output).as_posix(), (1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (path.stat().st_mode & 0o777) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                dest.writestr(info, path.read_bytes())
    (product/'capture.json').write_text(json.dumps(dict(format=1, archiveSha256=digest(archive)), indent=2)+'\n')


if __name__ == '__main__':
    main()
