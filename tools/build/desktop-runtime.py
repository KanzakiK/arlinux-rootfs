"""Source-owned runtime files refreshed when reusing an offline package snapshot."""
from pathlib import Path


def runtime_files(framework):
    root = Path(framework)
    tools = root / 'runtime/tools'
    files = {}
    # All runtime launchers, modules, manifests and icons belong to the framework,
    # not the reusable distro package snapshot. Keep this list directory-driven.
    for source in sorted(tools.iterdir()):
        if not source.is_file():
            continue
        name = source.name
        if source.suffix == '.py':
            target = 'usr/lib/arlinux/' + name
            if name == 'apps.py':
                target = 'usr/lib/arlinux/guest/yibu-launcher.py'
        elif source.suffix == '.tsv':
            target = 'usr/lib/arlinux/guest/' + name
        elif source.suffix == '.desktop':
            target = 'usr/share/applications/' + name
        elif source.suffix == '.png':
            target = 'usr/share/pixmaps/arlinux-' + name
        elif name.startswith('arlinux-') and not source.suffix:
            target = 'usr/bin/' + name
        else:
            continue
        files[target] = source
    # First-boot and voice helpers are also duplicated outside the rootfs tar.
    guest = root / 'distributions/yibu/guest'
    for source in sorted(guest.rglob('*')):
        if source.is_file() and source.name != 'README.txt' and '__pycache__' not in source.parts:
            files['usr/lib/arlinux/guest/' + source.relative_to(guest).as_posix()] = source
    session = root / 'tools/arlinux-app-data'
    for name, target in {
        'hosted-ime.py': 'usr/lib/arlinux/hosted-ime.py',
        'org.arlinux.HostedInput.service': 'usr/share/dbus-1/services/org.arlinux.HostedInput.service',
        'arlinux-hosted.xml': 'usr/share/ibus/component/arlinux-hosted.xml',
        '90-arlinux-ibus.gschema.override': 'usr/share/glib-2.0/schemas/90-arlinux-ibus.gschema.override',
    }.items():
        source = session / name
        if source.is_file():
            files[target] = source
    return files


def bundle_files(framework):
    # RootfsSetup.copyHelpers installs this outer asset into the rootfs.
    root = Path(framework) / 'tools/arlinux-app-data'
    return {'arlinux/accessibility-session.sh': root / 'accessibility-session.sh'}
