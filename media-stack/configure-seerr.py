#!/usr/bin/env python3
"""Finaliza as integrações após o usuário autenticar o Jellyfin no Seerr."""
import json
from pathlib import Path
import requests

root = Path('/opt/media-stack')
cfg = json.loads((root/'credentials.json').read_text())
session = requests.Session()
session.trust_env = False
session.headers['X-Api-Key'] = cfg['seerr_key']
base = 'http://192.168.250.10:5055/api/v1/'

def api(method, path, payload=None):
    response = session.request(method, base+path, json=payload, timeout=45)
    if response.status_code in (401,403):
        raise SystemExit('Aguardando login inicial do Jellyfin na interface do Seerr.')
    if not response.ok:
        raise RuntimeError(f'Seerr {path}: HTTP {response.status_code}')
    return response.json() if response.content else None

api('GET','auth/me')
for name, port, directory in [('sonarr',8989,'series'),('radarr',7878,'filmes')]:
    existing = api('GET','settings/'+name)
    if any(item['name'] == name.capitalize()+' lab' for item in existing):
        continue
    profiles = requests.get(f'http://192.168.250.10:{port}/api/v3/qualityprofile',
        headers={'X-Api-Key':cfg[name+'_key']},timeout=15).json()
    profile = next(item for item in profiles if item['name'].startswith('Lab -'))
    payload = {'name': name.capitalize()+' lab', 'hostname': name, 'port': port,
               'apiKey': cfg[name+'_key'], 'useSsl': False, 'baseUrl': '',
               'activeProfileId': profile['id'], 'activeProfileName': profile['name'],
               'activeDirectory': '/data/biblioteca/'+directory,
               'is4k': False, 'isDefault': True, 'tags': [], 'syncEnabled': True,
               'preventSearch': False, 'tagRequests': False, 'overrideRule': []}
    if name == 'sonarr':
        payload.update({'seriesType':'standard', 'animeSeriesType':'anime',
                        'activeAnimeProfileId':profile['id'],
                        'activeAnimeProfileName':profile['name'],
                        'activeAnimeDirectory':'/data/biblioteca/series',
                        'animeTags':[], 'enableSeasonFolders':True,
                        'monitorNewItems':'all'})
    else:
        payload['minimumAvailability'] = 'released'
    api('POST','settings/'+name+'/test',payload)
    api('POST','settings/'+name,payload)
    print(name+': teste de conexão do Seerr concluído.',flush=True)
api('POST','settings/main',{'applicationTitle':'Lab - Filmes e Séries',
    'applicationUrl':'http://192.168.250.10:5055', 'locale':'pt-BR',
    'discoverRegion':'BR', 'streamingRegion':'BR', 'partialRequestsEnabled':True,
    'enableSpecialEpisodes':False, 'newPlexLogin':False})
api('POST','settings/initialize')
print('Seerr pronto para procurar e solicitar filmes, temporadas e episódios.')
