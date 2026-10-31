#!/usr/bin/env python3
"""Fedora: copiar via SFTP, verificar bytes e publicar sem executar mídia."""
import datetime,hashlib,json,os,re,resource,shutil,subprocess,tempfile,time,urllib.request
from pathlib import Path,PurePosixPath
ROOT=Path('/mnt/dados/lab');BASE=Path(os.environ.get('LAB_JELLYFIN_WORKDIR',ROOT/'jellyfin'));LIB=BASE/'biblioteca';STATE=BASE/'state'
VIDEO={'.mkv','.mp4','.m4v','.webm','.avi','.mov','.ts','.m2ts'};SUB={'.srt','.ass','.ssa','.vtt'}
MAX=2047*1024*1024

def safe(name):
 p=PurePosixPath(name)
 if not name or p.is_absolute() or len(p.parts)<2 or p.parts[0] not in ('filmes','series') or len(p.parts)>12 or len(name)>1024:raise ValueError('Caminho inválido')
 if any(x in ('.','..') or x.startswith('.') or len(x)>255 for x in p.parts) or any(ord(x)<32 or x in '\\"\'' for x in name):raise ValueError('Nome de arquivo recusado')
 return p.parts

def credential(name,fallback):
 directory=os.getenv('CREDENTIALS_DIRECTORY')
 return Path(directory)/name if directory else fallback

def get(remote,target,limit):
 def cap():resource.setrlimit(resource.RLIMIT_FSIZE,(limit,limit))
 r=subprocess.run(['/usr/bin/sftp','-F',str(BASE/'ssh_config'),'-i',str(credential('ssh-key',ROOT/'secrets/jellyfin_pull_ed25519')),'-o','UserKnownHostsFile='+str(credential('known-hosts',ROOT/'state/known_hosts')),'-b','-','jellyfin-export'],
  input=f'get "{remote}" "{target}"\n',capture_output=True,text=True,timeout=1800,preexec_fn=cap)
 if r.returncode:raise RuntimeError('Coleta SFTP falhou; arquivo não liberado')
 if not target.is_file() or target.is_symlink() or target.stat().st_size>limit:raise ValueError('Arquivo recebido inválido')

def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()

def folder(parts):
 p=LIB
 for name in parts:
  p=p/name
  if p.is_symlink():raise ValueError('Link no destino recusado')
  if not p.exists():
   p.mkdir(mode=0o770);p.chmod(0o770)
 return p

def refresh():
 c=json.loads(credential('jellyfin-api',ROOT/'secrets/jellyfin-host.json').read_text())
 request=urllib.request.Request('http://127.0.0.1:8096/Library/Refresh',data=b'',method='POST',headers={'Authorization':'MediaBrowser Client="Lab", Device="Fedora", DeviceId="lab-sync", Version="1", Token="'+c['api_key']+'"'})
 with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=15) as r:assert r.status in (200,204)

def atomic_json(path,data):
 fd,name=tempfile.mkstemp(prefix='.sync-',dir=STATE)
 try:
  with os.fdopen(fd,'w') as f:
   json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
  os.chmod(name,0o640);os.replace(name,path)
 finally:
  if os.path.exists(name):os.unlink(name)

def main():
 STATE.mkdir(mode=0o700,exist_ok=True)
 record=STATE/'published.json';previous=json.loads(record.read_text()) if record.exists() else {}
 errors=[];changed=0;current={};pending_files=0;copied_files=0;started=time.monotonic()
 staging=LIB/'.em-recebimento'
 if not staging.exists():
  staging.mkdir(mode=0o770);staging.chmod(0o770)
 with tempfile.TemporaryDirectory(dir=staging) as tmp:
  tmp=Path(tmp);manifest=tmp/'manifest.json';get('/.publicacao/manifest.json',manifest,1024*1024)
  m=json.loads(manifest.read_text());assert m['schema']==1 and isinstance(m['files'],list) and len(m['files'])<=10000
  generated=datetime.datetime.fromisoformat(m['generated_at']);age=datetime.datetime.now(datetime.timezone.utc)-generated
  if not -300<=age.total_seconds()<=7*86400:raise ValueError('Manifesto antigo ou com data inválida')
  expected={}
  for item in m['files']:
   name=item['path'];parts=safe(name);size=item['size'];digest=item['sha256'];ext=Path(name).suffix.lower()
   if name in expected:raise ValueError('Manifesto com caminho duplicado')
   if not isinstance(size,int) or not 0<size<=MAX or not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('Tamanho/hash inválido')
   if not ((item['kind']=='video' and ext in VIDEO) or (item['kind']=='subtitle' and ext in SUB and size<=10*1024*1024)):raise ValueError('Tipo de mídia recusado')
   expected[name]=item
  for index,(name,item) in enumerate(expected.items()):
   try:
    parts=safe(name);destination=folder(parts[:-1])/parts[-1]
    if destination.is_symlink():raise ValueError('Link no destino recusado')
    old=previous.get(name)
    if old and old['sha256']==item['sha256'] and destination.is_file() and old.get('stamp')==[destination.stat().st_ino,destination.stat().st_size,destination.stat().st_mtime_ns,destination.stat().st_ctime_ns]:
     current[name]=old;continue
    if copied_files>=4 or (copied_files and time.monotonic()-started>120):
     if old and destination.is_file() and old.get('stamp')==[destination.stat().st_ino,destination.stat().st_size,destination.stat().st_mtime_ns,destination.stat().st_ctime_ns]:current[name]=old
     pending_files+=1;continue
    incoming=tmp/str(index);get('/'+name,incoming,item['size'])
    if incoming.stat().st_size!=item['size'] or sha(incoming)!=item['sha256']:raise ValueError('Bytes diferentes do manifesto; publicação recusada')
    incoming.chmod(0o440);os.replace(incoming,destination)
    st=destination.stat();current[name]={'sha256':item['sha256'],'stamp':[st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns]};changed+=1;copied_files+=1
    atomic_json(record,{**previous,**current})
    atomic_json(STATE/'refresh-pending.json',{'pending':True})
   except Exception as e:errors.append({'path':name,'reason':str(e)})
  # Só retirar arquivos previamente geridos por este importador; preservar em quarentena privada.
  quarantine=STATE/'quarentena'
  for name,old in previous.items():
   if name in current:continue
   path=LIB.joinpath(*safe(name))
   if path.is_file() and not path.is_symlink():
    if not quarantine.exists():
     quarantine.mkdir(mode=0o770);quarantine.chmod(0o770)
    held=quarantine/(hashlib.sha256(name.encode()).hexdigest()+'-'+str(os.stat(path).st_mtime_ns))
    os.replace(path,held);changed+=1
  atomic_json(record,current)
  atomic_json(STATE/'last-run.json',{'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'published':len(current),'changed':changed,'pending':pending_files,'held':errors})
 pending=STATE/'refresh-pending.json'
 if changed:atomic_json(pending,{'pending':True})
 if pending.exists():
  refresh();pending.unlink()
 print(json.dumps({'published':len(current),'changed':changed,'pending':pending_files,'held':len(errors)}))
if __name__=='__main__':main()
