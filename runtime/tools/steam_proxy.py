"""Prepare instance-local trust for the Android Kotlin Steam HTTPS relay.

Keep the HTTP Steam Host while using a verified Akamai TLS name upstream.
Certificates and services are never shared between Linux instances.
"""
import hashlib
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess

DOMAINS = (
    'store.steampowered.com', 'steamcommunity.com', 'www.steamcommunity.com',
    'api.steampowered.com', 'store.akamai.steamstatic.com',
    'community.akamai.steamstatic.com', 'cdn.akamai.steamstatic.com',
    'avatars.akamai.steamstatic.com',
    'client-update.steamstatic.com', 'client-update.fastly.steamstatic.com',
    'client-update.akamai.steamstatic.com', 'cdn.steamstatic.com',
)
def instance_address(home=None):
    # Android apps and Linux instances share the host loopback namespace.
    # Include the package and instance path so Debug/Release cannot share a relay.
    identity = str(Path.home() if home is None else home).encode()
    octets = hashlib.sha256(identity).digest()[:3]
    return '127.' + '.'.join(str(part) for part in octets)


ADDRESS = instance_address()
CA_NAME = 'ARLinux instance Steam proxy'
TRUST = Path('/usr/local/share/ca-certificates/arlinux-steam-proxy.crt')


def enabled():
    language = Path('/etc/arlinux-steam-language')
    return language.is_file() and language.read_text().strip() == 'zh'


def dependencies():
    if all(shutil.which(name) for name in ('openssl', 'certutil', 'update-ca-certificates')):
        return
    if shutil.which('apt-get'):
        subprocess.run(['sudo', 'apt-get', 'update'], check=True)
        subprocess.run(['sudo', 'apt-get', 'install', '-y', '--no-install-recommends',
                        'openssl', 'libnss3-tools', 'ca-certificates'], check=True)
    elif shutil.which('pacman'):
        subprocess.run(['sudo', 'pacman', '-S', '--needed', '--noconfirm',
                        'openssl', 'nss', 'ca-certificates-utils'], check=True)
    else:
        raise RuntimeError('Install OpenSSL and certutil for the Chinese Steam relay')


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
        # Renew certificates when a release expands the served domain list.
        valid = all(subprocess.run(['openssl', 'verify', '-CAfile', str(ca),
                                   '-verify_hostname', domain, str(cert)], stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL).returncode == 0
                    for domain in DOMAINS)
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


def prepare():
    """Prepare certificates and guest trust; Android serves TLS and HTTP."""
    if not enabled():
        return False
    dependencies()
    directory = Path.home()/'.local/share/arlinux/steam-proxy'
    ca, cert = certificates(directory)
    trust(ca)
    return True


def activate():
    """Verify CONNECT and instance TLS before exposing proxy configuration."""
    ca = Path.home()/'.local/share/arlinux/steam-proxy/ca.crt'
    context = ssl.create_default_context(cafile=str(ca))
    with socket.create_connection((ADDRESS, 18443), timeout=5) as connection:
        connection.sendall(b'CONNECT store.steampowered.com:443 HTTP/1.1\r\nHost: store.steampowered.com:443\r\n\r\n')
        response = bytearray()
        while not response.endswith(b'\r\n\r\n'):
            block = connection.recv(1)
            if not block or len(response) >= 8192:
                raise RuntimeError('Steam HTTP proxy handshake failed')
            response.extend(block)
        if not response.startswith(b'HTTP/1.1 200 '):
            raise RuntimeError('Steam HTTP proxy rejected CONNECT')
        with context.wrap_socket(connection, server_hostname=DOMAINS[0]):
            pass
    endpoint = f'http://{ADDRESS}:18443'
    os.environ['http_proxy'] = endpoint
    os.environ['https_proxy'] = endpoint
    os.environ['HTTP_PROXY'] = endpoint
    os.environ['HTTPS_PROXY'] = endpoint
    return endpoint
