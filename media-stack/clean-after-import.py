#!/usr/bin/env python3
"""Aguarda a publicação dos pedidos atuais e inicia limpeza de cópias conferidas."""

import datetime as dt
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'state'
COMMAND_ID = 5238
TARGETS = {
    'Family Guy': {
        'series_id': 1,
        'seasons': {21, 22, 23, 24},
        'minimum': 68,
        'folder': 'Family Guy',
    },
    'Bleach': {
        'series_id': 2,
        'seasons': {17},
        'minimum': 50,
        'folder': 'Bleach',
    },
    'Star Wars: The Clone Wars': {
        'series_id': 3,
        'seasons': set(range(1, 8)),
        'minimum': 133,
        'folder': 'Star Wars - The Clone Wars',
    },
}


def target_status(episodes, items, folder, seasons, minimum, now):
    """Somente episódios confirmados nos dois catálogos satisfazem a espera."""
    expected = []
    for e in episodes:
        if e.get('seasonNumber') not in seasons or not e.get('airDateUtc'):
            continue
        air = dt.datetime.fromisoformat(e['airDateUtc'].replace('Z', '+00:00'))
        if air <= now:
            expected.append(e)
    if len(expected) < minimum:
        raise ValueError('Lista de episódios incompleta para ' + folder)
    prefix = '/lab-media/series/' + folder + '/'
    present = {
        (x.get('ParentIndexNumber'), x.get('IndexNumber'))
        for x in items
        if x.get('Path', '').startswith(prefix)
    }
    not_imported = [e for e in expected if not e.get('hasFile')]
    not_published = [
        e
        for e in expected
        if (e['seasonNumber'], e['episodeNumber']) not in present
    ]
    return {
        'expected': len(expected),
        'sonarr_missing': len(not_imported),
        'jellyfin_missing': len(not_published),
    }


def write_status(report):
    report = dict(
        report,
        at=dt.datetime.now(dt.timezone.utc).isoformat(),
        pid=os.getpid(),
    )
    fd, name = tempfile.mkstemp(prefix='.cleanup-wait-', dir=STATE)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, STATE / 'cleanup-after-import-status.json')
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    creds = json.loads((ROOT / 'secrets/media-stack.json').read_text())
    jelly = json.loads((ROOT / 'secrets/jellyfin-host.json').read_text())
    session = requests.Session()
    session.trust_env = False
    sonarr_headers = {'X-Api-Key': creds['sonarr_key']}
    jelly_headers = {
        'Authorization': (
            'MediaBrowser Client="Lab", Device="Fedora", '
            'DeviceId="cleanup-wait", Version="1", Token="'
            + jelly['api_key']
            + '"'
        )
    }

    def get(url, headers, params=None):
        r = session.get(
            url,
            headers=headers,
            params=params,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    with (STATE / 'cleanup-after-import.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            try:
                command = get(
                    'http://192.168.250.10:8989/api/v3/command/'
                    + str(COMMAND_ID),
                    sonarr_headers,
                )
                status = command.get('status')
                if status in ('failed', 'aborted', 'cancelled'):
                    write_status(
                        {
                            'state': 'erro',
                            'reason': 'A importação não terminou com sucesso.',
                            'command': status,
                        }
                    )
                    return 1
                if status != 'completed':
                    write_status(
                        {
                            'state': 'aguardando_importacao',
                            'command': status,
                            'progress': command.get('message'),
                        }
                    )
                else:
                    data = get(
                        'http://127.0.0.1:8096/Items',
                        jelly_headers,
                        {
                            'Recursive': 'true',
                            'IncludeItemTypes': 'Episode',
                            'Fields': 'Path,ParentIndexNumber,IndexNumber',
                            'Limit': 10000,
                        },
                    )
                    if len(data.get('Items', [])) != data.get('TotalRecordCount'):
                        raise ValueError('Resposta do catálogo incompleta')
                    targets = {}
                    for title, spec in TARGETS.items():
                        episodes = get(
                            'http://192.168.250.10:8989/api/v3/episode',
                            sonarr_headers,
                            {'seriesId': spec['series_id']},
                        )
                        targets[title] = target_status(
                            episodes,
                            data['Items'],
                            spec['folder'],
                            spec['seasons'],
                            spec['minimum'],
                            dt.datetime.now(dt.timezone.utc),
                        )
                    sync = json.loads((ROOT / 'jellyfin/state/last-run.json').read_text())
                    active = subprocess.run(
                        [
                            'systemctl',
                            'show',
                            'lab-jellyfin-sync.service',
                            '-p',
                            'ActiveState',
                            '--value',
                        ],
                        text=True,
                        capture_output=True,
                        timeout=10,
                        check=True,
                    ).stdout.strip()
                    commands = get('http://192.168.250.10:8989/api/v3/command', sonarr_headers)
                    ongoing = [
                        x
                        for x in commands
                        if x.get('status') in ('queued', 'started')
                        and x.get('name')
                        in ('ManualImport', 'DownloadedEpisodesScan', 'RenameFiles')
                    ]
                    missing = any(
                        v['sonarr_missing'] or v['jellyfin_missing']
                        for v in targets.values()
                    )
                    if (
                        missing
                        or sync.get('pending') != 0
                        or sync.get('held')
                        or active != 'inactive'
                        or ongoing
                    ):
                        write_status(
                            {
                                'state': 'aguardando_publicacao',
                                'targets': targets,
                                'sync_pending': sync.get('pending'),
                                'sync_held': len(sync.get('held') or []),
                                'sync_service': active,
                            }
                        )
                    else:
                        write_status({'state': 'limpando', 'targets': targets})
                        log = STATE / 'cleanup-after-import.log'
                        try:
                            with log.open('a', encoding='utf-8') as out:
                                r = subprocess.run(
                                    [
                                        'ionice',
                                        '-c',
                                        '3',
                                        sys.executable,
                                        str(ROOT / 'media-stack/clean-published-copies.py'),
                                        '--apply',
                                    ],
                                    cwd=ROOT,
                                    stdout=out,
                                    stderr=subprocess.STDOUT,
                                )
                        except Exception as e:
                            write_status(
                                {
                                    'state': 'erro',
                                    'reason': 'Falha ao iniciar limpeza: '
                                    + type(e).__name__,
                                    'targets': targets,
                                }
                            )
                            return 1
                        write_status(
                            {
                                'state': 'concluido'
                                if r.returncode == 0
                                else 'erro',
                                'exit_code': r.returncode,
                                'targets': targets,
                            }
                        )
                        return r.returncode
            except Exception as e:
                write_status({'state': 'aguardando_consulta', 'reason': type(e).__name__})
            time.sleep(60)


if __name__ == '__main__':
    sys.exit(main())
