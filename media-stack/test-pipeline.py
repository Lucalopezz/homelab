#!/usr/bin/env python3
"""Teste real com vídeo gerado localmente e EICAR; não procura mídia externa."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

import requests

if os.geteuid() != 0 or os.uname().nodename != 'lab-downloads':
    raise SystemExit('Executar somente dentro da VM com sudo.')
root = Path('/opt/media-stack')
cfg = json.loads((root/'credentials.json').read_text())
session = requests.Session()
session.trust_env = False
base = 'http://192.168.250.10:8080/api/v2/'
session.headers['Referer'] = 'http://192.168.250.10:8080/'
assert session.post(base+'auth/login',data={'username':'admin','password':cfg['qbit_password']},timeout=10).text == 'Ok.'

def bencode(value):
    if isinstance(value,int):
        return b'i'+str(value).encode()+b'e'
    if isinstance(value,str):
        value=value.encode()
    if isinstance(value,bytes):
        return str(len(value)).encode()+b':'+value
    if isinstance(value,dict):
        return b'd'+b''.join(bencode(key)+bencode(value[key]) for key in sorted(value))+b'e'
    raise TypeError(type(value))

folder = Path('/srv/downloads/recebidos/lab-pipeline-test')
if folder.exists():
    raise SystemExit('Já existe diretório de teste; conferir antes de repetir.')
folder.mkdir(mode=0o750)
os.chown(folder,1001,1001)
clean = folder/'Lab.Validacao.1080p.mp4'
subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i',
                'color=c=black:s=1280x720:r=2','-t','12','-c:v','mpeg4','-q:v','5',str(clean)],check=True)
eicar = folder/'Lab.Eicar.mp4'
eicar.write_bytes(base64.b64decode(
    'WDVPIVAlQEFQWzRcUFpYNTQoUF4pN0NDKTd9JEVJQ0FSLVNUQU5EQVJELUFOVElWSVJVUy1URVNULUZJTEUhJEgrSCo='))
disguised = folder/'Lab.Executavel.Disfarcado.mp4'
disguised.write_bytes(b'MZ' + b'not-a-video'*100)
hashes = {}
try:
    for path in (clean,eicar,disguised):
        os.chown(path,1001,1001)
        path.chmod(0o640)
        pieces=[]
        with path.open('rb') as handle:
            for chunk in iter(lambda:handle.read(262144),b''):
                pieces.append(hashlib.sha1(chunk).digest())
        info={'length':path.stat().st_size,'name':path.name,'piece length':262144,'pieces':b''.join(pieces)}
        torrent_hash=hashlib.sha1(bencode(info)).hexdigest()
        hashes[path.name]=torrent_hash
        torrent=bencode({'announce':'http://127.0.0.1:9/announce','info':info})
        response=session.post(base+'torrents/add',files={'torrents':(path.name+'.torrent',torrent)},
            data={'savepath':str(folder),'category':'manual','autoTMM':'false','stopped':'false'},timeout=15)
        assert response.text == 'Ok.'
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        items=session.get(base+'torrents/info',timeout=10).json()
        if all(any(item['hash']==value and item['progress']==1 for item in items) for value in hashes.values()):
            break
        time.sleep(2)
    else:
        raise RuntimeError('qBittorrent não reconheceu os arquivos locais completos.')
    subprocess.run(['systemctl','start','media-triage.service'],check=True,timeout=900)
    db=sqlite3.connect('/var/lib/media-triage/state.sqlite3')
    result={}
    for name,torrent_hash in hashes.items():
        row=db.execute('SELECT status,details FROM items WHERE hash=?',(torrent_hash,)).fetchone()
        assert row is not None
        result[name]={'status':row[0],'details':json.loads(row[1])}
    assert result[clean.name]['status']=='aprovado',result[clean.name]
    assert result[eicar.name]['status']=='reprovado',result[eicar.name]
    assert 'ClamAV' in result[eicar.name]['details']['reason']
    assert result[disguised.name]['status']=='reprovado',result[disguised.name]
    current = {item['hash']: item for item in session.get(base+'torrents/info',timeout=10).json()}
    for path in (eicar,disguised):
        assert current[hashes[path.name]]['state'] in ('stoppedUP','pausedUP')
    destination=Path(result[clean.name]['details']['destination'])
    assert (destination/clean.name).read_bytes()==clean.read_bytes()
    assert (destination/clean.name).stat().st_ino!=clean.stat().st_ino
    assert (destination/clean.name).stat().st_mode&0o222==0
    (root/'pipeline-test-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({name:value['status'] for name,value in result.items()},ensure_ascii=False,indent=2))
finally:
    if hashes:
        response=session.post(base+'torrents/delete',
            data={'hashes':'|'.join(hashes.values()),'deleteFiles':'false'},timeout=15)
        response.raise_for_status()
    # As cópias aprovadas ficam para a verificação SFTP; os originais artificiais são removidos.
    for path in (clean,eicar,disguised):
        path.unlink(missing_ok=True)
    folder.rmdir()
