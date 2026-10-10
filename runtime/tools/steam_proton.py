"""Apply an exact-version Proton core pack without modifying Valve's depot.

The shadow-tree approach follows DroidDeck's version-matched core packs. Steam
still supplies Proton, FEX, the Windows DLLs and game startup. This tool does not
provide pressure-vessel's namespace isolation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

CORE = ('files/lib/wine/aarch64-unix/ntdll.so', 'files/bin-arm64/wineserver')
# Wine locates its Unix modules relative to its executable; these cannot be
# symlinks back into the unmodified depot.
LOADERS = ('files/bin-arm64/wine', 'files/lib/wine/aarch64-unix/wine',
           'files/lib/wine/aarch64-unix/wine-preloader')
OWN = {'toolmanifest.vdf', 'compatibilitytool.vdf', 'arlinux-pack.json', 'run'}
PACKS = Path('/usr/lib/arlinux/proton-core')


def configure(steam):
    """Register matching bundled packs before Steam scans compatibility tools.

    Steam still owns depot installation and the user's compatibility selection.
    Never change config.vdf or substitute an unmatched Wine version.
    """
    from steam_fex import app_directory, IncompleteRuntime
    try:
        stock = app_directory(steam, '4628740')
    except IncompleteRuntime:
        print('Windows games: install Proton 11.0 (ARM64) in Steam, then restart Steam.', flush=True)
        return
    version = (stock/'version').read_text().strip()
    for manifest in sorted(PACKS.glob('*/pack.json')):
        if json.loads(manifest.read_text()).get('version') == version:
            register(stock, manifest.parent, steam/'compatibilitytools.d/arlinux-proton-arm64')
            return
    print(f'Windows games: no matching Android core pack for {version}. '
          'Update ARLinux before using this Proton version.', flush=True)


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def validate(stock, pack):
    data = json.loads((pack/'pack.json').read_text())
    if data.get('format') != 1 or set(data.get('stock', {})) != set(CORE) or set(data.get('files', {})) != set(CORE):
        raise RuntimeError('Invalid Proton core pack')
    if (stock/'version').read_text().strip() != data['version']:
        raise RuntimeError('This core pack does not match the installed Proton version')
    for name in CORE:
        if digest(stock/name) != data['stock'][name]:
            raise RuntimeError(f'Proton changed: refusing mismatched core pack ({name})')
        if digest(pack/name) != data['files'][name]:
            raise RuntimeError(f'Damaged Proton core pack: {name}')
    return data


def register(stock, pack, tool):
    stock, pack, tool = stock.resolve(), pack.resolve(), tool.absolute()
    data = validate(stock, pack)
    record = {'stock': str(stock), 'pack': str(pack), 'manifest': data}
    if tool.exists() or tool.is_symlink():
        marker = tool/'arlinux-pack.json'
        previous = json.loads(marker.read_text()) if marker.is_file() else {}
        if previous.get('stock') != str(stock) or previous.get('manifest') != data:
            raise RuntimeError(f'Preserving existing compatibility tool: {tool}')
        verify_tree(stock, tool, data)
        if previous != record:
            temporary = marker.with_suffix('.tmp')
            temporary.write_text(json.dumps(record, indent=2)+'\n')
            temporary.replace(marker)
        return
    tool.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.proton-core-', dir=tool.parent) as temporary:
        stage = Path(temporary)/'tool'
        stage.mkdir()
        copies = set(CORE) | {p for p in LOADERS if (stock/p).is_file()}
        real_dirs = {str(parent) for name in copies for parent in Path(name).parents}

        def populate(relative):
            for entry in (stock/relative).iterdir():
                name = (Path(relative)/entry.name).as_posix()
                target = stage/name
                if relative == '.' and entry.name in OWN:
                    continue
                if name in real_dirs:
                    target.mkdir()
                    populate(name)
                elif name in copies:
                    shutil.copy2((pack if name in CORE else stock)/name, target)
                else:
                    target.symlink_to(entry)
        populate('.')
        (stage/'arlinux-pack.json').write_text(json.dumps(record, indent=2)+'\n')
        (stage/'run').write_text('#!/bin/sh\nexec python3 /usr/lib/arlinux/steam_proton.py run "$(dirname "$0")" "$@"\n')
        (stage/'run').chmod(0o755)
        (stage/'toolmanifest.vdf').write_text('''"manifest"
{
    "version" "2"
    "commandline" "/run %verb%"
    "use_sessions" "1"
    "compatmanager_layer_name" "proton"
}
''')
        (stage/'compatibilitytool.vdf').write_text('''"compatibilitytools"
{
    "compat_tools"
    {
        "arlinux-proton-arm64"
        {
            "install_path" "."
            "display_name" "Proton ARM64 (ARLinux compatibility)"
            "from_oslist" "windows"
            "to_oslist" "linux"
        }
    }
}
''')
        stage.rename(tool)
    print(f'Registered {data["version"]}; restart Steam to select the tool')


def verify_tree(stock, tool, data):
    """Check copied modules and loaders, not only the pack we copied from."""
    for name in CORE:
        if (tool/name).is_symlink() or digest(tool/name) != data['files'][name]:
            raise RuntimeError(f'Damaged staged Proton core: {name}')
    for name in LOADERS:
        if (stock/name).is_file():
            if (tool/name).is_symlink() or digest(tool/name) != digest(stock/name):
                raise RuntimeError(f'Proton loader changed; rebuild the compatibility tool: {name}')


def launch(tool, arguments):
    record = json.loads((tool/'arlinux-pack.json').read_text())
    data = validate(Path(record['stock']), Path(record['pack']))
    if data != record['manifest']:
        raise RuntimeError('Core pack changed; rebuild the compatibility tool before launching')
    verify_tree(Path(record['stock']), tool, data)
    # Steam's private client libraries must not replace the desktop's libraries
    # when Proton is run without the Steam Linux Runtime container.
    os.environ['LD_LIBRARY_PATH'] = ':'.join(
        value for value in os.environ.get('LD_LIBRARY_PATH', '').split(':')
        if value and 'steamrtarm64' not in Path(value).parts)
    os.execv(str(tool/'proton'), [str(tool/'proton'), *arguments])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    install = commands.add_parser('register')
    for name in ('stock', 'pack', 'tool'):
        install.add_argument('--'+name, required=True, type=Path)
    run = commands.add_parser('run')
    run.add_argument('tool', type=Path)
    run.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command == 'register':
        register(args.stock, args.pack, args.tool)
    else:
        launch(args.tool, args.arguments)


if __name__ == '__main__':
    main()
