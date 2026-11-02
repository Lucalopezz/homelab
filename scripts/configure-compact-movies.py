#!/usr/bin/env python3
"""Cria um perfil opcional no Radarr, sem mudar definições globais de qualidade."""
import argparse
import copy
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
PROFILE = 'Lab - filmes compactos (720p ou SD)'
FORMAT = 'Lab - tamanho compacto ate 1.8 GB'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Criar o formato e o perfil no Radarr existente')
    args = parser.parse_args()
    cfg = json.loads((ROOT / 'secrets/media-stack.json').read_text())
    session = requests.Session()
    session.trust_env = False
    session.headers['X-Api-Key'] = cfg['radarr_key']

    def api(method, route, payload=None):
        r = session.request(method, 'http://192.168.250.10:7878/api/v3/' + route,
                            json=payload, timeout=30)
        if not r.ok:
            raise RuntimeError(f'Radarr {method} {route}: HTTP {r.status_code}')
        return r.json() if r.content else None

    profiles = api('GET', 'qualityprofile')
    if any(p['name'] == PROFILE for p in profiles):
        raise SystemExit('Já existe um perfil com esse nome; revisar sem sobrescrever.')
    base = next(p for p in profiles if p['name'] == 'Lab - 1080p preferido, 720p alternativa')
    formats = api('GET', 'customformat')
    if any(f['name'] == FORMAT for f in formats):
        raise SystemExit('Já existe um formato com esse nome; revisar sem sobrescrever.')
    spec = {'name': 'Tamanho pequeno', 'implementation': 'SizeSpecification',
            'negate': False, 'required': True,
            'fields': [{'name': 'min', 'value': 0}, {'name': 'max', 'value': 1.8}]}
    custom = {'name': FORMAT, 'includeCustomFormatWhenRenaming': False, 'specifications': [spec]}
    profile = copy.deepcopy(base)
    profile.pop('id', None)
    profile.update(name=PROFILE, upgradeAllowed=False, cutoff=6,
                   minFormatScore=100, cutoffFormatScore=100, minUpgradeFormatScore=1)
    allowed = {'WEBDL-720p', 'WEBRip-720p', 'Bluray-720p', 'WEBDL-480p',
               'WEBRip-480p', 'Bluray-480p', 'Bluray-576p', 'DVD'}

    def select(item):
        if item.get('items'):
            item['items'] = [select(x) for x in item['items']]
            item['allowed'] = any(x['allowed'] for x in item['items'])
        else:
            item['allowed'] = item.get('quality', {}).get('name') in allowed
        return item

    profile['items'] = [select(x) for x in profile['items']]
    for item in profile['formatItems']:
        item['score'] = -10000 if item['name'] == 'Lab - rejeitar pacotes suspeitos' else 0
    if not args.apply:
        print(json.dumps({'profile': PROFILE, 'size_limit_in_radarr_GB': 1.8,
                          'upgradeAllowed': False, 'qualities': sorted(allowed)}, ensure_ascii=False))
        return
    custom = api('POST', 'customformat', custom)
    profile['formatItems'].append({'format': custom['id'], 'name': custom['name'], 'score': 100})
    profile = api('POST', 'qualityprofile', profile)
    print(json.dumps({'profile_id': profile['id'], 'name': profile['name'], 'format_id': custom['id']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
