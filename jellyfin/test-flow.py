#!/usr/bin/env python3
"""Fedora: teste de bytes e catálogo com vídeo próprio e legenda EICAR recusada."""
import hashlib,json,os,subprocess,time
from pathlib import Path
import requests
ROOT=Path('/mnt/dados/lab');assert os.geteuid()==0
secret=json.loads((ROOT/'secrets/jellyfin-host.json').read_text());s=requests.Session();s.trust_env=False;s.headers['Authorization']='MediaBrowser Client="Lab", Device="Fedora", DeviceId="lab-test", Version="1", Token="'+secret['api_key']+'"'
def api(method,path,**kw):
 r=s.request(method,'http://127.0.0.1:8096/'+path,timeout=30,**kw);r.raise_for_status();return r.json() if r.content else None
def vm(action):
 r=subprocess.run(['ssh','-F',str(ROOT/'config/ssh_config'),'lab-downloads-admin','sudo python3 /opt/jellyfin-export/fixture-vm.py '+action],capture_output=True,text=True,check=True,timeout=1000)
 if action=='prepare':return json.loads(r.stdout.strip().splitlines()[-1])
def sync():subprocess.run(['systemctl','start','--no-block','lab-jellyfin-sync.service'],check=True)
fixture=None
item=None
try:
 fixture=vm('prepare');sync()
 folder=ROOT/'jellyfin/biblioteca'/fixture['relative'];video=folder/fixture['filename'];sub=video.with_suffix('.pt-BR.srt');bad=video.with_suffix('.en.srt')
 for attempt in range(1800):
  if video.is_file() and sub.is_file():break
  if attempt and attempt%30==0:print('Aguardando lote com a amostra sintética...',flush=True)
  time.sleep(2)
 assert video.is_file() and sub.is_file() and not bad.exists()
 assert hashlib.sha256(video.read_bytes()).hexdigest()==fixture['sha256']
 api('POST','Library/Refresh')
 library=next(v for v in api('GET','Library/VirtualFolders') if '/lab-media/filmes' in v.get('Locations',[]))
 item=None
 for _ in range(60):
  result=api('GET','Items',params={'ParentId':library['ItemId'],'Recursive':'true','IncludeItemTypes':'Movie','Fields':'Path,MediaSources,MediaStreams'})
  item=next((i for i in result.get('Items',[]) if i.get('Path')=='/lab-media/'+fixture['relative']+'/'+fixture['filename']),None)
  if item:break
  time.sleep(2)
 assert item,'Vídeo não apareceu na biblioteca'
 r=s.get('http://127.0.0.1:8096/Videos/'+item['Id']+'/stream',params={'static':'true'},headers={'Range':'bytes=0-1023'},timeout=30);r.raise_for_status();assert r.status_code==206 and r.content==video.read_bytes()[:1024]
 inspect=json.loads(subprocess.check_output(['docker','inspect','medias-jellyfin-1']))[0]
 assert inspect['Config']['User']=='1000:1000' and inspect['HostConfig']['ReadonlyRootfs']
 assert 'ALL' in inspect['HostConfig']['CapDrop']
 assert all(not m['RW'] for m in inspect['Mounts'] if m['Destination'] in ('/media','/lab-media'))
 p=subprocess.run(['docker','exec','medias-jellyfin-1','touch','/lab-media/.lab-write-test'],capture_output=True);assert p.returncode!=0 and b'Read-only file system' in p.stderr
 result={'synthetic_video':True,'sha256_matches':True,'subtitle_transferred':True,'eicar_subtitle_blocked':True,'jellyfin_catalog':True,'http_range_206':True,'read_only_enforced':True,'non_root':True,'rootfs_read_only':True,'capabilities_dropped':True}
 (ROOT/'state/jellyfin-flow-test.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
finally:
 vm('cleanup')
 if fixture:
  # O teste remove apenas a pasta com nome único que ele próprio criou.
  folder=ROOT/'jellyfin/biblioteca'/fixture['relative']
  if folder.exists():
   import shutil
   shutil.rmtree(folder)
  if item:api('DELETE','Items/'+item['Id'])
  sync();api('POST','Library/Refresh')
