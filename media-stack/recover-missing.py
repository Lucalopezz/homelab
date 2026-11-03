#!/usr/bin/env python3
"""Reconcilia episódios monitorados com arquivos aprovados e buscas limitadas."""
import argparse
import datetime as dt
import fcntl
import json
import os
import re
import sqlite3
import tempfile
import time
from pathlib import Path, PurePosixPath

import requests

STATE = Path('/var/lib/media-recovery')
TRIAGE = Path('/var/lib/media-triage/state.sqlite3')
CONFIG = Path('/etc/media-triage/credentials.json')
APPROVED = Path('/srv/downloads/aprovados/series')
VIDEO = {'.mkv', '.mp4', '.m4v', '.webm', '.avi', '.mov', '.ts', '.m2ts'}
BACKOFF = 24 * 3600
MAX_ATTEMPTS = 3


def safe_relative(name):
    p = PurePosixPath(name)
    return bool(name and '\\' not in name and not p.is_absolute() and all(x not in ('.', '..') and not x.startswith('.') for x in p.parts))


def should_search(eid, series_id, covered, ambiguous_series, unknown_source, attempts, now):
    if unknown_source or series_id in ambiguous_series or eid in covered:
        return False
    old = attempts.get(str(eid), {})
    return old.get('count', 0) < MAX_ATTEMPTS and now - old.get('at', 0) >= BACKOFF


def classify_parse(parsed):
    if not isinstance(parsed, dict):
        return None, set()
    series = parsed.get('series') or {}
    sid = series.get('id')
    episodes = parsed.get('episodes') or []
    return sid, {x['id'] for x in episodes if x.get('id') is not None}


def explicit_episode_match(title, episode):
    """Require a season/episode or an absolute number stated in the release."""
    season, number = episode['season'], episode['episode']
    if re.search(r'(?i)(?<![a-z0-9])s0*' + str(season) + r'e0*' + str(number) + r'(?![0-9])', title):
        return True
    absolute = episode.get('absolute')
    return bool(absolute is not None and re.search(r'(?i)\[\s*ep\s*:\s*0*' + str(absolute) + r'\s*\]', title))


def save_json(path, data):
    fd, name = tempfile.mkstemp(prefix='.recovery-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


class Recovery:
    def __init__(self):
        cfg = json.loads(CONFIG.read_text())
        self.sonarr = cfg['sonarr']['url'].rstrip('/') + '/api/v3/'
        self.qbit = cfg['qbit']['url'].rstrip('/')
        self.key = cfg['sonarr']['api_key']
        self.password = cfg['qbit']['password']
        self.session = requests.Session(); self.session.trust_env = False
        self.qsession = requests.Session(); self.qsession.trust_env = False
        self.qsession.headers['Referer'] = self.qbit + '/'

    def get(self, path, **params):
        r = self.session.get(self.sonarr + path, params=params, headers={'X-Api-Key': self.key}, timeout=30)
        r.raise_for_status(); return r.json()

    def post(self, name, **payload):
        r = self.session.post(self.sonarr + 'command', json={'name': name, **payload}, headers={'X-Api-Key': self.key}, timeout=30)
        r.raise_for_status(); return r.json()

    def parse(self, title):
        try:
            return classify_parse(self.get('parse', title=title))
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None, set()
            raise

    def torrents(self):
        r = self.qsession.post(self.qbit + '/api/v2/auth/login', data={'username': 'admin', 'password': self.password}, timeout=15)
        r.raise_for_status()
        if r.text != 'Ok.': raise RuntimeError('Autenticação do qBittorrent falhou')
        r = self.qsession.get(self.qbit + '/api/v2/torrents/info', timeout=30)
        r.raise_for_status(); return r.json()

    def active_commands(self):
        return [x for x in self.get('command') if x.get('status') in ('queued', 'started') and x.get('name') in ('ManualImport', 'DownloadedEpisodesScan', 'EpisodeSearch', 'SeasonSearch', 'SeriesSearch', 'RenameFiles', 'RenameSeries', 'RescanSeries', 'RefreshSeries')]

    def approved_rows(self):
        c = sqlite3.connect('file:' + str(TRIAGE) + '?mode=ro', uri=True)
        try: return [(h, json.loads(raw)) for h, raw in c.execute("select hash,details from items where status='aprovado'")]
        finally: c.close()

    def run(self, apply=False):
        report = {'at': dt.datetime.now(dt.timezone.utc).isoformat(), 'action': 'none', 'notes': []}
        if self.active_commands():
            report['notes'].append('Comando de busca ou importação em andamento; aguardando.')
            return report
        series = [x for x in self.get('series') if x.get('monitored')]
        missing = {}
        for s in series:
            for e in self.get('episode', seriesId=s['id']):
                air = e.get('airDateUtc')
                if e.get('monitored') and not e.get('hasFile') and air:
                    try: released = dt.datetime.fromisoformat(air.replace('Z', '+00:00')) <= dt.datetime.now(dt.timezone.utc)
                    except ValueError: released = False
                    if released: missing[e['id']] = {'series_id': s['id'], 'season': e['seasonNumber'], 'episode': e['episodeNumber'], 'absolute': e.get('absoluteEpisodeNumber')}
        report['missing_count'] = len(missing)
        if not missing: return report
        covered, ambiguous, unknown = set(), set(), False
        for t in self.torrents():
            if t.get('category') != 'sonarr': continue
            if t.get('state') in ('error', 'missingFiles') or 'erro-sem-progresso' in t.get('tags', ''): continue
            sid, ids = self.parse(t.get('name', ''))
            if not sid: unknown = True
            elif not ids: ambiguous.add(sid)
            else: covered.update(ids)
        candidates = {}
        for h, d in self.approved_rows():
            title = d.get('name', '')
            if not title: continue
            root = Path(d.get('destination', ''))
            if not root.is_absolute() or root.parent != APPROVED or root.is_symlink(): continue
            sid, ids = self.parse(title)
            if not sid:
                unknown = True
                continue
            if not ids:
                ambiguous.add(sid)
                continue
            relevant = ids.intersection(missing)
            if not relevant: continue
            # Uma cópia aprovada impede uma nova busca mesmo que a associação
            # automática não seja segura; a revisão permanece visível.
            covered.update(relevant)
            marker = root / 'TRIAGEM.json'
            try:
                if marker.is_symlink() or marker.stat().st_uid != os.geteuid() or marker.stat().st_mode & 0o222: continue
                manifest = json.loads(marker.read_text())
                if manifest.get('hash') != h or manifest.get('scanner') != 'ClamAV': continue
            except (OSError, ValueError): continue
            for name, digest in d.get('files', {}).items():
                if not safe_relative(name) or Path(name).suffix.lower() not in VIDEO or manifest.get('sha256', {}).get(name) != digest: continue
                p = root
                for part in PurePosixPath(name).parts:
                    p = p / part
                    if p.is_symlink(): break
                else:
                    if not p.is_file(): continue
                    source = '/data/aprovados/series/' + p.relative_to(APPROVED).as_posix()
                    items = self.get('manualimport', folder=source, filterExistingFiles='false')
                    if len(items) != 1: continue
                    item = items[0]; mapped = item.get('episodes') or []
                    if item.get('path') != source or (item.get('series') or {}).get('id') != sid or len(mapped) != 1 or item.get('rejections'): continue
                    eid = mapped[0].get('id')
                    if eid not in relevant or missing[eid]['series_id'] != sid or not explicit_episode_match(title, missing[eid]): continue
                    candidates.setdefault(eid, {'path': source, 'folderName': item.get('folderName'), 'seriesId': sid,
                        'episodeIds': [eid], 'quality': item['quality'], 'languages': item['languages'],
                        'releaseGroup': item.get('releaseGroup'), 'indexerFlags': item.get('indexerFlags', 0),
                        'releaseType': item.get('releaseType', 'singleEpisode')})
        report['approved_candidates'] = len(candidates)
        report['ambiguous_series'] = sorted(ambiguous)
        report['unknown_source'] = unknown
        report['covered_missing_count'] = len(covered.intersection(missing))
        if unknown:
            report['notes'].append('Uma fonte não foi identificada; buscas automáticas suspensas até revisão.')
        if ambiguous:
            report['notes'].append('Há pacotes ou fontes sem episódios identificados; buscas dessas séries foram suspensas.')
        attempts_path = STATE / 'attempts.json'
        attempts = json.loads(attempts_path.read_text()) if attempts_path.exists() else {}
        now = time.time()
        if candidates:
            selected = [x for eid, x in candidates.items() if should_search('import-' + str(eid), x['seriesId'], set(), set(), False, attempts, now)][:4]
            if not selected:
                report['notes'].append('Cópias aprovadas exigem revisão após tentativas anteriores.'); return report
            if apply:
                # Reconfere comandos e episódios imediatamente antes de agir.
                if self.active_commands():
                    report['notes'].append('Outro comando começou; importação adiada.'); return report
                live = {}
                for sid in {x['seriesId'] for x in selected}:
                    live.update({x['id']: x for x in self.get('episode', seriesId=sid)})
                selected = [x for x in selected if x['episodeIds'][0] in live and not live[x['episodeIds'][0]]['hasFile']]
                if selected:
                    for x in selected:
                        key = 'import-' + str(x['episodeIds'][0]); old = attempts.get(key, {})
                        attempts[key] = {'count': old.get('count', 0) + 1, 'at': now, 'status': 'enviando'}
                    save_json(attempts_path, attempts)
                    cmd = self.post('ManualImport', importMode='copy', files=selected)
                    for x in selected: attempts['import-' + str(x['episodeIds'][0])].update(status='enviado', command=cmd.get('id'))
                    save_json(attempts_path, attempts)
                    report.update(action='import', command=cmd.get('id'), episode_ids=[x['episodeIds'][0] for x in selected])
            else: report.update(action='would_import', episode_ids=[x['episodeIds'][0] for x in selected])
            return report
        search = [eid for eid, e in missing.items() if should_search(eid, e['series_id'], covered, ambiguous, unknown, attempts, now)][:2]
        report['eligible_searches'] = search
        if not search and missing and not candidates:
            report['notes'].append('Nenhuma busca elegível agora: há fontes existentes, identificação incerta ou espera entre tentativas.')
        if search and apply:
            if self.active_commands():
                report['notes'].append('Outro comando começou; busca adiada.'); return report
            # Registrar antes da chamada evita repetir uma busca se a resposta se perder.
            for eid in search:
                old = attempts.get(str(eid), {})
                attempts[str(eid)] = {'count': old.get('count', 0) + 1, 'at': now, 'status': 'enviando'}
            save_json(attempts_path, attempts)
            cmd = self.post('EpisodeSearch', episodeIds=search)
            for eid in search: attempts[str(eid)].update(status='enviado', command=cmd.get('id'))
            save_json(attempts_path, attempts)
            report.update(action='search', command=cmd.get('id'), episode_ids=search)
        elif search: report.update(action='would_search', episode_ids=search)
        return report


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--apply', action='store_true'); args = parser.parse_args()
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE / 'recovery.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try: report = Recovery().run(apply=args.apply)
        except Exception as e:
            report = {'at': dt.datetime.now(dt.timezone.utc).isoformat(), 'action': 'error', 'reason': str(e)[:500]}
            save_json(STATE / 'status.json', report); print(json.dumps(report, ensure_ascii=False)); raise
        save_json(STATE / 'status.json', report)
        print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__': main()
