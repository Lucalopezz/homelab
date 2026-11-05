#!/usr/bin/env python3
"""Desliga apenas a VM após uma limpeza concluída e trabalhos pendentes."""
import argparse
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import requests

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from check_qbittorrent import connect,request
STATUS=ROOT/'state/shutdown-after-cleanup-status.json'
CLEANUP=ROOT/'state/cleanup-packages-status.json'
CLEANUP_PROCESS='clean-published-packages.py'
SSH=['ssh','-F',str(ROOT/'config/ssh_config'),'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=8','lab-downloads-admin']
IMPORTS={'DownloadedEpisodesScan','DownloadedMoviesScan','ManualImport','RenameFiles','RenameSeries','RescanSeries'}
ACTIVE_DOWNLOADS={'downloading','stalledDL','metaDL','queuedDL','forcedDL'}
ACTIVE_PROCESSING={'checkingDL','checkingUP','checkingResumeData','allocating','moving'}


def write(state,reason=None,**extra):
    data={'state':state,'at':dt.datetime.now(dt.timezone.utc).isoformat(),'pid':os.getpid(),**extra}
    if reason:data['reason']=reason
    fd,name=tempfile.mkstemp(prefix='.shutdown-after-cleanup-',dir=STATUS.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        os.replace(name,STATUS)
    finally:
        if os.path.exists(name):os.unlink(name)


def cleanup_decision(state,alive):
    if state=='concluido':return 'ready'
    if state=='erro':return 'error'
    if state in ('preparando','limpando') and alive:return 'wait'
    return 'interrupted'


def process_matches(pid,name):
    if not isinstance(pid,int) or pid<=0:return False
    try:
        proc=Path('/proc')/str(pid)
        if proc.stat().st_uid!=os.getuid():return False
        return any(x.endswith(name.encode()) for x in (proc/'cmdline').read_bytes().split(b'\0'))
    except OSError:return False


def domstate():
    r=subprocess.run(['virsh','--readonly','-c','qemu:///system','domstate','lab-downloads'],capture_output=True,text=True,timeout=10,check=True)
    return r.stdout.strip()


def safe_to_shutdown():
    cleanup=json.loads(CLEANUP.read_text())
    if cleanup_decision(cleanup.get('state'),process_matches(cleanup.get('pid'),CLEANUP_PROCESS))!='ready':
        return False,'A limpeza ainda não foi concluída.'
    torrents=json.loads(request(connect(),'torrents/info'))
    if any(t.get('state') in ACTIVE_PROCESSING or (t.get('progress',0)<1 and t.get('state') in ACTIVE_DOWNLOADS) for t in torrents):
        return False,'Há download ou movimentação do qBittorrent em andamento.'
    cfg=json.loads((ROOT/'secrets/media-stack.json').read_text())
    session=requests.Session();session.trust_env=False
    for app,port,key in [('Sonarr',8989,'sonarr_key'),('Radarr',7878,'radarr_key')]:
        r=session.get(f'http://192.168.250.10:{port}/api/v3/command',headers={'X-Api-Key':cfg[key]},timeout=15);r.raise_for_status()
        if any(x.get('name') in IMPORTS and x.get('status') in ('started','queued') for x in r.json()):
            return False,f'{app} ainda tem importação ou movimentação em andamento.'
    triage=subprocess.run(SSH+['systemctl show media-triage.service -p ActiveState --value'],capture_output=True,text=True,timeout=15,check=True)
    if triage.stdout.strip()!='inactive':
        return False,'A triagem ainda está ativa ou requer revisão.'
    result=subprocess.run(['systemctl','show','lab-jellyfin-sync.service','-p','ActiveState','--value'],capture_output=True,text=True,timeout=10,check=True)
    if result.stdout.strip()!='inactive':
        return False,'A sincronização para o Jellyfin está ativa ou requer revisão.'
    sync=json.loads((ROOT/'jellyfin/state/last-run.json').read_text())
    at=dt.datetime.fromisoformat(sync['at'].replace('Z','+00:00'))
    if (dt.datetime.now(dt.timezone.utc)-at).total_seconds()>600:
        return False,'Aguardando uma sincronização recente para confirmar o estado.'
    if sync.get('pending')!=0 or sync.get('held'):
        return False,'Há arquivos pendentes ou retidos na sincronização.'
    return True,None


def main():
    with (ROOT/'state/shutdown-after-cleanup.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        write('aguardando_limpeza')
        while True:
            try:
                state=domstate()
                if state=='shut off':write('desligada','A VM já está desligada.');return 0
                if state!='running':write('erro','Estado inesperado da VM: '+state);return 1
                cleanup=json.loads(CLEANUP.read_text())
                decision=cleanup_decision(cleanup.get('state'),process_matches(cleanup.get('pid'),CLEANUP_PROCESS))
                if decision in ('error','interrupted'):
                    write('aguardando_revisao','A limpeza falhou ou foi interrompida; a VM permaneceu ligada.');return 1
                if decision=='wait':
                    write('aguardando_limpeza',removed=cleanup.get('removed',0),total=len(cleanup.get('files',[])));time.sleep(90);continue
                ready,reason=safe_to_shutdown()
                if not ready:
                    write('aguardando_trabalhos',reason);time.sleep(90);continue
                # Reconfere antes do pedido para não depender de um único instantâneo.
                time.sleep(5)
                ready,reason=safe_to_shutdown()
                if not ready:
                    write('aguardando_trabalhos',reason);time.sleep(90);continue
                write('desligando','Limpeza concluída; solicitando desligamento gracioso da VM.')
                subprocess.run(SSH+['sudo -n systemctl poweroff'],capture_output=True,text=True,timeout=20,check=False)
                for _ in range(60):
                    time.sleep(2)
                    if domstate()=='shut off':write('desligada','VM desligada após a limpeza.');return 0
                write('erro','O desligamento foi solicitado, mas a VM não confirmou que desligou.');return 1
            except (OSError,ValueError,KeyError,subprocess.SubprocessError,requests.RequestException) as exc:
                write('aguardando_servicos',type(exc).__name__);time.sleep(90)

def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply',action='store_true',help='agendar o desligamento; sem esta opção mostra o estado atual')
    p.add_argument('--cleanup-status',default=str(CLEANUP),help='arquivo de estado da limpeza dentro de state/')
    p.add_argument('--cleanup-process',default=CLEANUP_PROCESS,help='nome do script que produz esse estado')
    return p


def configured_cleanup(path,process):
    target=Path(path).expanduser().resolve()
    state_dir=(ROOT/'state').resolve()
    if not target.is_relative_to(state_dir) or target==state_dir:
        raise ValueError('O arquivo de estado precisa ficar em state/.')
    if Path(process).name!=process or not process.endswith('.py'):
        raise ValueError('Informe apenas o nome do script de limpeza, terminado em .py.')
    return target,process


if __name__=='__main__':
    p=parser();args=p.parse_args()
    try:
        CLEANUP,CLEANUP_PROCESS=configured_cleanup(args.cleanup_status,args.cleanup_process)
        if not args.apply:
            data=json.loads(CLEANUP.read_text()) if CLEANUP.exists() else {}
            current=json.loads(STATUS.read_text()) if STATUS.exists() else {}
            print(json.dumps({'limpeza':data.get('state'),'desligamento':current.get('state'),
                              'motivo':current.get('reason'),'ativo':process_matches(current.get('pid'),'shutdown-after-cleanup.py'),
                              'processo':CLEANUP_PROCESS},ensure_ascii=False,indent=2))
            raise SystemExit(0)
        if not CLEANUP.exists():raise ValueError('Estado da limpeza não encontrado; inicie a limpeza primeiro.')
        raise SystemExit(main())
    except (OSError,ValueError) as exc:
        print('Não foi possível configurar o desligamento:',str(exc),file=sys.stderr);raise SystemExit(1)
