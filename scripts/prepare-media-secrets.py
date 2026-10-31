#!/usr/bin/env python3
import json
import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
os.umask(0o077)
path = root / 'secrets/media-stack.json'
if path.exists():
    raise SystemExit('Credenciais já existem; não serão substituídas.')
config = {'username': 'lab', 'password': secrets.token_urlsafe(24),
          'sonarr_key': secrets.token_hex(16), 'radarr_key': secrets.token_hex(16),
          'prowlarr_key': secrets.token_hex(16), 'seerr_key': secrets.token_hex(32),
          'bazarr_key': secrets.token_hex(16),
          'qbit_password': (root / 'secrets/qbittorrent-password').read_text().strip()}
path.write_text(json.dumps(config, indent=2) + '\n')
print('Credenciais geradas em secrets/media-stack.json, sem exibir valores.')
