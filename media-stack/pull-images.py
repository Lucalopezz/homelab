#!/usr/bin/env python3
import concurrent.futures
import json
import os
from pathlib import Path
import re
import subprocess

if os.geteuid() != 0 or os.uname().nodename != 'lab-downloads':
    raise SystemExit('Executar somente na VM, com sudo.')
root = Path('/opt/media-stack')
os.umask(0o077)
if (root / '.env').exists():
    raise SystemExit('.env já existe: preservar a instalação e revisar antes de atualizar imagens.')
images = json.loads((root / 'images.lock.json').read_text())
repositories = {'SONARR': 'lscr.io/linuxserver/sonarr',
                'RADARR': 'lscr.io/linuxserver/radarr',
                'PROWLARR': 'lscr.io/linuxserver/prowlarr',
                'BAZARR': 'lscr.io/linuxserver/bazarr',
                'SEERR': 'ghcr.io/seerr-team/seerr'}
if set(images) != set(repositories):
    raise SystemExit('Manifesto de imagens incompleto ou com serviços inesperados.')
for name, reference in images.items():
    if not re.fullmatch(re.escape(repositories[name]) + r'@sha256:[0-9a-f]{64}', reference):
        raise SystemExit('Referência inválida no manifesto: ' + name)
credentials = json.loads((root / 'credentials.json').read_text())
if not re.fullmatch(r'[0-9a-f]{64}', credentials['seerr_key']):
    raise SystemExit('Chave Seerr inválida; não gerar .env.')

def pull(item):
    name, image = item
    subprocess.run(['docker', 'pull', image], check=True)
    data = json.loads(subprocess.check_output(['docker', 'image', 'inspect', image]))[0]
    if (data['Os'], data['Architecture']) != ('linux', 'amd64'):
        raise RuntimeError('Arquitetura inesperada: ' + name)
    print(name, 'imagem obtida e fixada por digest', flush=True)
    return name + '_IMAGE', image

with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
    locked = dict(executor.map(pull, images.items()))
locked['SEERR_API_KEY'] = credentials['seerr_key']
with (root / '.env').open('x') as target:
    target.write(''.join(f'{key}={value}\n' for key, value in locked.items()))
subprocess.run(['docker', 'compose', 'config', '--quiet'], cwd=root, check=True)
subprocess.run(['systemctl', 'enable', '--now', 'lab-media.service'], check=True)
