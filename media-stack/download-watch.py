#!/usr/bin/env python3
"""Retém downloads sem progresso; nunca remove dados ou retoma itens pausados."""
import fcntl
import json
from pathlib import Path
import time

import requests

STATE = Path('/var/lib/media-download-watch')
TIMEOUT = 15 * 60
TAG = 'erro-sem-progresso'
ACTIVE = {'downloading', 'stalledDL', 'metaDL'}
CATEGORIES = {'sonarr', 'radarr', 'manual', ''}


def observe(torrents, previous, now):
    """Só conta tempo observado em estado de download ativo, nunca tempo na fila."""
    current, stalled = {}, []
    for torrent in torrents:
        if (torrent['category'] not in CATEGORIES or torrent['state'] not in ACTIVE
                or torrent['progress'] >= 1):
            continue
        key = torrent['hash']
        progress = [torrent['downloaded'], torrent['progress'], torrent['size']]
        old = previous.get(key, {})
        # Uma lacuna de observação (VM parada, timer falhou) reinicia a contagem.
        continuous = 0 <= now - old.get('seen', -1e12) <= 180
        since = old.get('since', now) if continuous and old.get('progress') == progress else now
        current[key] = {'progress': progress, 'since': since, 'seen': now}
        if now - since >= TIMEOUT and torrent.get('dlspeed', 0) == 0:
            stalled.append(key)
    return current, stalled


def main():
    STATE.mkdir(mode=0o700, exist_ok=True)
    with (STATE / 'watch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        cfg = json.loads(Path('/etc/media-triage/credentials.json').read_text())['qbit']
        session = requests.Session()
        session.trust_env = False
        session.headers['Referer'] = cfg['url'] + '/'
        base = cfg['url'] + '/api/v2/'
        login = session.post(base + 'auth/login', data={'username': 'admin', 'password': cfg['password']}, timeout=10)
        login.raise_for_status()
        if login.text != 'Ok.':
            raise RuntimeError('Login do qBittorrent falhou')

        def get_torrents():
            response = session.get(base + 'torrents/info', timeout=15)
            response.raise_for_status()
            return response.json()

        path = STATE / 'observations.json'
        previous = json.loads(path.read_text()) if path.exists() else {}
        current, stalled = observe(get_torrents(), previous, time.time())
        # Reconfere progresso/estado imediatamente antes de qualquer parada.
        fresh = {t['hash']: t for t in get_torrents()} if stalled else {}
        for key in stalled:
            torrent = fresh.get(key)
            if (not torrent or torrent['state'] not in ACTIVE or torrent.get('dlspeed', 0) > 0
                    or torrent['progress'] >= 1
                    or [torrent['downloaded'], torrent['progress'], torrent['size']] != current[key]['progress']):
                current.pop(key, None)
                continue
            # A etiqueta primeiro torna visível inclusive uma falha na parada.
            for route, data in [('torrents/addTags', {'hashes': key, 'tags': TAG}),
                                ('torrents/stop', {'hashes': key})]:
                session.post(base + route, data=data, timeout=15).raise_for_status()
            current.pop(key, None)
            print(json.dumps({'hash': key, 'status': TAG, 'idle_minutes': 15}, ensure_ascii=False), flush=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(current) + '\n')
        temp.replace(path)


if __name__ == '__main__':
    main()
