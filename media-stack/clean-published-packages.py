#!/usr/bin/env python3
"""Limpa originais de torrents só após conferir aprovação e cópia no Jellyfin.

Sem --apply, mostra somente a quantidade de candidatos. A limpeza pára o
compartilhamento dos torrents afetados e preserva as cópias aprovadas e do
Jellyfin. O registro local permite revisar uma interrupção.
"""
import argparse
import collections
import fcntl
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('clean_published',ROOT/'media-stack/clean-published-copies.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
JOURNAL=ROOT/'state/cleanup-packages-status.json'
LOCK=ROOT/'state/cleanup-published.lock'
RUN_STARTED=False


def save(state):
    state['updated']=time.time();state['pid']=os.getpid()
    fd,name=tempfile.mkstemp(prefix='.cleanup-packages-',dir=JOURNAL.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(state,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        os.replace(name,JOURNAL)
    finally:
        if os.path.exists(name):os.unlink(name)


def safe_base(t):
    category=t.get('category')
    base={'sonarr':'/srv/downloads/recebidos/series','radarr':'/srv/downloads/recebidos/filmes'}.get(category)
    return base if base and t.get('save_path','').rstrip('/')==base else None


def paths_exist(paths):
    code='''import json,os,stat,sys\nfrom pathlib import Path\nitems=json.load(sys.stdin);result=[]\nfor raw in items:\n p=Path(raw);ok=p.is_absolute() and p.is_relative_to(Path('/srv/downloads/recebidos'))\n if ok:\n  try:\n   current=Path('/')\n   for part in p.parts[1:]:\n    current=current/part\n    if current.is_symlink():ok=False;break\n   if ok:ok=stat.S_ISREG(p.stat().st_mode)\n  except OSError:ok=False\n result.append(ok)\nprint(json.dumps(result))\n'''
    command=shlex.join(['sudo','-n','python3','-c',code])
    r=subprocess.run(m.SSH+[command],input=json.dumps(paths),capture_output=True,text=True,timeout=120,check=True)
    result=json.loads(r.stdout)
    if len(result)!=len(paths):raise RuntimeError('Verificação de caminhos incompleta')
    return result


def build_plan(client):
    torrents=m.qlist(client);published=json.loads((ROOT/'jellyfin/state/published.json').read_text());catalog=m.catalog()
    by_digest=collections.defaultdict(list)
    for name,record in published.items():
        if name.startswith(('series/','filmes/')) and '/lab-media/'+name in catalog:
            by_digest[record.get('sha256')].append((name,record))
    candidates=[]
    for h,details in m.guest_rows():
        t=torrents.get(h);base=safe_base(t) if t else None
        if not base or t.get('progress')!=1 or 'triagem-aprovada' not in t.get('tags',''):continue
        if t.get('state') not in ('uploading','stalledUP','queuedUP','stoppedUP','pausedUP'):continue
        files=json.loads(m.request(client,'torrents/files?hash='+h))
        for name,digest in m.videos(details.get('files',{})):
            if not m.safe_name(name):continue
            qfiles=[f for f in files if f.get('name')==name and f.get('progress')==1 and f.get('priority',0)>0]
            matches=by_digest.get(digest,[])
            if len(qfiles)!=1 or len(matches)!=1:continue
            source=PurePosixPath(base)/name
            overlap=False
            for other in torrents.values():
                if other['hash']==h or not other.get('content_path'):continue
                path=PurePosixPath(other['content_path'])
                if source==path or path in source.parents or source in path.parents:overlap=True;break
            if overlap:continue
            published_name,record=matches[0]
            candidates.append({'hash':h,'torrent':t.get('name',''),'content_path':t.get('content_path'),
                               'name':name,'digest':digest,'base':base,'category':t.get('category'),'published':published_name,
                               'record':record,'size':qfiles[0]['size'],'status':'pendente'})
    present=paths_exist([str(PurePosixPath(x['base'])/x['name']) for x in candidates]) if candidates else []
    return sorted([item for item,exists in zip(candidates,present) if exists],key=lambda x:x['size'])


def select_plan(items, category='all', title='', max_torrents=0):
    """Filtra por torrent inteiro, sem abandonar candidatos de um pacote."""
    if max_torrents < 0:
        raise ValueError('O limite de torrents não pode ser negativo')
    selected = [x for x in items if (category == 'all' or x.get('category') == category)
                and title.casefold() in x.get('torrent', '').casefold()]
    if max_torrents:
        chosen = []
        for item in selected:
            if item['hash'] not in chosen and len(chosen) < max_torrents:
                chosen.append(item['hash'])
        selected = [x for x in selected if x['hash'] in chosen]
    return selected


def main(apply, category='all', title='', max_torrents=0, list_items=False):
    global RUN_STARTED
    with LOCK.open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        client=m.connect()
        selection={'category':category,'title':title,'max_torrents':max_torrents}
        previous=json.loads(JOURNAL.read_text()) if apply and JOURNAL.exists() else None
        if previous and previous.get('state') in ('limpando','erro','preparando'):
            # Um plano interrompido pode ter arquivos cujo torrent foi removido.
            # Nunca o descarte ao aplicar filtros diferentes.
            old_selection=previous.get('selection',{'category':'all','title':'','max_torrents':0})
            if selection != {'category':'all','title':'','max_torrents':0} and selection != old_selection:
                raise RuntimeError('Há uma limpeza interrompida com outros filtros; retome-a sem filtros antes de iniciar outra.')
            state=previous
        else:
            state={'state':'preparando','files':select_plan(build_plan(client),category,title,max_torrents),
                   'bytes':0,'removed':0,'selection':selection}
        print(json.dumps({'candidatos':len(state['files']),'bytes':sum(x['size'] for x in state['files']),'modo':'aplicar' if apply else 'consulta'}),flush=True)
        if list_items:
            for item in state['files']:
                print(json.dumps({'torrent':item['torrent'],'arquivo_publicado':item['published'],'bytes':item['size'],'estado':item['status']},ensure_ascii=False),flush=True)
        if not apply:return
        state['state']='limpando';state.pop('reason',None);save(state);RUN_STARTED=True
        for item in state['files']:
            if item.get('status')=='removido':continue
            source=str(PurePosixPath(item['base'])/item['name'])
            if not paths_exist([source])[0]:
                item['status']='ausente';save(state);continue
            state['current']=item['published'];save(state);print('Conferindo:',item['published'],flush=True)
            path,before=m.verify_published(item['published'],item['record'])
            arg=json.dumps({k:item[k] for k in ('hash','name','digest','base')},ensure_ascii=False)
            command=shlex.join(['sudo','-n','ionice','-c','3','python3','-c',m.WORKER,arg])
            proc=subprocess.Popen(m.SSH+[command],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
            try:
                ready=m.worker_reply(proc,timeout=7200)
                if not ready.get('ready') or ready.get('bytes')!=item['size']:raise RuntimeError('Cópia recebida não corresponde')
                latest=json.loads((ROOT/'jellyfin/state/published.json').read_text())
                if latest.get(item['published'])!=item['record'] or m.stamp(path.stat())!=before or '/lab-media/'+item['published'] not in m.catalog():raise RuntimeError('Publicação mudou durante a conferência')
                client=m.connect();current=m.qlist(client)
                source_path=PurePosixPath(source)
                for other in current.values():
                    if other['hash']==item['hash'] or not other.get('content_path'):continue
                    other_path=PurePosixPath(other['content_path'])
                    if source_path==other_path or source_path in other_path.parents or other_path in source_path.parents:raise RuntimeError('Outro torrent usa este caminho')
                torrent=current.get(item['hash'])
                if torrent:
                    if torrent.get('progress')!=1 or safe_base(torrent)!=item['base'] or 'triagem-aprovada' not in torrent.get('tags','') or torrent.get('content_path')!=item['content_path']:raise RuntimeError('Torrent mudou durante a conferência')
                    m.request(client,'torrents/stop',{'hashes':item['hash']})
                    for _ in range(50):
                        torrent=m.qlist(client).get(item['hash'])
                        if torrent and torrent.get('state') in ('stoppedUP','pausedUP'):break
                        time.sleep(.2)
                    else:raise RuntimeError('Parada do torrent não confirmada')
                    # Só remove o registro; nenhum arquivo é apagado por esta chamada.
                    m.request(client,'torrents/delete',{'hashes':item['hash'],'deleteFiles':'false'})
                    if item['hash'] in m.qlist(client):raise RuntimeError('Remoção do torrent não confirmada')
                proc.stdin.write('delete\n');proc.stdin.flush();answer=m.worker_reply(proc,timeout=7200)
                if not answer.get('removed') or answer.get('bytes')!=item['size'] or proc.wait(timeout=30):raise RuntimeError('Remoção não confirmada')
                item['status']='removido';state['removed']+=1;state['bytes']+=item['size'];state['current']=None;save(state)
                print(json.dumps({'removido':item['published'],'bytes':item['size']},ensure_ascii=False),flush=True)
            finally:
                if proc.stdin and not proc.stdin.closed:proc.stdin.close()
                if proc.poll() is None:proc.terminate()
        state['state']='concluido';state['current']=None;save(state)
        print(json.dumps({'concluido':state['removed'],'bytes':state['bytes']}),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',help='executar a limpeza; sem esta opção apenas consulta')
    parser.add_argument('--category',choices=('all','sonarr','radarr'),default='all',help='limitar a séries ou filmes')
    parser.add_argument('--title',default='',help='filtrar pelo nome do torrent, sem diferenciar maiúsculas')
    parser.add_argument('--max-torrents',type=int,default=0,help='limitar a torrents completos; 0 não limita')
    parser.add_argument('--list',action='store_true',help='listar os candidatos sem expor credenciais')
    args=parser.parse_args()
    if args.max_torrents < 0:parser.error('--max-torrents não pode ser negativo')
    try:main(args.apply,args.category,args.title,args.max_torrents,args.list)
    except Exception as e:
        if args.apply and RUN_STARTED:
            try:
                state=json.loads(JOURNAL.read_text()) if JOURNAL.exists() else {'files':[],'removed':0,'bytes':0}
                state.update(state='erro',reason=str(e)[:400]);save(state)
            except Exception:pass
        print('Limpeza interrompida:',type(e).__name__,str(e)[:250],file=sys.stderr,flush=True);sys.exit(1)
