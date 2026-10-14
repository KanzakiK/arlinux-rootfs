"""Instance-local Steam HTTPS relay using distribution nginx and a private CA.

Keep the HTTP Steam Host while using a verified Akamai TLS name upstream.
Certificates and services are never shared between Linux instances.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time

DOMAINS = (
    'store.steampowered.com', 'steamcommunity.com', 'www.steamcommunity.com',
    'api.steampowered.com', 'store.akamai.steamstatic.com',
    'community.akamai.steamstatic.com', 'cdn.akamai.steamstatic.com',
    'avatars.akamai.steamstatic.com', 'client-update.akamai.steamstatic.com',
    'client-update.fastly.steamstatic.com',
)
UPSTREAMS = ('steamuserimages-a.akamaihd.net.edgesuite.net',
             'steamstore-a.akamaihd.net.edgesuite.net',
             'eaassets-a.akamaihd.net.edgesuite.net',
             'steamcommunity-a.akamaihd.net.edgesuite.net')
SNI = 'officecdn-microsoft-com.akamaized.net'
ADDRESS = '127.0.0.2'
BEGIN = '# BEGIN ARLinux Steam proxy'
END = '# END ARLinux Steam proxy'
CA_NAME = 'ARLinux instance Steam proxy'
TRUST = Path('/usr/local/share/ca-certificates/arlinux-steam-proxy.crt')


def enabled():
    language = Path('/etc/arlinux-steam-language')
    return language.is_file() and language.read_text().strip() == 'zh'


def strip_section(text, begin, end):
    lines = text.splitlines(keepends=True)
    output = []
    i = 0
    while i < len(lines):
        if lines[i].strip() == begin:
            closing = next((j for j in range(i + 1, len(lines)) if lines[j].strip() == end), None)
            if closing is not None:
                i = closing + 1
                continue
        output.append(lines[i])
        i += 1
    return ''.join(output)


def hosts_text(text, activate):
    text = strip_section(text, BEGIN, END)
    if not activate:
        return text
    # The Android DNS optimizer owns this other section. Once the relay is
    # active its Steam entries must not compete with direct CDN addresses.
    text = strip_section(text, '# BEGIN ARLinux Steam DNS', '# END ARLinux Steam DNS')
    existing = {name.lower() for line in text.splitlines()
                for name in line.split('#', 1)[0].split()[1:]}
    entries = [f'{ADDRESS} {domain}\n' for domain in DOMAINS if domain not in existing]
    if not entries:
        return text
    return text + ('' if text.endswith('\n') else '\n') + BEGIN + '\n' + ''.join(entries) + END + '\n'


def write_hosts(activate):
    hosts = Path('/etc/hosts')
    if hosts.is_symlink():
        raise RuntimeError('Steam relay will not replace a redirected hosts file')
    before = hosts.read_text()
    after = hosts_text(before, activate)
    if after == before:
        return
    with tempfile.NamedTemporaryFile(dir=hosts.parent, prefix='.steam-proxy-', delete=False) as output:
        temporary = Path(output.name)
        output.write(after.encode())
    try:
        temporary.chmod(hosts.stat().st_mode & 0o777)
        temporary.replace(hosts)
    finally:
        temporary.unlink(missing_ok=True)


def dependencies():
    if all(shutil.which(name) for name in ('nginx', 'openssl', 'certutil', 'update-ca-certificates')):
        return
    if shutil.which('apt-get'):
        subprocess.run(['sudo', 'apt-get', 'update'], check=True)
        subprocess.run(['sudo', 'apt-get', 'install', '-y', '--no-install-recommends',
                        'nginx-light', 'openssl', 'libnss3-tools', 'ca-certificates'], check=True)
    elif shutil.which('pacman'):
        subprocess.run(['sudo', 'pacman', '-S', '--needed', '--noconfirm',
                        'nginx', 'openssl', 'nss', 'ca-certificates-utils'], check=True)
    else:
        raise RuntimeError('Install nginx, OpenSSL and certutil for the Chinese Steam relay')


def run(*arguments):
    return subprocess.run(list(arguments), check=True, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL)


def certificates(directory):
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    ca, cert = directory/'ca.crt', directory/'server.crt'
    valid = all((directory/name).is_file() for name in ('ca.crt', 'ca.key', 'server.crt', 'server.key'))
    if valid:
        valid = subprocess.run(['openssl', 'x509', '-in', str(cert), '-checkend', '86400', '-noout'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if valid:
        return ca, cert
    previous = os.umask(0o077)
    try:
        run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '365',
            '-subj', '/CN=ARLinux instance Steam proxy', '-keyout', str(directory/'ca.key'),
            '-out', str(ca), '-addext', 'basicConstraints=critical,CA:TRUE,pathlen:0',
            '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
        run('openssl', 'req', '-new', '-newkey', 'rsa:2048', '-nodes',
            '-subj', '/CN=ARLinux Steam relay', '-keyout', str(directory/'server.key'),
            '-out', str(directory/'server.csr'))
        extensions = directory/'server.ext'
        extensions.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n'
                              'extendedKeyUsage=serverAuth\nsubjectAltName=' + ','.join('DNS:' + d for d in DOMAINS) + '\n')
        run('openssl', 'x509', '-req', '-in', str(directory/'server.csr'), '-CA', str(ca),
            '-CAkey', str(directory/'ca.key'), '-CAcreateserial', '-days', '30',
            '-extfile', str(extensions), '-out', str(cert))
    finally:
        os.umask(previous)
    return ca, cert


def trust(ca):
    TRUST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ca, TRUST)
    TRUST.chmod(0o644)
    run('sudo', 'update-ca-certificates')
    nss = Path.home()/'.pki/nssdb'
    nss.mkdir(parents=True, exist_ok=True)
    database = 'sql:' + str(nss)
    if not (nss/'cert9.db').exists():
        run('certutil', '-N', '--empty-password', '-d', database)
    subprocess.run(['certutil', '-D', '-d', database, '-n', CA_NAME],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    run('certutil', '-A', '-d', database, '-n', CA_NAME, '-t', 'C,,', '-i', str(ca))


def configuration(directory):
    # No access log: request URLs, cookies, login state and bodies are private.
    upstreams = '\n'.join('server ' + d + ':443 max_fails=2 fail_timeout=5s;' for d in UPSTREAMS)
    return f'''worker_processes 1;
pid "{directory}/nginx.pid";
error_log /dev/null;
events {{ worker_connections 256; }}
http {{
    access_log off;
    client_body_temp_path "{directory}/body";
    proxy_temp_path "{directory}/proxy";
    map $http_upgrade $upgrade_connection {{ default upgrade; '' close; }}
    upstream steam_edge {{ least_conn; {upstreams} }}
    server {{ listen {ADDRESS}:443 ssl default_server; ssl_reject_handshake on; }}
    server {{
        listen {ADDRESS}:443 ssl;
        server_name {' '.join(DOMAINS)};
        ssl_certificate "{directory}/server.crt";
        ssl_certificate_key "{directory}/server.key";
        ssl_protocols TLSv1.2 TLSv1.3;
        client_max_body_size 32m;
        location / {{
            proxy_pass https://steam_edge;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $upgrade_connection;
            proxy_ssl_server_name on;
            proxy_ssl_name {SNI};
            proxy_ssl_verify on;
            proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;
            proxy_connect_timeout 5s;
            proxy_read_timeout 120s;
            proxy_next_upstream error timeout http_502 http_503 http_504;
            proxy_next_upstream_tries 4;
            proxy_next_upstream_timeout 15s;
            proxy_buffering off;
            proxy_request_buffering off;
        }}
    }}
}}
'''


@contextmanager
def session():
    """Start before Steam, remove redirects before stopping the local service."""
    write_hosts(False)  # Remove redirects left by a crashed previous session.
    if not enabled():
        yield
        return
    dependencies()
    directory = Path.home()/'.local/share/arlinux/steam-proxy'
    ca, cert = certificates(directory)
    trust(ca)
    for name in ('body', 'proxy'):
        (directory/name).mkdir(mode=0o700, exist_ok=True)
    config = directory/'nginx.conf'
    config.write_text(configuration(directory))
    config.chmod(0o600)
    run('nginx', '-t', '-p', str(directory) + '/', '-c', str(config))
    service = subprocess.Popen(['nginx', '-p', str(directory) + '/', '-c', str(config), '-g', 'daemon off;'],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    stopped = threading.Event()
    def watch():
        while not stopped.wait(2):
            if service.poll() is not None or not enabled():
                write_hosts(False)
                return
    try:
        deadline = time.monotonic() + 5
        while True:
            if service.poll() is not None:
                raise RuntimeError('Steam HTTPS relay failed to start')
            try:
                with socket.create_connection((ADDRESS, 443), timeout=.2):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    raise RuntimeError('Steam HTTPS relay did not open its listener')
                time.sleep(.1)
        write_hosts(True)
        threading.Thread(target=watch, daemon=True).start()
        print('Chinese Steam HTTPS relay ready (private instance certificate; verified Akamai upstream).', flush=True)
        yield
    finally:
        stopped.set()
        write_hosts(False)
        service.terminate()
        try:
            service.wait(timeout=5)
        except subprocess.TimeoutExpired:
            service.kill()
            service.wait()
