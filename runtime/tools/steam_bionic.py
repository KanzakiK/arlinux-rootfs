"""Steam compatibility-tool entry point for Android-hosted Bionic Wine.

Steam launches a guest Python adapter; only the Android host executes Wine.
Runtime installation uses the pinned Windows manifest and immutable shared cache.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

TOOL = 'arlinux-wine-bionic'
ENVIRONMENT = ('SteamAppId', 'SteamGameId', 'SteamOverlayGameId',
               'WEBVIEW2_BROWSER_EXECUTABLE_FOLDER',
               'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS')


def register(steam):
    tool = steam/'compatibilitytools.d'/TOOL
    expected = {'backend': 'bionic', 'protocol': 1}
    if tool.exists():
        marker = tool/'arlinux-backend.json'
        if not marker.is_file() or json.loads(marker.read_text()) != expected:
            raise RuntimeError('Preserving unrecognized compatibility tool: '+str(tool))
        return tool
    tool.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.wine-bionic-', dir=tool.parent) as temporary:
        stage = Path(temporary)/'tool'
        stage.mkdir()
        (stage/'arlinux-backend.json').write_text(json.dumps(expected)+'\n')
        (stage/'run').write_text('#!/bin/sh\nexec python3 /usr/lib/arlinux/steam_bionic.py launch "$@"\n')
        (stage/'run').chmod(0o755)
        (stage/'toolmanifest.vdf').write_text('"manifest"\n{\n "version" "2"\n "commandline" "/run %verb%"\n "use_sessions" "0"\n}\n')
        (stage/'compatibilitytool.vdf').write_text('"compatibilitytools"\n{\n "compat_tools"\n {\n  "'+TOOL+'"\n  {\n   "install_path" "."\n   "display_name" "ARLinux Wine (Bionic, experimental)"\n   "from_oslist" "windows"\n   "to_oslist" "linux"\n  }\n }\n}\n')
        stage.rename(tool)
    return tool


def launch(verb, arguments):
    import windows
    if verb not in ('run', 'waitforexitandrun', 'getcompatpath', 'getnativepath'):
        raise ValueError('Unsupported Steam compatibility operation: '+verb)
    if not arguments:
        raise ValueError('Steam did not provide an executable or path')
    if verb == 'getcompatpath':
        print('Z:'+str(windows.host_path(arguments[0])).replace('/', '\\'))
        return 0
    if verb == 'getnativepath':
        value = arguments[0]
        if value[:3].lower() != 'z:\\':
            raise ValueError('Only the Bionic host Z: drive can be translated')
        print(windows.guest_path(value[2:].replace('\\', '/')))
        return 0
    data = os.environ.get('STEAM_COMPAT_DATA_PATH', '')
    if not data or not Path(data).is_absolute():
        raise ValueError('Steam must provide an absolute STEAM_COMPAT_DATA_PATH')
    env = {name: os.environ[name] for name in ENVIRONMENT if name in os.environ}
    for name, value in env.items():
        if name.startswith('Steam') and not value.isdecimal():
            raise ValueError('Invalid Steam game identity: '+name)
    root = windows.ensure_runtime()
    # The Android host owns initialization, DXVK setup and native driver paths.
    result = windows.run(root, Path(data), arguments[0], arguments[1:], env=env,
                         timeout=7*24*60*60)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    install = commands.add_parser('register')
    install.add_argument('steam', type=Path)
    run = commands.add_parser('launch')
    run.add_argument('verb')
    run.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command == 'register':
        print(register(args.steam))
        return 0
    return launch(args.verb, args.arguments)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print('ARLinux Bionic compatibility: '+str(error), file=sys.stderr)
        raise SystemExit(1)
