#!/usr/bin/env python3
"""Configura integrações e qualidade usando APIs dos serviços em execução."""
import copy
import json
import os
from pathlib import Path
import time

import requests

ROOT = Path('/opt/media-stack')
CFG = json.loads((ROOT / 'credentials.json').read_text())
PORTS = {'sonarr': 8989, 'radarr': 7878, 'prowlarr': 9696}
VERSIONS = {'sonarr': 'v3', 'radarr': 'v3', 'prowlarr': 'v1'}
SESSION = requests.Session()
SESSION.trust_env = False

def api(app, method, route, payload=None, timeout=30):
    response = SESSION.request(method,
        f'http://192.168.250.10:{PORTS[app]}/api/{VERSIONS[app]}/{route}',
        headers={'X-Api-Key': CFG[app + '_key']}, json=payload, timeout=timeout)
    if not response.ok:
        messages = []
        try:
            data = response.json()
            if isinstance(data, list):
                messages = [item.get('errorMessage', '') for item in data]
            else:
                messages = [data.get('message', '')]
        except ValueError:
            pass
        raise RuntimeError(f'{app} {method} {route}: HTTP {response.status_code}; ' + '; '.join(messages)[:600])
    return response.json() if response.content else None

def fields(model, values):
    for field in model['fields']:
        if field['name'] in values:
            field['value'] = values[field['name']]
    return model

def ensure_model(app, route, model):
    existing = next((item for item in api(app, 'GET', route) if item['name'] == model['name']), None)
    if existing:
        return existing
    model.pop('id', None)
    return api(app, 'POST', route, model)

def set_item(item):
    name = item.get('quality', {}).get('name', '') if item.get('quality') else ''
    if item.get('items'):
        item['items'] = [set_item(child) for child in item['items']]
        item['allowed'] = any(child['allowed'] for child in item['items'])
    else:
        item['allowed'] = ('1080p' in name or '720p' in name) and any(
            value in name.lower() for value in ('webdl', 'webrip', 'bluray')) and 'remux' not in name.lower()
    return item

def configure_arr(app):
    for _ in range(120):
        try:
            api(app, 'GET', 'system/status', timeout=3)
            break
        except Exception:
            time.sleep(2)
    else:
        raise RuntimeError(app + ' não iniciou')
    host = api(app, 'GET', 'config/host')
    host.update({'username': CFG['username'], 'password': CFG['password'],
                 'passwordConfirmation': CFG['password'], 'analyticsEnabled': False,
                 'authenticationMethod': 'forms', 'authenticationRequired': 'enabled'})
    api(app, 'PUT', 'config/host', host)
    if app == 'prowlarr':
        return
    if app == 'sonarr':
        naming = api(app, 'GET', 'config/naming')
        naming['renameEpisodes'] = True
        naming['animeEpisodeFormat'] = '{Series Title} - S{season:00}E{episode:00} - {Episode Title} {Quality Full}'
        api(app, 'PUT', 'config/naming', naming)
    management = api(app, 'GET', 'config/mediamanagement')
    management['copyUsingHardlinks'] = False
    # Importar também as legendas que já passaram pela triagem com o vídeo.
    management['importExtraFiles'] = True
    management['extraFileExtensions'] = 'srt,ass,vtt'
    api(app, 'PUT', 'config/mediamanagement', management)
    download_config = api(app, 'GET', 'config/downloadclient')
    download_config.update({'enableCompletedDownloadHandling': False})
    api(app, 'PUT', 'config/downloadclient', download_config)
    folder = '/data/biblioteca/' + ('series' if app == 'sonarr' else 'filmes')
    roots = api(app, 'GET', 'rootfolder')
    if not any(item['path'] == folder for item in roots):
        api(app, 'POST', 'rootfolder', {'path': folder})
    schema = api(app, 'GET', 'qualityprofile/schema')
    if isinstance(schema, list):
        schema = schema[0]
    profile = copy.deepcopy(schema)
    profile.update({'name': 'Lab - 1080p preferido, 720p alternativa', 'upgradeAllowed': True,
                    'minFormatScore': 0, 'cutoffFormatScore': 0})
    if app == 'radarr':
        languages = api(app, 'GET', 'language')
        original = next((item for item in languages if item['name'].lower() == 'original'), None)
        if original:
            profile['language'] = original
    profile['items'] = [set_item(item) for item in profile['items']]
    definitions = api(app, 'GET', 'qualitydefinition')
    cutoff = next(item['quality']['id'] for item in definitions
                  if item['quality']['name'].lower() == 'webdl-1080p')
    # Usar o grupo existente quando WEB-DL e WEBRip estão agrupados no schema.
    profile['cutoff'] = cutoff
    for item in profile['items']:
        if item.get('items') and any(child.get('quality', {}).get('id') == cutoff for child in item['items']):
            profile['cutoff'] = item['id']
    profile = ensure_model(app, 'qualityprofile', profile)
    for definition in definitions:
        name = definition['quality']['name'].lower()
        if '1080p' in name and any(value in name for value in ('webdl', 'webrip', 'bluray')) and 'remux' not in name:
            definition.update({'minSize': 4, 'preferredSize': 20, 'maxSize': 40})
        elif '720p' in name and any(value in name for value in ('webdl', 'webrip', 'bluray')):
            definition.update({'minSize': 2, 'preferredSize': 10, 'maxSize': 25})
        else:
            continue
        api(app, 'PUT', f"qualitydefinition/{definition['id']}", definition)
    spec = {'name': 'Executável ou pacote suspeito', 'implementation': 'ReleaseTitleSpecification',
            'negate': False, 'required': False,
            'fields': [{'name': 'value', 'value': r'(?i)(\.(exe|scr|msi|lnk|bat|cmd|iso|rar|zip|7z)\b|password[ ._-]*protected)'}]}
    custom = ensure_model(app, 'customformat', {'name': 'Lab - rejeitar pacotes suspeitos',
                                               'includeCustomFormatWhenRenaming': False,
                                               'specifications': [spec]})
    profile = api(app, 'GET', f"qualityprofile/{profile['id']}")
    found = False
    for item in profile.get('formatItems', []):
        if item['format'] == custom['id']:
            item['score'] = -10000
            found = True
    if not found:
        profile.setdefault('formatItems', []).append({'format': custom['id'], 'name': custom['name'], 'score': -10000})
    api(app, 'PUT', f"qualityprofile/{profile['id']}", profile)
    models = api(app, 'GET', 'downloadclient/schema')
    client = copy.deepcopy(next(item for item in models if item['implementation'] == 'QBittorrent'))
    client.update({'name': 'qBittorrent com triagem', 'enable': True,
                   'removeCompletedDownloads': False, 'removeFailedDownloads': False,
                   'priority': 1})
    fields(client, {'host': '192.168.250.10', 'port': 8080, 'useSsl': False,
                    'username': 'admin', 'password': CFG['qbit_password'],
                    'tvCategory': 'sonarr', 'movieCategory': 'radarr',
                    'recentTvPriority': 0, 'olderTvPriority': 0,
                    'initialState': 0, 'firstAndLast': False})
    ensure_model(app, 'downloadclient', client)
    print(app + ': acesso, perfil de qualidade, diretório e cliente integrados.', flush=True)

def configure_qbit():
    session = requests.Session()
    session.trust_env = False
    base = 'http://192.168.250.10:8080/api/v2/'
    session.headers['Referer'] = 'http://192.168.250.10:8080/'
    assert session.post(base+'auth/login', data={'username': 'admin', 'password': CFG['qbit_password']}, timeout=10).text == 'Ok.'
    preferences = {'save_path': '/srv/downloads/recebidos', 'auto_tmm_enabled': True,
                   'excluded_file_names_enabled': True,
                   'excluded_file_names': '\n'.join('*.'+ext for ext in ['exe','scr','bat','cmd','msi','lnk','com','vbs','pif','ps1','js','jse','wsf','hta']),
                   'autorun_enabled': False, 'autorun_on_torrent_added_enabled': False}
    session.post(base+'app/setPreferences', data={'json': json.dumps(preferences)}, timeout=10).raise_for_status()
    categories = session.get(base+'torrents/categories', timeout=10).json()
    for category, directory in [('sonarr','series'), ('radarr','filmes'), ('manual','manuais')]:
        target = '/srv/downloads/recebidos/'+directory
        if category in categories and categories[category]['savePath'].rstrip('/') == target:
            continue
        route = 'editCategory' if category in categories else 'createCategory'
        session.post(base+'torrents/'+route, data={'category': category,
            'savePath': target}, timeout=10).raise_for_status()
    print('qBittorrent: categorias, filtros e destino de recebidos configurados.', flush=True)

def configure_prowlarr():
    for name, implementation, port in [('Sonarr', 'Sonarr', 8989), ('Radarr', 'Radarr', 7878)]:
        app = name.lower()
        model = copy.deepcopy(next(item for item in api('prowlarr','GET','applications/schema')
                                   if item['implementation'] == implementation))
        model.update({'name': name+' lab', 'syncLevel': 'fullSync'})
        fields(model, {'prowlarrUrl': 'http://prowlarr:9696', 'baseUrl': f'http://{app}:{port}',
                       'apiKey': CFG[app+'_key']})
        ensure_model('prowlarr','applications',model)
    models = api('prowlarr','GET','indexer/schema')
    # Só cadastrar os indexadores que passam pelo teste de conectividade real.
    successes, failures = [], []
    for wanted in ['Nyaa.si', 'AnimeTosho', 'Knaben']:
        model = next((item for item in models if item['name'].casefold() == wanted.casefold()), None)
        if not model:
            failures.append({'name': wanted, 'reason': 'não consta do schema instalado'})
            continue
        model = copy.deepcopy(model)
        model.update({'enable': True, 'appProfileId': 1, 'priority': 25})
        fields(model, {'minimumSeeders': 5})
        if wanted == 'Knaben':
            fields(model, {'torrentBaseSettings.preferMagnetUrl': True})
        try:
            created = ensure_model('prowlarr','indexer',model)
            successes.append({'name': wanted, 'id': created['id']})
            print('Indexador validado: '+wanted, flush=True)
        except Exception as error:
            failures.append({'name': wanted, 'reason': str(error)})
            print('Indexador pendente: '+wanted, flush=True)
    api('prowlarr','POST','command',{'name': 'ApplicationIndexerSync'})
    report = {'working': successes, 'pending': failures}
    (ROOT/'indexers-result.json').write_text(json.dumps(report, indent=2)+'\n')
    if not successes:
        raise RuntimeError('Nenhum indexador passou no teste; verificar conectividade.')

def configure_bazarr():
    url = 'http://192.168.250.10:6767/api/system/settings'
    headers = {'X-API-KEY': CFG['bazarr_key']}
    # Partida fria no HD pode levar vários minutos.
    for _ in range(300):
        try:
            response = SESSION.get(url, headers=headers, timeout=3)
            if response.ok:
                break
        except requests.RequestException:
            pass
        time.sleep(2)
    else:
        raise RuntimeError('Bazarr não iniciou')
    profile = {'profileId': 1, 'name': 'Português BR + inglês para áudio em inglês',
               # Não encerrar a busca de inglês só porque já existe pt-BR.
               'cutoff': 2, 'items': [
                   {'id':1, 'language':'pb', 'hi':'False', 'forced':'False',
                    'audio_exclude':'False', 'audio_only_include':'False'},
                   {'id':2, 'language':'en', 'hi':'False', 'forced':'False',
                    'audio_exclude':'False', 'audio_only_include':'True'}],
               'mustContain': [], 'mustNotContain': [], 'originalFormat': None}
    profiles_response = SESSION.get(url.replace('system/settings', 'system/languages/profiles'),
                                    headers=headers, timeout=30)
    profiles_response.raise_for_status()
    profiles = [item for item in profiles_response.json() if item['profileId'] != 1] + [profile]
    languages_response = SESSION.get(url.replace('system/settings', 'system/languages'),
                                     headers=headers, timeout=30)
    languages_response.raise_for_status()
    enabled = {item['code2'] for item in languages_response.json() if item['enabled']} | {'pb', 'en'}
    result = SESSION.post(url, headers=headers, timeout=120, data=[
        *[('languages-enabled', language) for language in sorted(enabled)],
        ('languages-profiles',json.dumps(profiles))])
    result.raise_for_status()
    print('Bazarr: pt-BR e inglês obrigatório quando o áudio é inglês.',flush=True)

if __name__ == '__main__':
    configure_qbit()
    for application in PORTS:
        configure_arr(application)
    configure_bazarr()
    configure_prowlarr()
