#!/usr/bin/env python3
"""Inicializa diretórios e configurações dentro da VM; nunca no Fedora."""
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import xml.etree.ElementTree as ET

if os.geteuid() != 0 or os.uname().nodename != 'lab-downloads':
    raise SystemExit('Executar com sudo somente na VM lab-downloads.')
root = Path('/opt/media-stack')
credentials = json.loads((root / 'credentials.json').read_text())

def run(*args):
    subprocess.run(args, check=True)

for name, identifier in [('midia', 1100), ('triagem', 1101)]:
    try:
        group = grp.getgrnam(name)
        assert group.gr_gid == identifier
    except KeyError:
        run('groupadd', '--gid', str(identifier), name)
    try:
        user = pwd.getpwnam(name)
        assert user.pw_uid == identifier
    except KeyError:
        run('useradd', '--system', '--uid', str(identifier), '--gid', name,
            '--home-dir', '/nonexistent', '--no-create-home', '--shell', '/usr/sbin/nologin', name)
run('usermod', '-aG', 'torrent,midia,clamav', 'triagem')
run('usermod', '-aG', 'midia', 'coleta')

def directory(path, uid, gid, mode):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    os.chown(path, uid, gid)
    path.chmod(mode)

directory('/srv/downloads/recebidos', 1001, 1001, 0o750)
directory('/srv/downloads/aprovados', 0, 0, 0o755)
for name in ['series', 'filmes', 'manuais', 'STATUS']:
    directory('/srv/downloads/aprovados/' + name, 1101, 1100, 0o2750)
directory('/srv/downloads/aprovados/.em-analise', 1101, 1101, 0o700)
for name in ['series', 'filmes']:
    directory('/srv/downloads/biblioteca/' + name, 1100, 1100, 0o2750)
directory('/var/lib/media-triage', 1101, 1101, 0o700)
scan_lock = Path('/var/lib/media-triage/clamav-scan.lock')
scan_lock.touch(exist_ok=True)
os.chown(scan_lock, 1101, 1101)
scan_lock.chmod(0o440)
directory('/etc/media-triage', 0, 1101, 0o750)

triage = {'qbit': {'url': 'http://192.168.250.10:8080', 'password': credentials['qbit_password']}}
for app, port in [('sonarr', 8989), ('radarr', 7878), ('prowlarr', 9696)]:
    directory(root / 'appdata' / app, 1100, 1100, 0o700)
    triage[app] = {'url': f'http://192.168.250.10:{port}', 'api_key': credentials[app + '_key']}
    target = root / 'appdata' / app / 'config.xml'
    if not target.exists():
        document = ET.Element('Config')
        for name, value in {'BindAddress': '*', 'Port': str(port), 'EnableSsl': 'False',
                            'LaunchBrowser': 'False', 'AuthenticationMethod': 'Forms',
                            'AuthenticationRequired': 'Enabled', 'ApiKey': credentials[app + '_key'],
                            'UrlBase': '', 'LogLevel': 'info', 'UpdateMechanism': 'Docker'}.items():
            ET.SubElement(document, name).text = value
        ET.ElementTree(document).write(target, encoding='unicode')
        os.chown(target, 1100, 1100)
        target.chmod(0o600)
directory(root / 'appdata' / 'bazarr', 1100, 1100, 0o700)
bazarr_config = root / 'appdata/bazarr/config/config.yaml'
directory(bazarr_config.parent, 1100, 1100, 0o700)
if not bazarr_config.exists():
    import yaml
    bazarr = {
        'auth': {'apikey': credentials['bazarr_key'], 'type': 'form',
                 'username': credentials['username'],
                 'password': hashlib.md5(credentials['password'].encode()).hexdigest()},
        'general': {'use_sonarr': True, 'use_radarr': True, 'auto_update': False,
                    'enabled_providers': ['animetosho', 'gestdown', 'yifysubtitles'],
                    'serie_default_enabled': True, 'serie_default_profile': 1,
                    'movie_default_enabled': True, 'movie_default_profile': 1,
                    'use_postprocessing': False, 'concurrent_jobs': 1},
        'sonarr': {'ip': 'sonarr', 'port': 8989, 'apikey': credentials['sonarr_key'], 'base_url': '/'},
        'radarr': {'ip': 'radarr', 'port': 7878, 'apikey': credentials['radarr_key'], 'base_url': '/'},
    }
    bazarr_config.write_text(yaml.safe_dump(bazarr, allow_unicode=True))
    os.chown(bazarr_config, 1100, 1100)
    bazarr_config.chmod(0o600)
directory(root / 'appdata' / 'seerr', 1000, 1000, 0o700)
target = Path('/etc/media-triage/credentials.json')
target.write_text(json.dumps(triage, indent=2) + '\n')
os.chown(target, 0, 1101)
target.chmod(0o640)

# A conta de coleta passa a enxergar apenas resultados aprovados.
ssh_target = Path('/etc/ssh/sshd_config.d/00-lab-downloads.conf')
ssh = ssh_target.read_text().replace('ChrootDirectory /srv/downloads\n',
    'ChrootDirectory /srv/downloads/aprovados\n').replace(
    'ForceCommand internal-sftp -R -d /concluidos', 'ForceCommand internal-sftp -R -d /')
ssh_target.write_text(ssh)
run('/usr/sbin/sshd', '-t')
run('systemctl', 'reload', 'ssh')

for name in ['lab-media.service', 'media-triage.service', 'media-triage.timer',
             'media-download-watch.service', 'media-download-watch.timer']:
    run('install', '-m', '644', str(root / 'config' / name), '/etc/systemd/system/' + name)
run('install', '-m', '644', str(root / 'config/clamd.conf'), '/etc/clamav/clamd.conf')
directory('/etc/systemd/system/clamav-daemon.service.d', 0, 0, 0o755)
Path('/etc/systemd/system/clamav-daemon.service.d/lab.conf').write_text(
    '[Service]\nMemoryMax=3G\nCPUQuota=100%\n')
run('systemctl', 'daemon-reload')
print('Diretórios, separação de permissões e unidades de triagem preparados.')
