#!/usr/bin/env python3
"""Painel local de consulta ao laboratório. Não altera downloads."""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from check_qbittorrent import connect, request

HTML = '''<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Laboratório de mídia</title><style>
body{font:16px system-ui;background:#101820;color:#edf3f6;max-width:1100px;margin:auto;padding:20px}
section{background:#1c2933;border-radius:12px;padding:18px;margin:16px 0}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:8px;border-bottom:1px solid #3c4c58}
button{padding:9px 15px;border:0;border-radius:7px;cursor:pointer} .error{color:#ffadad}
.overview{border-left:5px solid #eebc63;background:#263540}.overview h2{margin-top:0}.overview p{line-height:1.5}
</style><h1>Laboratório de mídia</h1><p>Consulta local. Atualização automática a cada minuto ou pelo botão.</p>
<button onclick="refresh()">Atualizar</button> <input id="filter" placeholder="Filtrar por nome ou estado" oninput="render()"><p id="updated"></p><div id="content"></div>
<script>
function section(title, rows, columns){let s=document.createElement('section'),h=document.createElement('h2');h.textContent=title;s.append(h);let t=document.createElement('table'),head=document.createElement('tr');columns.forEach(c=>{let x=document.createElement('th');x.textContent=c[0];head.append(x)});t.append(head);rows.forEach(r=>{let tr=document.createElement('tr');columns.forEach(c=>{let td=document.createElement('td');td.textContent=String(c[1](r)??'—');tr.append(td)});t.append(tr)});s.append(t);return s}
function overview(data){let s=document.createElement('section');s.className='overview';let h=document.createElement('h2');h.textContent=data.title;s.append(h);for(let line of data.lines){let p=document.createElement('p');p.textContent=line;s.append(p)}if(data.at){let p=document.createElement('p');p.textContent='Última conferência dos pedidos: '+new Date(data.at).toLocaleString();s.append(p)}return s}
let current=null;
function render(){if(!current)return;let data=current,target=document.getElementById('content');target.textContent='';let filter=document.getElementById('filter').value.toLocaleLowerCase();for(let [key,title,cols] of [['series','Séries no Sonarr',[['Título',x=>x.title],['Episódios com arquivo no Sonarr',x=>x.files],['Episódios monitorados no Sonarr',x=>x.total],['No Jellyfin (lançados)',x=>{let a=data.jellyfin&&data.jellyfin.targets&&data.jellyfin.targets[x.title];return !a||a.error?'Indisponível':(a.expected-a.jellyfin_missing)+' / '+a.expected}]]],['movies','Filmes no Radarr',[['Título',x=>x.title],['Arquivo no Radarr',x=>x.hasFile?'Sim':'Não'],['No Jellyfin',x=>{let a=data.jellyfin&&data.jellyfin.movies&&data.jellyfin.movies[x.title];return !a||a.error?'Indisponível':(a.jellyfin?'Sim':'Não')}]]],['torrents','Downloads no qBittorrent',[['Nome',x=>x.name],['Estado',x=>x.state],['Progresso',x=>Math.round(x.progress*100)+'%'],['Velocidade',x=>Math.round(x.dlspeed/1024)+' KiB/s'],['Etiquetas',x=>x.tags],['Caminho informado na VM',x=>x.content_path]]],['triage','Triagem: último registro por download',[['Nome',x=>x.name],['Estado registrado',x=>x.status],['Fase informada',x=>x.phase||'Não registrada'],['Arquivo informado',x=>x.file||'Não identificado'],['Destino registrado na VM',x=>x.destination||'Não registrado'],['Motivo',x=>x.reason||'—'],['Atualizado em',x=>x.updated]]]]){let source=data[key];if(source.error){let s=document.createElement('section');s.className='error';s.textContent=title+': indisponível — '+source.error;target.append(s)}else{let rows=source.items.filter(x=>!filter||JSON.stringify(x).toLocaleLowerCase().includes(filter));target.append(section(title,rows,cols))}}if(data.triage&&!data.triage.error&&data.triage.large_files&&data.triage.large_files.length){let rows=data.triage.large_files.filter(x=>!filter||JSON.stringify(x).toLocaleLowerCase().includes(filter));document.getElementById('content').append(section('Arquivos grandes detectados',[...rows],[['Arquivo',x=>x.file],['Estado',x=>x.status],['Motivo',x=>x.reason],['Alternativa solicitada',x=>x.alternative||'—'],['Atualizado em',x=>x.updated]]))}let info=document.createElement('section');let h=document.createElement('h2');h.textContent='Atividade atual e sincronização';let p=document.createElement('p');p.textContent=data.triage.error?'Atividade da triagem desconhecida':('Serviço de triagem: '+data.triage.service.ActiveState+' / '+data.triage.service.SubState+'. Arquivos identificados em uso: '+(data.triage.active.length?data.triage.active.map(x=>x.phase+': '+x.file).join('; '):'nenhum identificado; isso não prova que a triagem está parada.'));let q=document.createElement('p');q.textContent=data.sync.error?'Sincronização indisponível: '+data.sync.error:'Última sincronização concluída: '+JSON.stringify(data.sync.data)+'; serviço atual: '+data.sync.service+'. O arquivo atualmente copiado não é identificado pelo sincronizador.';let a=document.createElement('p');if(data.commands.error){a.textContent='Comandos do Sonarr: indisponíveis'}else{let cmds=data.commands.items;a.textContent=cmds.length?'Sonarr: '+cmds.map(x=>{let msg=x.message||x.status;let match=msg.match(/Processing file (\\d+) of (\\d+)/i);return x.name+': '+(match?'processando arquivo '+match[1]+' de '+match[2]:msg)}).join('; '):'Sonarr: nenhuma busca ou importação em execução'}let b=document.createElement('p');let rec=data.triage.error?null:data.triage.recovery;if(!rec){b.textContent='Recuperação automática: estado indisponível'}else{let labels={none:'sem ação',import:'importação solicitada',search:'busca solicitada',error:'erro'};b.textContent='Recuperação automática: '+(labels[rec.action]||rec.action)+'; última consulta '+new Date(rec.at).toLocaleString()+(rec.notes&&rec.notes.length?' — '+rec.notes.join(' '):'')+(rec.reason?' — '+rec.reason:'')}let z=document.createElement('p');let clean=data.cleanup&&data.cleanup.data;if(!clean){z.textContent='Limpeza anterior: sem agendamento registrado'}else{let names={aguardando_importacao:'aguardando importação',aguardando_publicacao:'aguardando publicação no Jellyfin',aguardando_consulta:'aguardando serviços',limpando:'conferindo e limpando',concluido:'concluída',erro:'interrompida com erro'};if(['aguardando_importacao','aguardando_publicacao','aguardando_consulta','limpando'].includes(clean.state)&&!data.cleanup.active)names[clean.state]='processo interrompido; conferir registro';else if(clean.state==='limpando'&&!data.cleanup.worker_active)names[clean.state]='verificador de cópias não identificado';let extra='';if(clean.targets){let n=Object.values(clean.targets).reduce((sum,x)=>sum+x.jellyfin_missing,0);extra='; episódios ainda não catalogados: '+n}z.textContent='Limpeza anterior (pedidos de 03/11): '+(names[clean.state]||clean.state)+extra+(clean.reason?' — '+clean.reason:'')+(clean.state==='limpando'?'; iniciada em ':'; atualizado em ')+new Date(clean.at).toLocaleString()}info.append(h,p,a,b,q,z);target.prepend(info);target.prepend(overview(data.overview))}
let loading=false;async function refresh(){if(loading)return;loading=true;let target=document.getElementById('content');target.textContent='Consultando…';try{let r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error('Falha na consulta');current=await r.json();document.getElementById('updated').textContent='Consulta: '+new Date(current.at).toLocaleString();render()}catch(e){target.textContent='Não foi possível consultar o painel: '+e.message}finally{loading=false}}
refresh();setInterval(refresh,60000);</script></html>'''


def catalog_status(series, episodes_by_id, jelly_series, jelly_episodes, now):
    """Compara somente episódios monitorados e lançados da biblioteca do lab."""
    lab_series = [x for x in jelly_series if (x.get('Path') or '').startswith('/lab-media/series/')]
    targets = {}
    for item in series:
        if not item.get('monitored'):
            continue
        title = item.get('title', 'Série sem título')
        episodes = episodes_by_id.get(item.get('id'))
        if not isinstance(episodes, list):
            targets[title] = {'error': 'Episódios do Sonarr indisponíveis'}
            continue
        expected = []
        try:
            for ep in episodes:
                if not ep.get('monitored') or ep.get('seasonNumber', 0) <= 0 or not ep.get('airDateUtc'):
                    continue
                air = datetime.fromisoformat(ep['airDateUtc'].replace('Z', '+00:00'))
                if air <= now:
                    expected.append(ep)
        except (TypeError, ValueError):
            targets[title] = {'error': 'Data de episódio inválida no Sonarr'}
            continue
        tvdb = str(item.get('tvdbId') or '')
        folder = (item.get('path') or '').removeprefix('/data/biblioteca/series/')
        expected_path = '/lab-media/series/' + folder if folder and '/' not in folder else None
        matches = [x for x in lab_series if
                   (tvdb and str((x.get('ProviderIds') or {}).get('Tvdb') or '') == tvdb)
                   or (expected_path and x.get('Path') == expected_path)]
        if len(matches) > 1 or not tvdb:
            targets[title] = {'error': 'Identificação da série no Jellyfin ambígua ou ausente'}
            continue
        if not matches and any(not (x.get('ProviderIds') or {}).get('Tvdb') for x in lab_series):
            targets[title] = {'error': 'Identificação incompleta no catálogo do Jellyfin'}
            continue
        jelly_id = matches[0].get('Id') if matches else None
        if matches and not jelly_id:
            targets[title] = {'error': 'Série do Jellyfin sem identificador'}
            continue
        present = {(x.get('ParentIndexNumber'), x.get('IndexNumber')) for x in jelly_episodes
                   if jelly_id and x.get('SeriesId') == jelly_id
                   and (x.get('Path') or '').startswith('/lab-media/series/')}
        targets[title] = {
            'expected': len(expected),
            'sonarr_missing': sum(not ep.get('hasFile') for ep in expected),
            'jellyfin_missing': sum((ep.get('seasonNumber'), ep.get('episodeNumber')) not in present for ep in expected),
        }
    return targets


def movie_catalog_status(movies, jelly_movies):
    """Relaciona filmes monitorados à biblioteca do lab pelo ID do TMDB."""
    lab = [x for x in jelly_movies if (x.get('Path') or '').startswith('/lab-media/filmes/')]
    result = {}
    for movie in movies:
        if not movie.get('monitored'):
            continue
        title = movie.get('title', 'Filme sem título')
        tmdb = str(movie.get('tmdbId') or '')
        if not tmdb:
            result[title] = {'error': 'Filme sem identificador TMDB no Radarr'}
            continue
        matches = [x for x in lab if str((x.get('ProviderIds') or {}).get('Tmdb') or '') == tmdb]
        if len(matches) > 1:
            result[title] = {'error': 'Filme com correspondência ambígua no Jellyfin'}
        elif not matches and any(not (x.get('ProviderIds') or {}).get('Tmdb') for x in lab):
            result[title] = {'error': 'Identificação incompleta no catálogo do Jellyfin'}
        else:
            result[title] = {'radarr': bool(movie.get('hasFile')), 'jellyfin': bool(matches)}
    return result


def progress_overview(cleanup, sync, now=None, jellyfin=None):
    """Resumo atual; o resultado de uma limpeza antiga não define novos pedidos."""
    result = {'title': 'Acompanhamento dos pedidos', 'at': None, 'lines': []}
    targets = jellyfin.get('targets') if isinstance(jellyfin, dict) else None
    if not isinstance(targets, dict):
        result['lines'].append('Não foi possível consultar o catálogo atual; o estado dos pedidos não está confirmado.')
    else:
        result['at'] = jellyfin.get('at')
        if not targets:
            result['lines'].append('Nenhuma série monitorada encontrada no Sonarr.')
        for title, item in targets.items():
            if item.get('error'):
                result['lines'].append(f"{title}: consulta incompleta — {item['error']}.")
            elif all(isinstance(item.get(k), int) for k in ('expected', 'jellyfin_missing', 'sonarr_missing')):
                result['lines'].append(f"{title}: {item['expected'] - item['jellyfin_missing']}/{item['expected']} no Jellyfin; {item['sonarr_missing']} sem arquivo no Sonarr.")
            else:
                result['lines'].append(f'{title}: estado não confirmado.')
    movies = jellyfin.get('movies') if isinstance(jellyfin, dict) else None
    if isinstance(movies, dict):
        for title, item in movies.items():
            if item.get('error'):
                result['lines'].append(f"Filme {title}: consulta incompleta — {item['error']}.")
            else:
                result['lines'].append(f"Filme {title}: {'no Jellyfin' if item.get('jellyfin') else 'ainda não está no Jellyfin'}; {'arquivo no Radarr' if item.get('radarr') else 'sem arquivo no Radarr'}.")
    elif isinstance(jellyfin, dict) and jellyfin.get('movies_error'):
        result['lines'].append('Filmes: consulta ao Radarr ou ao Jellyfin indisponível.')
    data = sync.get('data') if isinstance(sync, dict) else None
    if isinstance(data, dict) and isinstance(data.get('pending'), int):
        try:
            when = datetime.fromisoformat(data['at'].replace('Z', '+00:00')).astimezone().strftime('%d/%m às %H:%M')
        except (KeyError, ValueError, TypeError):
            when = 'horário desconhecido'
        result['lines'].append(f"Última sincronização ({when}): {data['pending']} arquivo(s) aguardando cópia; isso não conta downloads ou análises pendentes.")
    return result


def parse_cleanup_log(text):
    progress = None
    current = None
    for line in text.splitlines():
        if line.startswith('Conferindo: '):
            current = line.removeprefix('Conferindo: ')
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get('modo') == 'aplicar' and isinstance(entry.get('candidatos'), int):
            progress = {'candidates': entry['candidatos'], 'removed': 0, 'bytes': 0}
            current = None
        elif progress is not None and isinstance(entry.get('bytes'), int) and entry.get('removido'):
            progress['removed'] += 1
            progress['bytes'] += entry['bytes']
            current = None
    if progress is not None:
        progress['current'] = current
    return progress


def cleanup_activity(pid, log_path):
    """Lê o processo filho e o registro da rodada sem interferir na limpeza."""
    result = {'worker_active': False}
    try:
        children = (Path('/proc') / str(pid) / 'task' / str(pid) / 'children').read_text().split()
        for child in children:
            cmd = (Path('/proc') / child / 'cmdline').read_bytes().split(b'\0')
            if str(ROOT / 'media-stack/clean-published-copies.py').encode() in cmd and b'--apply' in cmd:
                result['worker_active'] = True
                break
    except OSError:
        pass
    try:
        if log_path.stat().st_size > 5 * 1024 * 1024:
            return result
        progress = parse_cleanup_log(log_path.read_text(encoding='utf-8', errors='replace'))
        if progress is not None:
            progress['at'] = datetime.fromtimestamp(log_path.stat().st_mtime, timezone.utc).astimezone().strftime('%d/%m às %H:%M:%S')
            result['progress'] = progress
    except OSError:
        pass
    return result


def collect():
    from datetime import datetime, timezone
    result = {'at': datetime.now(timezone.utc).isoformat()}
    session = requests.Session()
    session.trust_env = False
    try:
        credentials = json.loads((ROOT / 'secrets/media-stack.json').read_text())
    except Exception:
        credentials = {}
    series_data = None
    movies_data = None
    for name, port, key, route in (('series', 8989, 'sonarr_key', 'series'), ('movies', 7878, 'radarr_key', 'movie')):
        try:
            response = session.get(f'http://192.168.250.10:{port}/api/v3/{route}', headers={'X-Api-Key': credentials[key]}, timeout=10)
            response.raise_for_status()
            if name == 'series':
                series_data = response.json()
                items = [{'title': x['title'], 'files': x.get('statistics', {}).get('episodeFileCount'), 'total': x.get('statistics', {}).get('episodeCount')} for x in series_data]
            else:
                movies_data = response.json()
                items = [{'title': x['title'], 'hasFile': x.get('hasFile')} for x in movies_data]
            result[name] = {'items': items}
        except Exception as exc:
            result[name] = {'error': type(exc).__name__}
    try:
        jelly_key = json.loads((ROOT / 'secrets/jellyfin-host.json').read_text())['api_key']
        jelly_headers = {'Authorization': 'MediaBrowser Client="Lab", Device="Fedora", DeviceId="painel-local", Version="1", Token="' + jelly_key + '"'}
        def jelly_items(kind):
            response = session.get('http://127.0.0.1:8096/Items', params={'Recursive': 'true', 'IncludeItemTypes': kind,
                'Fields': 'Path,ProviderIds,SeriesId,ParentIndexNumber,IndexNumber', 'Limit': 10000}, headers=jelly_headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            if len(data.get('Items', [])) != data.get('TotalRecordCount'):
                raise ValueError('Catálogo incompleto')
            return data['Items']
        result['jellyfin'] = {'at': datetime.now(timezone.utc).isoformat()}
        try:
            if not isinstance(series_data, list):
                raise RuntimeError('Sonarr indisponível')
            jelly_series = jelly_items('Series')
            jelly_episodes = jelly_items('Episode')
            episodes_by_id = {}
            for item in series_data:
                if not item.get('monitored'):
                    continue
                try:
                    response = session.get('http://192.168.250.10:8989/api/v3/episode', params={'seriesId': item['id']},
                        headers={'X-Api-Key': credentials['sonarr_key']}, timeout=15)
                    response.raise_for_status()
                    episodes_by_id[item['id']] = response.json()
                except Exception:
                    episodes_by_id[item['id']] = None
            targets = catalog_status(series_data, episodes_by_id, jelly_series, jelly_episodes, datetime.now(timezone.utc))
            result['jellyfin']['targets'] = targets
        except Exception as exc:
            result['jellyfin']['series_error'] = type(exc).__name__
        try:
            if not isinstance(movies_data, list):
                raise RuntimeError('Radarr indisponível')
            result['jellyfin']['movies'] = movie_catalog_status(movies_data, jelly_items('Movie'))
        except Exception as exc:
            result['jellyfin']['movies_error'] = type(exc).__name__
    except Exception as exc:
        result['jellyfin'] = {'error': type(exc).__name__}
    try:
        response = session.get('http://192.168.250.10:8989/api/v3/command', headers={'X-Api-Key': credentials['sonarr_key']}, timeout=10)
        response.raise_for_status()
        result['commands'] = {'items': [{k: x.get(k) for k in ('name', 'status', 'message', 'started')} for x in response.json() if x.get('status') in ('queued', 'started')]}
    except Exception as exc:
        result['commands'] = {'error': type(exc).__name__}
    try:
        client = connect()
        torrents = json.loads(request(client, 'torrents/info'))
        result['torrents'] = {'items': [{k: x.get(k) for k in ('name', 'state', 'progress', 'dlspeed', 'tags', 'content_path')} for x in torrents]}
    except Exception as exc:
        result['torrents'] = {'error': type(exc).__name__}
    try:
        result['triage'] = json.loads(subprocess.run(
            ['ssh', '-F', str(ROOT / 'config/ssh_config'), '-o', 'StrictHostKeyChecking=yes',
             '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', 'lab-downloads-admin', 'sudo -n python3 -'],
            input=(ROOT / 'media-stack/painel-triagem.py').read_text(), text=True,
            capture_output=True, check=True, timeout=20).stdout)
    except Exception as exc:
        result['triage'] = {'error': type(exc).__name__}
    try:
        service = subprocess.run(['systemctl', 'show', 'lab-jellyfin-sync.service', '-p', 'ActiveState', '--value'],
                                 text=True, capture_output=True, check=True, timeout=5).stdout.strip()
        result['sync'] = {'data': json.loads((ROOT / 'jellyfin/state/last-run.json').read_text()), 'service': service}
    except Exception as exc:
        result['sync'] = {'error': type(exc).__name__}
    try:
        data = json.loads((ROOT / 'state/cleanup-after-import-status.json').read_text())
        pid = data.get('pid')
        active = False
        if isinstance(pid, int) and pid > 0:
            try:
                cmdline = (Path('/proc') / str(pid) / 'cmdline').read_bytes().split(b'\0')
                active = str(ROOT / 'media-stack/clean-after-import.py').encode() in cmdline
            except OSError:
                pass
        result['cleanup'] = {'data': data, 'active': active}
        if active and data.get('state') == 'limpando':
            result['cleanup'].update(cleanup_activity(pid, ROOT / 'state/cleanup-after-import.log'))
    except FileNotFoundError:
        result['cleanup'] = {'data': None}
    except Exception as exc:
        result['cleanup'] = {'error': type(exc).__name__}
    result['overview'] = progress_overview(result['cleanup'], result['sync'], jellyfin=result['jellyfin'])
    return result


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get('Host', '').split(':')[0] not in ('127.0.0.1', 'localhost'):
            self.send_error(403)
            return
        path = urlsplit(self.path).path
        if path == '/':
            body, content_type = HTML.encode(), 'text/html; charset=utf-8'
        elif path == '/api/status':
            body, content_type = json.dumps(collect(), ensure_ascii=False).encode(), 'application/json; charset=utf-8'
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    print('Painel local: http://127.0.0.1:8765', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8765), Handler).serve_forever()
