"""On-demand Windows apps. Each app owns its prefix; Wine/FEX remain shared.

Downloads come from the vendors, never from a copied development prefix.
Power BI's WebView2 sandbox is disabled in its dedicated Wine prefix only:
Wine lacks the required Windows sandbox interception thunks. Android app
isolation is not equivalent to browser sandboxing. First installation requires
explicit consent. Both applications are experimental on ARLinux.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

import windows
import shared

MANIFEST = Path('/usr/lib/arlinux/guest/windows-app-downloads.tsv')
LICENSES = {
    'paintnet': 'https://www.getpaint.net/license.html',
    'powerbi': 'https://powerbi.microsoft.com/desktop-eula/',
}


def download(name):
    row = next(line.split('\t') for line in MANIFEST.read_text().splitlines()
               if line.startswith(name + '\t'))
    _, expected, url = row
    if (not re.fullmatch('[0-9a-f]{64}', expected) or not url.startswith('https://')):
        raise ValueError('Invalid Windows application download manifest')
    return shared.download(url, expected, '.zip' if name == 'paintnet' else '.exe')


def unpack_zip(archive, destination):
    """Normalize vendor Windows ZIP paths without allowing traversal or links."""
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            name = entry.filename.replace('\\', '/')
            target = (destination / name).resolve()
            if (not target.is_relative_to(destination.resolve()) or ':' in name
                    or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError(f'Unsafe ZIP entry: {name}')
            if entry.is_dir() or name.endswith('/'):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(entry) as data, target.open('wb') as output:
                    shutil.copyfileobj(data, output)


def consent(app, accepted):
    print(f'First installation needs internet access and several GB of storage.\n'
          f'License: {LICENSES[app]}', flush=True)
    if app == 'powerbi':
        print('Also installs Microsoft .NET and WebView2 under their licenses.\n'
              'WebView2 browser sandboxing is disabled inside this Wine prefix.\n'
              'Use trusted reports and data sources only.', flush=True)
    else:
        print('The vendor Wine build is experimental and expires after 12 weeks.', flush=True)
    if not accepted and (not sys.stdin.isatty() or
                         input('Accept the licenses and continue? [y/N] ').strip().lower() != 'y'):
        raise RuntimeError('Installation cancelled; no application license was accepted')


def install_powerbi(root, prefix):
    env = windows.environment(root, prefix)
    system = prefix / 'pfx/drive_c/windows/system32'

    def run(exe, *args, **kwargs):
        result = windows.run(root, prefix, exe, args,
                             env={**env, **kwargs.get('environment', {})},
                             capture=kwargs.get('capture', False), timeout=3600)
        # Windows installers return 3010 for successful installation requiring
        # reboot; Wine's Unix exit status carries its low byte.
        if result.returncode not in (0, 3010 & 255):
            result.check_returncode()
        if result.returncode == (3010 & 255):
            # Complete delayed CLR replacements before the next installer loads
            # them. Kill this isolated prefix's processes first: wineboot would
            # otherwise discard pending renames for DLLs still held open.
            windows.run(root, prefix, system / 'wineboot.exe', ['-k', '-r'],
                        env={**env, 'WINEDLLOVERRIDES': 'mscoree=b'},
                        timeout=3600, check=True)
        return result

    reg, cfg = system / 'reg.exe', system / 'winecfg.exe'
    # Remove Wine Mono through its registered uninstaller, not fabricated keys.
    listing = run(system / 'uninstaller.exe', '--list', capture=True)
    for line in listing.stdout.splitlines():
        match = re.fullmatch(r'([^|]+)\|\|\|Wine Mono(?: .*)?', line.strip())
        if match:
            run(system / 'uninstaller.exe', '--remove', match[1])
    # A missing key is expected before installation or after an interrupted
    # install. Probe it without treating reg.exe's not-found status as fatal.
    release = windows.run(root, prefix, reg,
                          ['query', r'HKLM\Software\Microsoft\NET Framework Setup\NDP\v4\Full',
                           '/v', 'Release', '/reg:64'], env=env, capture=True, timeout=3600)
    if release.returncode not in (0, 1):
        release.check_returncode()
    match = re.search(r'Release\s+REG_DWORD\s+(0x[0-9a-fA-F]+)', release.stdout)
    # Wine's default registry advertises .NET 4.8 even without Microsoft's CLR.
    # A version key alone is therefore not an installed dependency check.
    native_clr = prefix / 'pfx/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/clr.dll'
    native_shims = [prefix / 'pfx/drive_c/windows' / directory / 'mscoree.dll'
                    for directory in ('system32', 'syswow64')]
    # .NET 4.8 is an upgrade: its success does not install the CLR activation
    # shim when 4.0 was skipped because Wine advertised a default NDP version.
    def microsoft_shims():
        return all(path.is_file() and b'Wine builtin DLL' not in path.read_bytes()[:256]
                   for path in native_shims)

    if not native_clr.is_file() or not microsoft_shims() or not match or int(match[1], 16) < 528040:
        print('Installing Microsoft .NET 4.0 and 4.8…', flush=True)
        try:
            if not native_clr.is_file() or not microsoft_shims():
                # Remove Wine's placeholder registration only when the real CLR
                # is absent. Do not claim an installed Microsoft version.
                if not native_clr.is_file():
                    for view in ('/reg:32', '/reg:64'):
                        key = r'HKLM\Software\Microsoft\NET Framework Setup\NDP\v4'
                        existing = windows.run(root, prefix, reg, ['query', key, view],
                                               env=env, capture=True)
                        if existing.returncode == 0:
                            run(reg, 'delete', key, '/f', view)
                run(cfg, '/v', 'winxp')
                run(download('dotnet40'), '/q', '/norestart', '/log', r'C:\dotnet40.log',
                    environment={'WINEDLLOVERRIDES': 'fusion=b'})
                if not microsoft_shims():
                    raise RuntimeError('Microsoft .NET 4.0 did not install both CLR activation shims')
                run(reg, 'add', r'HKCU\Software\Wine\DllOverrides', '/v', 'mscoree',
                    '/t', 'REG_SZ', '/d', 'native,builtin', '/f')
            run(cfg, '/v', 'win7')
            run(download('dotnet48'), '/q', '/norestart', '/log', r'C:\dotnet48.log',
                environment={'WINEDLLOVERRIDES': 'fusion=b'})
        finally:
            run(cfg, '/v', 'win10')
        release = run(reg, 'query', r'HKLM\Software\Microsoft\NET Framework Setup\NDP\v4\Full',
                      '/v', 'Release', '/reg:64', capture=True)
        match = re.search(r'Release\s+REG_DWORD\s+(0x[0-9a-fA-F]+)', release.stdout)
        if not native_clr.is_file() or not microsoft_shims() or not match or int(match[1], 16) < 528040:
            raise RuntimeError('Microsoft .NET 4.8 installation did not complete')
    webview = prefix / 'pfx/drive_c/Program Files (x86)/Microsoft/EdgeWebView/Application'
    if not list(webview.glob('*/msedgewebview2.exe')):
        run(download('webview2'), '/silent', '/install')
    run(download('powerbi'), '-quiet', '-norestart', 'ACCEPT_EULA=1', 'ENABLECXP=0')
    executable = prefix / 'pfx/drive_c/Program Files/Microsoft Power BI Desktop/bin/PBIDesktop.exe'
    if not executable.is_file():
        raise RuntimeError('Power BI installer did not create PBIDesktop.exe; see installer logs in the prefix')
    # Official WebView2 policy; limited to this application's isolated prefix.
    run(reg, 'add', r'HKLM\Software\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments',
        '/v', 'PBIDesktop.exe', '/t', 'REG_SZ', '/d', '--no-sandbox', '/f', '/reg:64')
    # Re-register oleacc after installers so IAccessible marshaling uses the
    # Accessibility typelib instead of an imported UIAutomation mapping.
    run(reg.parent / 'regsvr32.exe', '/s', 'oleacc.dll')
    return executable


def ensure_powerbi_authentication():
    # Offline reports also authenticate against the local Analysis Services.
    # Android's Bionic Wine host invokes this helper through the guest launcher.
    if shutil.which('ntlm_auth'):
        return
    print('Installing local authentication support…', flush=True)
    subprocess.run(['sudo', 'apt-get', 'update'], check=True)
    subprocess.run(['sudo', 'apt-get', 'install', '-y', '--no-install-recommends',
                    'winbind'], check=True)


def prepare(app, accepted=False):
    home = windows.storage() / 'apps' / app
    home.mkdir(parents=True, exist_ok=True)
    cache = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'arlinux/windows-apps' / app
    cache.mkdir(parents=True, exist_ok=True)
    prefix = home / 'wine'
    pointer = home / 'installed.json'
    with (home / 'install.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if pointer.is_file():
            entry = json.loads(pointer.read_text())
            executable = (home / entry['executable']).resolve(strict=True)
            if not executable.is_relative_to(home.resolve()):
                raise ValueError('Invalid installed app path')
            if app == 'powerbi':
                ensure_powerbi_authentication()
            return executable, prefix, cache
        consent(app, accepted)
        if app == 'powerbi':
            ensure_powerbi_authentication()
        root = windows.ensure_runtime()
        windows.initialize(root, prefix, windows.environment(root, prefix))
        if app == 'paintnet':
            env = windows.environment(root, prefix)
            system = prefix / 'pfx/drive_c/windows/system32'
            # Match the vendor setup: Windows 11 and ClearType, with the
            # runtime's version-matched DXVK already installed by initialize.
            windows.run(root, prefix, system / 'winecfg.exe', ['/v', 'win11'], env=env, check=True)
            windows.run(root, prefix, system / 'reg.exe', ['add', r'HKCU\Control Panel\Desktop',
                        '/v', 'FontSmoothingType', '/t', 'REG_DWORD', '/d', '2', '/f'], env=env, check=True)
            # Atomic extraction leaves retryable downloads, not half-ready apps.
            application = prefix / 'pfx/drive_c/Program Files/Paint.NET'
            if not (application / 'paintdotnet.exe').is_file():
                with tempfile.TemporaryDirectory(prefix='extract-', dir=home) as temporary:
                    stage = Path(temporary) / 'application'
                    stage.mkdir()
                    unpack_zip(download(app), stage)
                    if not (stage / 'paintdotnet.exe').is_file():
                        raise RuntimeError('Paint.NET executable missing from official archive')
                    application.parent.mkdir(parents=True, exist_ok=True)
                    stage.rename(application)
            executable = application / 'paintdotnet.exe'
        else:
            executable = install_powerbi(root, prefix)
        temporary = pointer.with_suffix('.tmp')
        temporary.write_text(json.dumps({'executable': str(executable.relative_to(home))}) + '\n')
        temporary.replace(pointer)
        return executable, prefix, cache


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', choices=LICENSES)
    parser.add_argument('--desktop', action='store_true')
    parser.add_argument('--accept-license', action='store_true', help='Explicit consent for unattended installation')
    args = parser.parse_args()
    executable, prefix, cache = prepare(args.app, args.accept_license)
    root = windows.ensure_runtime()
    env = windows.environment(root, prefix)
    windows.initialize(root, prefix, env)
    import windows_a11y
    windows_a11y.ensure(root, prefix, 'Paint.NET' if args.app == 'paintnet' else 'Power BI Desktop', env)
    if args.app == 'paintnet':
        # These are the vendor paintdotnet.sh overrides, not modified binaries.
        env['WINEDLLOVERRIDES'] = 'mshtml=;d3dcompiler_47=n'
    response = windows.request(root, prefix, executable,
                               overrides=env.get('WINEDLLOVERRIDES', ''))
    (cache / 'desktop.log').write_text('Native log: '+response['log']+'\n')
    exit_file = windows.guest_path(response['exit'])
    import time
    time.sleep(2)
    if exit_file.is_file() and int(exit_file.read_text()) != 0:
        raise RuntimeError('Application exited; see '+str(windows.guest_path(response['log'])))
    return 0


if __name__ == '__main__':
    try:
        status = main()
    except (OSError, ValueError, RuntimeError, KeyError, StopIteration,
            zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        print(f'Windows app: {error}\nClick the app again to retry.', file=sys.stderr)
        status = 1
    if status and '--desktop' in sys.argv and sys.stdin.isatty():
        try:
            input('\nPress Enter to close this window. ')
        except (EOFError, KeyboardInterrupt):
            pass
    sys.exit(status)
