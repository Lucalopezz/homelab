#!/usr/bin/env python3
"""Prepara arquivos locais. Não configura libvirt/rede/serviços do Fedora."""
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[1]
if ROOT != Path('/mnt/dados/lab'):
    raise SystemExit('Este laboratório está fixado em /mnt/dados/lab.')
os.chdir(ROOT)
os.umask(0o077)
if (ROOT / 'state/host-configured').exists():
    raise SystemExit('Host já configurado: não recriar o seed de uma VM em uso.')

for directory in ('secrets', 'state', 'backups', 'images', 'disks', 'cloud-init'):
    (ROOT / directory).mkdir(exist_ok=True)
for directory in ('secrets', 'state', 'backups'):
    (ROOT / directory).chmod(0o700)

image = ROOT / 'images/debian-13-genericcloud-amd64.qcow2'
if not image.exists():
    part = image.with_suffix('.qcow2.part')
    if not part.exists():
        raise SystemExit('Primeiro baixe a imagem oficial do Debian indicada no README.')
    candidate = part
else:
    candidate = image
checksums = (ROOT / 'images/SHA512SUMS').read_text().splitlines()
expected = [line.split()[0] for line in checksums
            if line.split()[-1].lstrip('*') == image.name]
if len(expected) != 1:
    raise SystemExit('Checksum da imagem ausente ou ambíguo.')
digest = hashlib.sha512()
with candidate.open('rb') as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b''):
        digest.update(chunk)
if digest.hexdigest() != expected[0]:
    raise SystemExit('SHA512 incorreto: a imagem não será usada.')
if candidate != image:
    candidate.rename(image)
print('SHA512 da imagem oficial: OK')

# Não recriar ou sobrescrever discos existentes.
system = ROOT / 'disks/system.qcow2'
if not system.exists():
    staging = system.with_suffix('.qcow2.preparing')
    if staging.exists():
        raise SystemExit(f'Preparação anterior incompleta: confira {staging}')
    subprocess.run(['qemu-img', 'convert', '-f', 'qcow2', '-O', 'qcow2',
                    str(image), str(staging)], check=True)
    subprocess.run(['qemu-img', 'resize', str(staging), '20G'], check=True)
    staging.rename(system)
data = ROOT / 'disks/downloads.qcow2'
if not data.exists():
    subprocess.run(['qemu-img', 'create', '-f', 'qcow2', str(data), '400G'], check=True)

keys = {}
for account in ('admin', 'coleta'):
    key = ROOT / f'secrets/{account}_ed25519'
    if not key.exists():
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key),
                        '-C', f'lab-downloads-{account}'], check=True)
    keys[account] = key.with_suffix('.pub').read_text().strip()

password_file = ROOT / 'secrets/qbittorrent-password'
if not password_file.exists():
    password_file.write_text(secrets.token_urlsafe(24) + '\n')
password = password_file.read_text().strip()
salt = secrets.token_bytes(16)
password_hash = base64.b64encode(salt).decode() + ':' + base64.b64encode(
    hashlib.pbkdf2_hmac('sha512', password.encode(), salt, 100000, dklen=64)).decode()

qbit = r'''[LegalNotice]
Accepted=true

[BitTorrent]
Session\DefaultSavePath=/srv/downloads/concluidos
Session\TempPath=/srv/downloads/incompletos
Session\TempPathEnabled=true
Session\QueueingSystemEnabled=true
Session\MaxActiveDownloads=4
Session\MaxActiveTorrents=6
Session\MaxActiveUploads=2
Session\GlobalUPSpeedLimit=256
Session\LSDEnabled=false

[Network]
PortForwardingEnabled=false

[Preferences]
WebUI\Address=192.168.250.10
WebUI\Port=8080
WebUI\Username=admin
WebUI\LocalHostAuth=true
WebUI\AuthSubnetWhitelistEnabled=false
WebUI\CSRFProtection=true
WebUI\HostHeaderValidation=true
WebUI\UseUPnP=false
WebUI\Password_PBKDF2="@ByteArray(PASSWORD_HASH)"
'''.replace('PASSWORD_HASH', password_hash)

ssh_config = '''PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
PubkeyAuthentication yes

Match User coleta
    ChrootDirectory /srv/downloads
    ForceCommand internal-sftp -R -d /concluidos
    AuthenticationMethods publickey
    DisableForwarding yes
    PermitTTY no

Match all
'''

def guest_file(path, content, mode='0644', defer=False):
    return {'path': path, 'owner': 'root:root', 'permissions': mode,
            'content': content, 'defer': defer}

config = {
    'hostname': 'lab-downloads',
    'manage_etc_hosts': True,
    'timezone': 'America/Sao_Paulo',
    'disable_root': True,
    'ssh_pwauth': False,
    'users': [
        {'name': 'labadmin', 'shell': '/bin/bash', 'lock_passwd': True,
         'sudo': ['ALL=(ALL) NOPASSWD:ALL'], 'ssh_authorized_keys': [keys['admin']]},
        {'name': 'torrent', 'shell': '/usr/sbin/nologin', 'lock_passwd': True},
        {'name': 'coleta', 'shell': '/bin/sh', 'lock_passwd': True,
         'groups': ['torrent'], 'ssh_authorized_keys': [keys['coleta']]},
    ],
    'package_update': True,
    'packages': ['qbittorrent-nox', 'openssh-server', 'curl', 'e2fsprogs'],
    'write_files': [
        guest_file('/usr/local/sbin/lab-downloads-setup',
                   (ROOT / 'cloud-init/setup-guest.sh').read_text(), '0700'),
        guest_file('/etc/ssh/sshd_config.d/00-lab-downloads.conf', ssh_config),
        guest_file('/home/torrent/.config/qBittorrent/qBittorrent.conf', qbit, '0600', True),
        guest_file('/etc/systemd/system/qbittorrent-nox@torrent.service.d/lab.conf',
                   '[Unit]\nRequiresMountsFor=/srv/downloads\n'
                   'AssertPathIsMountPoint=/srv/downloads\n\n'
                   '[Service]\nUMask=0027\nNoNewPrivileges=yes\nPrivateTmp=yes\n'),
    ],
    'runcmd': [['/usr/local/sbin/lab-downloads-setup']],
}
(ROOT / 'cloud-init/user-data').write_text('#cloud-config\n' + json.dumps(config, indent=2) + '\n')
metadata = ROOT / 'cloud-init/meta-data'
if not metadata.exists():
    metadata.write_text('instance-id: lab-downloads-' + secrets.token_hex(8) +
                        '\nlocal-hostname: lab-downloads\n')
(ROOT / 'cloud-init/network-config').write_text('''version: 2
ethernets:
  downloads:
    match:
      macaddress: "52:54:00:dd:00:10"
    set-name: ens3
    dhcp4: true
    dhcp6: false
    accept-ra: false
''')
subprocess.run(['genisoimage', '-quiet', '-output', str(ROOT / 'disks/seed.iso'),
                '-volid', 'cidata', '-joliet', '-rock',
                'user-data', 'meta-data', 'network-config'], cwd=ROOT / 'cloud-init', check=True)
print('Discos, chaves e seed de instalação preparados no HD; VM ainda não iniciada.')
