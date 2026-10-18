#!/usr/bin/env python3
"""Build the pinned ARM64 Spark Store package for the ARLinux guest."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import urllib.request
from artifact_download import download

URL = 'https://cdn.d.store.deepinos.org.cn/aarch64-store/tools/spark-store/spark-store_5.3.2_arm64.deb'
SHA256 = '6c4ce66ab3523bf8c48276d956f7dfd8cd7682581e64cbc2a0baf803c456ffab'


def patch_asar(path):
    original = path.read_bytes()
    header = json.loads(original[16:16 + struct.unpack_from('<I', original, 12)[0]])
    start = 8 + struct.unpack_from('<I', original, 4)[0]
    payload = bytearray()

    def visit(nodes, prefix=''):
        for name, node in nodes.items():
            full = prefix + name
            if 'files' in node:
                visit(node['files'], full + '/')
            elif 'offset' in node and not node.get('unpacked'):
                offset, size = int(node['offset']), node['size']
                data = original[start + offset:start + offset + size]
                if full == 'dist-electron/main/index.js':
                    old = b'const Pa = pf.ref(!1), dc = [\n  "/usr/bin/pkexec",'
                    new = b'const Pa = pf.ref(!1), dc = [\n  "/opt/spark-store/extras/arlinux-pkexec",\n  "/usr/bin/pkexec",'
                    if data.count(old) != 1:
                        raise ValueError('Pinned Spark privilege discovery changed')
                    data = data.replace(old, new)
                    block = node.get('integrity', {}).get('blockSize', 4194304)
                    node['integrity'] = {'algorithm': 'SHA256', 'hash': hashlib.sha256(data).hexdigest(),
                                         'blockSize': block, 'blocks': [hashlib.sha256(data[i:i+block]).hexdigest()
                                                                      for i in range(0, len(data), block)]}
                node['offset'], node['size'] = str(len(payload)), len(data)
                payload.extend(data)

    visit(header['files'])
    raw = json.dumps(header, separators=(',', ':'), ensure_ascii=False).encode()
    padded = raw + b'\0' * (-len(raw) % 4)
    header_size = len(padded) + 8
    path.write_bytes(struct.pack('<4I', 4, header_size, header_size - 4, len(raw)) + padded + payload)


def build(source, output):
    download(URL,source,SHA256)
    with tempfile.TemporaryDirectory(prefix='arlinux-spark-') as directory:
        root = Path(directory) / 'package'
        subprocess.run(['dpkg-deb', '-R', str(source), str(root)], check=True)
        control = root / 'DEBIAN/control'
        text = control.read_text().replace('Version: 5.3.2\n', 'Version: 5.3.2+arlinux.1\n')
        text = text.replace(', policykit-1 | pkexec', '').replace(', systemd,', ',')
        control.write_text(text)
        # The container has no systemd daemon or polkit authority. Installation
        # stays inside its filesystem and uses its virtual set-id sudo helper.
        for name in ['preinst', 'prerm', 'postrm', 'triggers']:
            (root / 'DEBIAN' / name).unlink(missing_ok=True)
        postinst = root / 'DEBIAN/postinst'
        postinst.write_text('''#!/bin/sh
set -eu
if [ "$1" = configure ]; then
    mkdir -p /var/lib/aptss/lists /usr/local/bin /etc/apt/trusted.gpg.d
    for name in ssinstall ssaudit spark-dstore-patch aptss; do
        ln -sf /opt/durapps/spark-store/bin/$name /usr/bin/$name
    done
    ln -sf /usr/bin/arlinux-spark-store /usr/local/bin/spark-store
    gpg --batch --yes --dearmor -o /etc/apt/trusted.gpg.d/spark-store.gpg /opt/durapps/spark-store/bin/spark-store.asc
    update-desktop-database /usr/share/applications || true
    update-mime-database /usr/share/mime || true
fi
''')
        postinst.chmod(0o755)
        install = root / 'opt/durapps/spark-store/bin/ssinstall'
        text = install.read_text()
        first, last = text.index('function get_current_user() {'), text.index('# 全局变量初始化')
        text = text[:first] + '''function get_current_user() {
    printf '%s\\n' "${SUDO_USER:-${USER:-root}}"
}

function zenity() {
    command /usr/bin/zenity "$@"
}

''' + text[last:]
        text = text.replace('export user=$(who | awk \'{print $1}\' | head -n 1)',
                            'export user=$(get_current_user)')
        text = text.replace('$(sudo -u "$user" xdg-user-dir)', '$HOME')
        text = text.replace('export CURRENT_USER_DIR_DESKTOP=$(sudo -u "$user" xdg-user-dir DESKTOP)',
                            'export CURRENT_USER_DIR_DESKTOP="${XDG_DESKTOP_DIR:-$HOME/Desktop}"')
        text = text.replace('sudo -u "$user" cp ', 'cp ')
        install.write_text(text)
        aptss = root / 'opt/durapps/spark-store/bin/aptss'
        text = aptss.read_text().replace('#!/bin/bash\n', '''#!/bin/bash
# A sealed desktop keeps package indexes and archives empty until first use.
if [ "$(id -u)" = 0 ]; then
    mkdir -p /var/lib/apt/lists/partial /var/cache/apt/archives/partial \\
        /var/cache/apt/apt-fast /var/lib/aptss/lists/partial
fi
''', 1)
        aptss.write_text(text)
        app_launcher = root / 'opt/spark-store/extras/app-launcher'
        text = app_launcher.read_text()
        marker = '    local package_name=$1\n    # 标准desktop文件检测'
        preferred = """    local package_name=$1
    # Prefer the user's application entry over an optional administrative entry.
    # For example, BleachBit also ships a separate pkexec desktop shortcut.
    while IFS= read -r path; do
        if ! grep -qE '^NoDisplay=true|^Exec=(pkexec|sudo) ' "$path"; then
            export desktop_file_path="$path"
            return 0
        fi
    done < <(dpkg -L "$package_name" 2>/dev/null | grep -E '/usr/share/applications/.*\\.desktop$|/opt/apps/.*/entries/applications/.*\\.desktop$')
    # 标准desktop文件检测"""
        if text.count(marker) != 1:
            raise ValueError('Pinned Spark application launcher changed')
        app_launcher.write_text(text.replace(marker, preferred))
        patch_asar(root / 'opt/spark-store/bin/resources/app.asar')
        helper = root / 'opt/spark-store/extras/arlinux-pkexec'
        helper.parent.mkdir(parents=True, exist_ok=True)
        helper.write_text('#!/bin/sh\nexec /usr/bin/sudo "$@"\n')
        helper.chmod(0o755)
        launcher = root / 'usr/bin/arlinux-spark-store'
        launcher.write_text('#!/bin/sh\nexec /opt/spark-store/bin/spark-store --no-sandbox --no-apm --ozone-platform=x11 "$@"\n')
        launcher.chmod(0o755)
        desktop = root / 'usr/share/applications/spark-store.desktop'
        text = desktop.read_text()
        text = '\n'.join('Exec=/usr/bin/arlinux-spark-store %U' if line.startswith('Exec=') else line for line in text.splitlines()) + '\n'
        desktop.write_text(text)
        sums = []
        for file in sorted(root.rglob('*')):
            relative = file.relative_to(root).as_posix()
            if file.is_file() and not file.is_symlink() and not relative.startswith('DEBIAN/'):
                sums.append(hashlib.md5(file.read_bytes()).hexdigest() + '  ' + relative + '\n')
        (root / 'DEBIAN/md5sums').write_text(''.join(sums))
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['dpkg-deb', '--root-owner-group', '-Zxz', '-z6', '-b', str(root), str(output)], check=True)
    print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    build(args.source, args.output)
