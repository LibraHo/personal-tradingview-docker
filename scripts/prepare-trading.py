"""Run locally on NAS before the first trading deployment. Does not change OpenD."""
import argparse
import ipaddress
import os
import secrets
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--host', required=True, help='NAS IP or DNS name included in the certificate')
parser.add_argument('--root', default='.')
args = parser.parse_args()
root = Path(args.root).resolve()
tls, data = root / 'trade-tls', root / 'trade-data'
tls.mkdir(mode=0o700, exist_ok=True)
data.mkdir(mode=0o700, exist_ok=True)
try:
    ipaddress.ip_address(args.host)
    san = 'IP:' + args.host
except ValueError:
    import re
    if not re.fullmatch(r'[A-Za-z0-9.-]+', args.host):
        raise SystemExit('Invalid host')
    san = 'DNS:' + args.host
if not (tls / 'cert.pem').exists():
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-sha256', '-days', '365',
        '-nodes', '-keyout', str(tls / 'key.pem'), '-out', str(tls / 'cert.pem'),
        '-subj', '/CN=' + args.host, '-addext', 'subjectAltName=' + san,
        '-addext', 'basicConstraints=critical,CA:FALSE', '-addext', 'extendedKeyUsage=serverAuth'],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.chmod(tls / 'key.pem', 0o600)
if not (data / 'auth.json').exists() and not (data / 'setup-code.txt').exists():
    fd = os.open(str(data / 'setup-code.txt'), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(secrets.token_urlsafe(32))
print('Prepared HTTPS certificate and one-time setup code. No OpenD changes.')
subprocess.run(['openssl', 'x509', '-in', str(tls / 'cert.pem'), '-noout', '-fingerprint', '-sha256'], check=True)
