#!/usr/bin/env python3
"""Baixa uma pequena amostra do torrent oficial Debian e remove só esse teste."""
import json
import time
from check_qbittorrent import ROOT, connect, request

client = connect()
before = {item['hash'] for item in json.loads(request(client, 'torrents/info'))}
test_hash = None
request(client, 'torrents/add', {
    'urls': 'https://cdimage.debian.org/debian-cd/current/amd64/bt-cd/debian-13.7.0-amd64-netinst.iso.torrent',
    'savepath': '/srv/downloads/concluidos/lab-smoke',
    'dlLimit': str(1024 * 1024),
    'upLimit': str(64 * 1024),
    'stopped': 'false',
    'tags': 'lab-smoke',
})
try:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        items = json.loads(request(client, 'torrents/info'))
        candidates = [item for item in items
                      if item['hash'] not in before and 'lab-smoke' in item['tags'].split(', ')]
        if candidates:
            if len(candidates) != 1:
                raise RuntimeError('Mais de um torrent de teste: interromper e conferir.')
            item = candidates[0]
            test_hash = item['hash']
            if item['downloaded'] >= 4 * 1024 * 1024:
                result = {key: item[key] for key in (
                    'name', 'downloaded', 'completed', 'num_seeds', 'num_leechs', 'state')}
                (ROOT / 'state/torrent-smoke.json').write_text(json.dumps(result, indent=2) + '\n')
                print(json.dumps(result, indent=2), flush=True)
                break
        time.sleep(2)
    else:
        raise RuntimeError('Sem amostra de 4 MiB dentro do prazo; conferir peers e trackers.')
finally:
    if test_hash is not None:
        request(client, 'torrents/stop', {'hashes': test_hash})
        request(client, 'torrents/delete', {'hashes': test_hash, 'deleteFiles': 'true'})
        print('Torrent de teste parado e removido com seus dados.', flush=True)
