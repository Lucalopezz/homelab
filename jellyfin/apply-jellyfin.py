#!/usr/bin/env python3
"""Atualiza o Jellyfin existente, preservando estado original e usando override do lab."""
import json,os,subprocess,time
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'jellyfin'
assert ROOT==Path('/mnt/dados/lab')
os.umask(0o077)
secret=json.loads((ROOT/'secrets/jellyfin-host.json').read_text());session=requests.Session();session.trust_env=False
session.headers['Authorization']='MediaBrowser Client="Lab", Device="Fedora", DeviceId="lab-sync", Version="1", Token="'+secret['api_key']+'"'
def api(method,path,**kw):
 r=session.request(method,'http://127.0.0.1:8096/'+path,timeout=30,**kw);r.raise_for_status();return r.json() if r.content else None
def run(*args):subprocess.run(args,check=True)
old=json.loads(subprocess.check_output(['docker','inspect','medias-jellyfin-1']))[0]
assert old['Config']['Labels']['com.docker.compose.project.config_files']=='/mnt/dados/Medias/compose.yml'
assert not (BASE/'runtime/config').exists(),'Configuração local já existe; não repetir migração'
previous_info=api('GET','System/Info')
if any(x.get('NowPlayingItem') for x in api('GET','Sessions')):raise SystemExit('Há uma reprodução ativa/pausada; combinar o reinício antes de aplicar.')
(BASE/'runtime/before-container.json').write_text(json.dumps(old,indent=2)+'\n')
image=json.loads((BASE/'images.lock.json').read_text())['image']
run('docker','pull',image)
command=['docker','compose','-p','medias','--project-directory','/mnt/dados/Medias','--env-file',str(BASE/'.env'),'-f','/mnt/dados/Medias/compose.yml','-f',str(BASE/'compose.override.yaml')]
run('docker','stop','--timeout','60','medias-jellyfin-1')
try:
 (BASE/'runtime/config').mkdir(mode=0o700)
 run('docker','cp','medias-jellyfin-1:/config/.',str(BASE/'runtime/config'))
 if any(p.stat().st_uid!=os.getuid() for p in (BASE/'runtime/config').rglob('*') if not p.is_symlink()):raise RuntimeError('Configuração copiada com proprietário inesperado')
 run(*command,'up','-d','--no-deps','--pull','never','jellyfin')
 for _ in range(120):
  try:
   info=api('GET','System/Info')
   if str(info.get('Version','')).startswith('12.4'):break
  except requests.RequestException:pass
  time.sleep(2)
 else:raise RuntimeError('Jellyfin atualizado não ficou pronto')
except Exception:
 print('Falha na aplicação; restaurando o container com a configuração original, preservada fora de lab.',flush=True)
 run('docker','compose','-p','medias','--project-directory','/mnt/dados/Medias','-f','/mnt/dados/Medias/compose.yml','up','-d','--no-deps','--pull','never','jellyfin')
 raise
assert info['Id']==previous_info['Id'],'Identidade do servidor mudou'
run('/usr/bin/python3',str(BASE/'configure-libraries.py'))
