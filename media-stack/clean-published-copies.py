#!/usr/bin/env python3
"""Remove somente vídeos recebidos já confirmados na biblioteca do Jellyfin.

Uso: ionice -c 3 python3 media-stack/clean-published-copies.py --apply
Sem --apply, apenas lista candidatos. Cada remoção encerra o compartilhamento
do torrent; outros arquivos do torrent e cópias aprovadas são preservados.
"""
import argparse
import fcntl
import hashlib
import json
import os
import select
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from check_qbittorrent import connect, request

VIDEO = {'.mkv', '.mp4', '.m4v', '.webm', '.avi', '.mov', '.ts', '.m2ts'}
SSH = ['ssh', '-F', str(ROOT / 'config/ssh_config'), '-o', 'StrictHostKeyChecking=yes',
       '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', 'lab-downloads-admin']


def safe_name(name):
    p = PurePosixPath(name)
    return bool(name and not p.is_absolute() and all(x not in ('.', '..') for x in p.parts))


def videos(files):
    return [(n, digest) for n, digest in files.items() if Path(n).suffix.lower() in VIDEO]


def guest_rows():
    code = '''import sqlite3,json\nc=sqlite3.connect("file:/var/lib/media-triage/state.sqlite3?mode=ro",uri=True)\nprint(json.dumps(c.execute("select hash,details from items where status='aprovado'").fetchall()))\n'''
    r = subprocess.run(SSH + ['sudo -n python3 -'], input=code, capture_output=True,
                       text=True, timeout=30, check=True)
    return [(h, json.loads(raw)) for h, raw in json.loads(r.stdout)]


def catalog():
    key = json.loads((ROOT / 'secrets/jellyfin-host.json').read_text())['api_key']
    headers = {'Authorization': 'MediaBrowser Client="Lab", Device="Fedora", DeviceId="lab-cleanup", Version="1", Token="' + key + '"'}
    url = 'http://127.0.0.1:8096/Items?Recursive=true&IncludeItemTypes=Episode,Movie&Fields=Path&Limit=10000'
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(urllib.request.Request(url, headers=headers), timeout=30) as r:
        data = json.load(r)
    if len(data['Items']) != data['TotalRecordCount']:
        raise RuntimeError('Catálogo veio incompleto')
    return {x.get('Path') for x in data['Items']}


def stamp(st):
    return [st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]


def verify_published(name, record):
    base = ROOT / 'jellyfin/biblioteca'
    if not safe_name(name) or not name.startswith(('filmes/', 'series/')):
        raise ValueError('Caminho publicado inválido')
    p = base
    for part in PurePosixPath(name).parts:
        p = p / part
        if p.is_symlink():
            raise ValueError('Link no caminho publicado')
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as f:
        before = stamp(os.fstat(f.fileno()))
        if before != record.get('stamp'):
            raise ValueError('Arquivo publicado mudou')
        digest = hashlib.sha256()
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
        if stamp(os.fstat(f.fileno())) != before or stamp(p.stat()) != before:
            raise ValueError('Arquivo publicado mudou durante a leitura')
    if digest.hexdigest() != record['sha256']:
        raise ValueError('Arquivo publicado não corresponde ao registro')
    return p, before


WORKER = r'''import fcntl,hashlib,json,os,pwd,sqlite3,stat,sys
from pathlib import Path
arg=json.loads(sys.argv[1]);h=arg['hash'];name=arg['name'];expected=arg['digest'];base=Path(arg['base']);p=base/name
assert len(h)==40 and all(c in '0123456789abcdef' for c in h)
lock=open('/var/lib/media-triage/'+h+'.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
assert all(not x.is_symlink() for x in [base,*[base.joinpath(*Path(name).parts[:i]) for i in range(1,len(Path(name).parts)+1)]])
def approved():
 c=sqlite3.connect('file:/var/lib/media-triage/state.sqlite3?mode=ro',uri=True);row=c.execute('select status,details from items where hash=?',(h,)).fetchone();c.close()
 assert row and row[0]=='aprovado';d=json.loads(row[1]);assert d['files'][name]==expected
 root=Path(d['destination']);assert root.is_dir() and not root.is_symlink()
 marker=root/'TRIAGEM.json';s=marker.stat(follow_symlinks=False);assert stat.S_ISREG(s.st_mode) and s.st_uid==pwd.getpwnam('triagem').pw_uid and s.st_mode & 0o222==0
 m=json.loads(marker.read_text());assert m['hash']==h and m['sha256'][name]==expected and m['scanner']=='ClamAV'
approved()
fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW);before=os.fstat(fd);assert stat.S_ISREG(before.st_mode)
x=hashlib.sha256()
with os.fdopen(fd,'rb') as f:
 for block in iter(lambda:f.read(1048576),b''):x.update(block)
 after=os.fstat(f.fileno())
def stamp(s):return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
assert stamp(before)==stamp(after)==stamp(p.stat(follow_symlinks=False)) and x.hexdigest()==expected
print(json.dumps({'ready':True,'bytes':before.st_size}),flush=True)
if sys.stdin.readline().strip()!='delete':sys.exit(0)
approved();assert stamp(p.stat(follow_symlinks=False))==stamp(before)
os.unlink(p)
print(json.dumps({'removed':True,'bytes':before.st_size}),flush=True)
'''


def qlist(client):
    return {t['hash']: t for t in json.loads(request(client, 'torrents/info'))}


def worker_reply(proc, timeout=1200):
    if not select.select([proc.stdout], [], [], timeout)[0]:
        raise TimeoutError('A operação da VM excedeu o tempo; confira o resultado antes de tentar novamente')
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError('Verificador da VM encerrou sem confirmar o arquivo')
    return json.loads(line)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--limit', type=int, default=0, help='máximo de vídeos removidos; 0 significa sem limite')
    args = parser.parse_args()
    lock = None
    if args.apply:
        lock = (ROOT / 'state/cleanup-published.lock').open('a')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    client = connect()
    torrents = qlist(client)
    published = json.loads((ROOT / 'jellyfin/state/published.json').read_text())
    catalog_paths = catalog()
    file_lists = {}
    for h, t in torrents.items():
        if t.get('save_path', '').startswith('/srv/downloads/recebidos/'):
            file_lists[h] = json.loads(request(client, 'torrents/files?hash=' + h))
    candidates = []
    for h, details in guest_rows():
        t = torrents.get(h)
        if not t or t.get('category') not in ('sonarr', 'radarr') or t.get('progress') != 1 or 'triagem-aprovada' not in t.get('tags', ''):
            continue
        base = '/srv/downloads/recebidos/' + ('series' if t['category'] == 'sonarr' else 'filmes')
        if t['save_path'].rstrip('/') != base:
            continue
        matches = videos(details.get('files', {}))
        if len(matches) != 1:
            continue
        name, digest = matches[0]
        tf = [x for x in file_lists.get(h, []) if Path(x['name']).suffix.lower() in VIDEO]
        if not safe_name(name) or len(tf) != 1 or tf[0]['name'] != name or tf[0]['progress'] != 1:
            continue
        target = str(PurePosixPath(base) / name)
        if any(str(PurePosixPath(torrents[other]['save_path']) / f['name']) == target
               for other, files in file_lists.items() if other != h for f in files):
            continue
        paths = [n for n, r in published.items() if n.startswith(('filmes/', 'series/')) and r.get('sha256') == digest and '/lab-media/' + n in catalog_paths]
        if paths:
            candidates.append((h, name, digest, base, paths[0], published[paths[0]], tf[0]['size']))
    print(json.dumps({'candidatos': len(candidates), 'modo': 'aplicar' if args.apply else 'consulta'}), flush=True)
    if not args.apply:
        return
    if args.limit < 0:
        raise ValueError('Limite inválido')
    count = 0
    for h, name, digest, base, published_name, record, size in candidates:
        if args.limit and count >= args.limit:
            break
        print('Conferindo:', published_name, flush=True)
        p, before = verify_published(published_name, record)
        arg = json.dumps({'hash': h, 'name': name, 'digest': digest, 'base': base}, ensure_ascii=False)
        command = shlex.join(['sudo', '-n', 'ionice', '-c', '3', 'python3', '-c', WORKER, arg])
        proc = subprocess.Popen(SSH + [command], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, bufsize=1)
        try:
            ready = worker_reply(proc)
            if not ready.get('ready') or ready.get('bytes') != size:
                raise RuntimeError('Cópia recebida não foi confirmada')
            latest = json.loads((ROOT / 'jellyfin/state/published.json').read_text())
            if latest.get(published_name) != record or stamp(p.stat()) != before or '/lab-media/' + published_name not in catalog():
                raise RuntimeError('Publicação mudou durante a conferência')
            current = qlist(client)
            if set(current) != set(torrents):
                raise RuntimeError('A fila mudou; reinicie a conferência')
            t = current[h]
            if t['progress'] != 1 or t['save_path'].rstrip('/') != base or 'triagem-aprovada' not in t.get('tags', ''):
                raise RuntimeError('Torrent mudou durante a conferência')
            if json.loads(request(client, 'torrents/files?hash=' + h)) != file_lists[h]:
                raise RuntimeError('Arquivos do torrent mudaram')
            request(client, 'torrents/stop', {'hashes': h})
            request(client, 'torrents/delete', {'hashes': h, 'deleteFiles': 'false'})
            if h in qlist(client):
                raise RuntimeError('Remoção do torrent não confirmada; vídeo preservado')
            del torrents[h]
            proc.stdin.write('delete\n'); proc.stdin.flush()
            result = worker_reply(proc)
            if not result.get('removed') or result.get('bytes') != size:
                raise RuntimeError('Remoção do vídeo não confirmada')
            code = proc.wait(timeout=30)
            if code:
                raise RuntimeError('Verificador da VM falhou após remoção')
            count += 1
            print(json.dumps({'removido': published_name, 'bytes': size}, ensure_ascii=False), flush=True)
        finally:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
            if proc.poll() is None:
                proc.terminate()
    print(json.dumps({'concluido': count}), flush=True)


if __name__ == '__main__':
    main()
