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
from importlib.util import module_from_spec, spec_from_file_location
from urllib.parse import urlsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from check_qbittorrent import connect, request

_targets_spec = spec_from_file_location('cleanup_targets', ROOT / 'media-stack/clean-after-import.py')
cleanup_targets = module_from_spec(_targets_spec)
_targets_spec.loader.exec_module(cleanup_targets)

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
function render(){if(!current)return;let data=current,target=document.getElementById('content');target.textContent='';let filter=document.getElementById('filter').value.toLocaleLowerCase();for(let [key,title,cols] of [['series','Séries no Sonarr',[['Título',x=>x.title],['Episódios com arquivo',x=>x.files],['Episódios monitorados',x=>x.total]]],['movies','Filmes no Radarr',[['Título',x=>x.title],['Arquivo',x=>x.hasFile?'Sim':'Não']]],['torrents','Downloads no qBittorrent',[['Nome',x=>x.name],['Estado',x=>x.state],['Progresso',x=>Math.round(x.progress*100)+'%'],['Velocidade',x=>Math.round(x.dlspeed/1024)+' KiB/s'],['Etiquetas',x=>x.tags],['Caminho informado na VM',x=>x.content_path]]],['triage','Triagem: último registro por download',[['Nome',x=>x.name],['Estado registrado',x=>x.status],['Fase informada',x=>x.phase||'Não registrada'],['Arquivo informado',x=>x.file||'Não identificado'],['Destino registrado na VM',x=>x.destination||'Não registrado'],['Motivo',x=>x.reason||'—'],['Atualizado em',x=>x.updated]]]]){let source=data[key];if(source.error){let s=document.createElement('section');s.className='error';s.textContent=title+': indisponível — '+source.error;target.append(s)}else{let rows=source.items.filter(x=>!filter||JSON.stringify(x).toLocaleLowerCase().includes(filter));target.append(section(title,rows,cols))}}let info=document.createElement('section');let h=document.createElement('h2');h.textContent='Atividade atual e sincronização';let p=document.createElement('p');p.textContent=data.triage.error?'Atividade da triagem desconhecida':('Serviço de triagem: '+data.triage.service.ActiveState+' / '+data.triage.service.SubState+'. Arquivos identificados em uso: '+(data.triage.active.length?data.triage.active.map(x=>x.phase+': '+x.file).join('; '):'nenhum identificado; isso não prova que a triagem está parada.'));let q=document.createElement('p');q.textContent=data.sync.error?'Sincronização indisponível: '+data.sync.error:'Última sincronização concluída: '+JSON.stringify(data.sync.data)+'; serviço atual: '+data.sync.service+'. O arquivo atualmente copiado não é identificado pelo sincronizador.';let a=document.createElement('p');if(data.commands.error){a.textContent='Comandos do Sonarr: indisponíveis'}else{let cmds=data.commands.items;a.textContent=cmds.length?'Sonarr: '+cmds.map(x=>{let msg=x.message||x.status;let match=msg.match(/Processing file (\\d+) of (\\d+)/i);return x.name+': '+(match?'processando arquivo '+match[1]+' de '+match[2]:msg)}).join('; '):'Sonarr: nenhuma busca ou importação em execução'}let b=document.createElement('p');let rec=data.triage.error?null:data.triage.recovery;if(!rec){b.textContent='Recuperação automática: estado indisponível'}else{let labels={none:'sem ação',import:'importação solicitada',search:'busca solicitada',error:'erro'};b.textContent='Recuperação automática: '+(labels[rec.action]||rec.action)+'; última consulta '+new Date(rec.at).toLocaleString()+(rec.notes&&rec.notes.length?' — '+rec.notes.join(' '):'')+(rec.reason?' — '+rec.reason:'')}let z=document.createElement('p');let clean=data.cleanup&&data.cleanup.data;if(!clean){z.textContent='Limpeza após importação: sem agendamento registrado'}else{let names={aguardando_importacao:'aguardando importação',aguardando_publicacao:'aguardando publicação no Jellyfin',aguardando_consulta:'aguardando serviços',limpando:'conferindo e limpando',concluido:'concluída',erro:'interrompida com erro'};if(['aguardando_importacao','aguardando_publicacao','aguardando_consulta','limpando'].includes(clean.state)&&!data.cleanup.active)names[clean.state]='processo interrompido; conferir registro';else if(clean.state==='limpando'&&!data.cleanup.worker_active)names[clean.state]='verificador de cópias não identificado';let extra='';if(clean.targets){let n=Object.values(clean.targets).reduce((sum,x)=>sum+x.jellyfin_missing,0);extra='; episódios ainda não catalogados: '+n}z.textContent='Limpeza após importação: '+(names[clean.state]||clean.state)+extra+(clean.reason?' — '+clean.reason:'')+(clean.state==='limpando'?'; iniciada em ':'; atualizado em ')+new Date(clean.at).toLocaleString()}info.append(h,p,a,b,q,z);target.prepend(info);target.prepend(overview(data.overview))}
let loading=false;async function refresh(){if(loading)return;loading=true;let target=document.getElementById('content');target.textContent='Consultando…';try{let r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error('Falha na consulta');current=await r.json();document.getElementById('updated').textContent='Consulta: '+new Date(current.at).toLocaleString();render()}catch(e){target.textContent='Não foi possível consultar o painel: '+e.message}finally{loading=false}}
refresh();setInterval(refresh,60000);</script></html>'''


def progress_overview(cleanup, sync, now=None, jellyfin=None):
    """Resume fontes atuais sem confundir o início da limpeza com um sinal de vida."""
    data = cleanup.get('data') if isinstance(cleanup, dict) else None
    data = data if isinstance(data, dict) else {}
    now = now or datetime.now(timezone.utc)
    try:
        at = datetime.fromisoformat(data['at'].replace('Z', '+00:00'))
        fresh = 0 <= (now - at).total_seconds() <= 180
    except (KeyError, ValueError, TypeError):
        fresh = False
    state = data.get('state')
    result = {'at': data.get('at'), 'lines': []}
    live_targets = jellyfin.get('targets') if isinstance(jellyfin, dict) else None
    live_ok = isinstance(live_targets, dict) and all(
        isinstance(live_targets.get(title), dict) and not live_targets[title].get('error')
        for title in cleanup_targets.TARGETS
    )
    if live_ok:
        result['at'] = jellyfin.get('at')
    def append_observations():
        targets = live_targets if live_ok else data.get('targets')
        if not live_ok:
            result['lines'].append('Catálogo atual indisponível; números anteriores podem ter mudado.')
        if isinstance(targets, dict):
            for title, item in targets.items():
                if isinstance(item, dict) and all(isinstance(item.get(k), int) for k in ('expected', 'jellyfin_missing', 'sonarr_missing')):
                    result['lines'].append(f"{title}: {item['expected'] - item['jellyfin_missing']}/{item['expected']} no Jellyfin; {item['sonarr_missing']} sem arquivo no Sonarr.")
        s = sync.get('data') if isinstance(sync, dict) else None
        if isinstance(s, dict) and isinstance(s.get('pending'), int):
            try:
                when = datetime.fromisoformat(s['at'].replace('Z', '+00:00')).astimezone().strftime('%d/%m às %H:%M')
            except (KeyError, ValueError, TypeError):
                when = 'horário desconhecido'
            result['lines'].append(f"Última sincronização ({when}): {s['pending']} arquivo(s) aguardando cópia. Arquivos e episódios são contagens diferentes.")
    if not data:
        result.update(title='Situação dos pedidos', lines=['Não há estado disponível para a limpeza agendada.'])
        append_observations()
        return result
    if state in ('aguardando_importacao', 'aguardando_publicacao', 'aguardando_consulta', 'limpando') and not cleanup.get('active'):
        result.update(title='Acompanhamento interrompido', lines=['O processo de espera ou limpeza não está ativo. O estado dos pedidos precisa ser conferido novamente.'])
        append_observations()
        return result
    if not fresh and state not in ('concluido', 'erro', 'limpando'):
        result.update(title='Situação dos pedidos desatualizada', lines=['Ainda não foi possível confirmar o estado atual. Os números anteriores podem ter mudado.'])
        append_observations()
        return result
    if state == 'aguardando_importacao':
        result['title'] = 'Importação para o Sonarr em andamento'
        progress = data.get('progress') or ''
        match = re.search(r'Processing file (\d+) of (\d+)', progress, re.IGNORECASE)
        result['lines'].append('Arquivo ' + match.group(1) + ' de ' + match.group(2) + ' na importação.' if match else 'A importação ainda não foi confirmada como concluída.')
        result['lines'].append('Depois, os arquivos precisam ser publicados e reconhecidos pelo Jellyfin. A limpeza está aguardando.')
    elif state == 'aguardando_publicacao':
        result['title'] = 'Publicação no Jellyfin ainda pendente'
        result['lines'].append('A importação terminou, mas nem todos os episódios foram encontrados no catálogo do Jellyfin. A limpeza ainda não começou.')
    elif state == 'aguardando_consulta':
        result.update(title='Aguardando confirmação dos serviços', lines=['Não foi possível confirmar o estado dos pedidos; a limpeza permanece em espera.'])
    elif state == 'limpando':
        if cleanup.get('worker_active'):
            result.update(title='Limpeza em andamento', lines=['O verificador de cópias está ativo; o catálogo é consultado separadamente abaixo.'])
        else:
            result.update(title='Estado da limpeza não confirmado', lines=['O processo de espera está ativo, mas o verificador de cópias não foi identificado.'])
        progress = cleanup.get('progress') or {}
        if isinstance(progress.get('removed'), int) and isinstance(progress.get('bytes'), int):
            result['lines'].append(f"Nesta etapa da limpeza: {progress['removed']} vídeo(s) removido(s), {progress['bytes'] / 1024**3:.1f} GiB liberados na VM.")
        if progress.get('current'):
            result['lines'].append('Último arquivo em conferência: ' + progress['current'])
        if progress.get('at'):
            result['lines'].append('Último registro da limpeza: ' + progress['at'])
    elif state == 'concluido':
        result.update(title='Conferência e limpeza concluídas', lines=['A última conferência confirmou os episódios solicitados nos dois catálogos.'])
    elif state == 'erro':
        result.update(title='Limpeza interrompida', lines=[data.get('reason') or 'O processo terminou com erro; consulte o registro antes de tentar novamente.'])
    else:
        result.update(title='Situação dos pedidos não confirmada', lines=['O estado retornado não é reconhecido.'])
    append_observations()
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
    for name, port, key, route in (('series', 8989, 'sonarr_key', 'series'), ('movies', 7878, 'radarr_key', 'movie')):
        try:
            response = session.get(f'http://192.168.250.10:{port}/api/v3/{route}', headers={'X-Api-Key': credentials[key]}, timeout=10)
            response.raise_for_status()
            if name == 'series':
                items = [{'title': x['title'], 'files': x.get('statistics', {}).get('episodeFileCount'), 'total': x.get('statistics', {}).get('episodeCount')} for x in response.json()]
            else:
                items = [{'title': x['title'], 'hasFile': x.get('hasFile')} for x in response.json()]
            result[name] = {'items': items}
        except Exception as exc:
            result[name] = {'error': type(exc).__name__}
    try:
        jelly_key = json.loads((ROOT / 'secrets/jellyfin-host.json').read_text())['api_key']
        response = session.get('http://127.0.0.1:8096/Items', params={'Recursive': 'true', 'IncludeItemTypes': 'Episode',
            'Fields': 'Path,ParentIndexNumber,IndexNumber', 'Limit': 10000}, headers={'Authorization':
            'MediaBrowser Client="Lab", Device="Fedora", DeviceId="painel-local", Version="1", Token="' + jelly_key + '"'}, timeout=15)
        response.raise_for_status()
        data = response.json()
        if len(data.get('Items', [])) != data.get('TotalRecordCount'):
            raise ValueError('Catálogo incompleto')
        targets = {}
        for title, spec in cleanup_targets.TARGETS.items():
            try:
                episodes = session.get('http://192.168.250.10:8989/api/v3/episode', params={'seriesId': spec['series_id']},
                    headers={'X-Api-Key': credentials['sonarr_key']}, timeout=15)
                episodes.raise_for_status()
                targets[title] = cleanup_targets.target_status(episodes.json(), data['Items'], spec['folder'],
                    spec['seasons'], spec['minimum'], datetime.now(timezone.utc))
            except Exception as exc:
                targets[title] = {'error': type(exc).__name__}
        result['jellyfin'] = {'at': datetime.now(timezone.utc).isoformat(), 'targets': targets}
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
