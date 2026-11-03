#!/usr/bin/env python3
"""Consulta somente leitura da triagem, executada na VM pelo painel."""
import json
import os
import re
import sqlite3
import subprocess

db = sqlite3.connect('file:/var/lib/media-triage/state.sqlite3?mode=ro', uri=True)
items = []
for torrent_hash, status, raw, updated in db.execute('SELECT hash,status,details,updated FROM items ORDER BY updated DESC'):
    details = json.loads(raw)
    items.append({'hash': torrent_hash, 'status': status, 'name': details.get('name', ''),
                  'phase': details.get('phase'), 'file': details.get('file'),
                  'phase_started_at': details.get('phase_started_at'),
                  'reason': details.get('reason') or details.get('import_error'),
                  'destination': details.get('destination'), 'updated': updated})

show = subprocess.run(['systemctl', 'show', 'media-triage.service', '-p', 'ActiveState', '-p', 'SubState', '-p', 'MainPID'], capture_output=True, text=True, check=True)
service = dict(line.split('=', 1) for line in show.stdout.splitlines() if '=' in line)
ps = subprocess.run(['ps', '-eo', 'pid,stat,args'], capture_output=True, text=True, check=True).stdout.splitlines()
active = []
for line in ps:
    if 'clamdscan --' in line or 'ffprobe -v' in line:
        match = re.search(r'/srv/downloads/aprovados/\.em-analise/([0-9a-fA-F]{40,64})/([^\n]+)', line)
        if match:
            active.append({'hash': match.group(1), 'file': match.group(2),
                           'phase': 'antivírus' if 'clamdscan --' in line else 'validação de mídia'})
pid = service.get('MainPID', '0')
if pid.isdecimal() and pid != '0':
    try:
        for fd in os.listdir('/proc/' + pid + '/fd'):
            try:
                target = os.readlink('/proc/' + pid + '/fd/' + fd)
            except OSError:
                continue
            match = re.match(r'/srv/downloads/aprovados/\.em-analise/([0-9a-fA-F]{40,64})/(.+)', target)
            if match and not any(x['hash'] == match.group(1) for x in active):
                active.append({'hash': match.group(1), 'file': match.group(2), 'phase': 'arquivo aberto pela triagem'})
    except OSError:
        pass
try:
    with open('/var/lib/media-recovery/status.json', encoding='utf-8') as f:
        recovery = json.load(f)
except (OSError, ValueError):
    recovery = None
print(json.dumps({'items': items, 'service': service, 'active': active, 'recovery': recovery}, ensure_ascii=False))
