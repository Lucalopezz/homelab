#!/usr/bin/env python3
"""Configuração idempotente das bibliotecas após a atualização do servidor."""
import json,time
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'jellyfin'
c=json.loads((ROOT/'secrets/jellyfin-host.json').read_text());s=requests.Session();s.trust_env=False
s.headers['Authorization']='MediaBrowser Client="Lab", Device="Fedora", DeviceId="lab-sync", Version="1", Token="'+c['api_key']+'"'
def api(method,path,**kw):
 r=s.request(method,'http://127.0.0.1:8096/'+path,timeout=30,**kw);r.raise_for_status();return r.json() if r.content else None
info=api('GET','System/Info');assert info['Version'].startswith('12.4')
options={'EnableRealtimeMonitor':True,'SaveLocalMetadata':False,'MetadataSavers':[],
 'EnableChapterImageExtraction':False,'ExtractChapterImagesDuringLibraryScan':False,
 'EnableTrickplayImageExtraction':False,'ExtractTrickplayImagesDuringLibraryScan':False,
 'EnableLUFSScan':False,'PreferredMetadataLanguage':'pt','MetadataCountryCode':'BR'}
existing=api('GET','Library/VirtualFolders')
for name,kind,path in [('Lab - Filmes','movies','/lab-media/filmes'),('Lab - Séries','tvshows','/lab-media/series')]:
 if not any(path in v.get('Locations',[]) for v in existing):
  api('POST','Library/VirtualFolders',params={'name':name,'collectionType':kind,'paths':path,'refreshLibrary':'false'},json={'LibraryOptions':options})
api('POST','Library/Refresh')
media=json.loads((ROOT/'secrets/media-stack.json').read_text());seerr=requests.Session();seerr.trust_env=False;seerr.headers['X-Api-Key']=media['seerr_key'];url='http://192.168.250.10:5055/api/v1/'
for _ in range(120):
 try:
  r=seerr.get(url+'auth/me',timeout=3)
  if r.ok:break
 except requests.RequestException:pass
 time.sleep(2)
else:raise RuntimeError('Seerr ainda não disponível; executar este configurador novamente após o boot da VM')
user=r.json();users=api('GET','Users');assert user['jellyfinUserId'] in {u['Id'] for u in users},'Identidade do usuário mudou'
r=seerr.get(url+'settings/jellyfin',timeout=15);r.raise_for_status();assert r.json()['serverId']==info['Id'],'Identidade do servidor mudou'
r=seerr.post(url+'settings/jellyfin/library/sync',timeout=45);r.raise_for_status();libraries=r.json()
for library in libraries:
 if library.get('name') in ('Lab - Filmes','Lab - Séries'):
  response=seerr.put(url+'settings/jellyfin/library/'+str(library['id']),json={'enabled':True},timeout=20);response.raise_for_status()
result={'version':info['Version'],'server_id_preserved':True,'user_mapping_preserved':True,'users':len(users),'library_names':['Lab - Filmes','Lab - Séries'],'config_in_lab':True,'media_read_only':True}
(BASE/'runtime/applied.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print('Jellyfin '+info['Version']+': identidade e usuários preservados; bibliotecas do lab conectadas ao Seerr.')
