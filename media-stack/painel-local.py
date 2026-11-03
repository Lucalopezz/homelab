#!/usr/bin/env python3
"""Painel local de consulta ao laboratório. Não altera downloads."""
import json
import os
import subprocess
import sys
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
</style><h1>Laboratório de mídia</h1><p>Consulta local. As informações são atualizadas ao clicar no botão.</p>
<button onclick="refresh()">Atualizar</button> <input id="filter" placeholder="Filtrar por nome ou estado" oninput="render()"><p id="updated"></p><div id="content"></div>
<script>
function section(title, rows, columns){let s=document.createElement('section'),h=document.createElement('h2');h.textContent=title;s.append(h);let t=document.createElement('table'),head=document.createElement('tr');columns.forEach(c=>{let x=document.createElement('th');x.textContent=c[0];head.append(x)});t.append(head);rows.forEach(r=>{let tr=document.createElement('tr');columns.forEach(c=>{let td=document.createElement('td');td.textContent=String(c[1](r)??'—');tr.append(td)});t.append(tr)});s.append(t);return s}
let current=null;
function render(){if(!current)return;let data=current,target=document.getElementById('content');target.textContent='';let filter=document.getElementById('filter').value.toLocaleLowerCase();for(let [key,title,cols] of [['series','Séries no Sonarr',[['Título',x=>x.title],['Episódios com arquivo',x=>x.files],['Episódios monitorados',x=>x.total]]],['movies','Filmes no Radarr',[['Título',x=>x.title],['Arquivo',x=>x.hasFile?'Sim':'Não']]],['torrents','Downloads no qBittorrent',[['Nome',x=>x.name],['Estado',x=>x.state],['Progresso',x=>Math.round(x.progress*100)+'%'],['Velocidade',x=>Math.round(x.dlspeed/1024)+' KiB/s'],['Etiquetas',x=>x.tags],['Caminho informado na VM',x=>x.content_path]]],['triage','Triagem: último registro por download',[['Nome',x=>x.name],['Estado registrado',x=>x.status],['Fase informada',x=>x.phase||'Não registrada'],['Arquivo informado',x=>x.file||'Não identificado'],['Destino registrado na VM',x=>x.destination||'Não registrado'],['Motivo',x=>x.reason||'—'],['Atualizado em',x=>x.updated]]]]){let source=data[key];if(source.error){let s=document.createElement('section');s.className='error';s.textContent=title+': indisponível — '+source.error;target.append(s)}else{let rows=source.items.filter(x=>!filter||JSON.stringify(x).toLocaleLowerCase().includes(filter));target.append(section(title,rows,cols))}}let info=document.createElement('section');let h=document.createElement('h2');h.textContent='Atividade atual e sincronização';let p=document.createElement('p');p.textContent=data.triage.error?'Atividade da triagem desconhecida':('Serviço de triagem: '+data.triage.service.ActiveState+' / '+data.triage.service.SubState+'. Arquivos identificados em uso: '+(data.triage.active.length?data.triage.active.map(x=>x.phase+': '+x.file).join('; '):'nenhum identificado; isso não prova que a triagem está parada.'));let q=document.createElement('p');q.textContent=data.sync.error?'Sincronização indisponível: '+data.sync.error:'Última sincronização concluída: '+JSON.stringify(data.sync.data)+'; serviço atual: '+data.sync.service+'. O arquivo atualmente copiado não é identificado pelo sincronizador.';info.append(h,p,q);target.prepend(info)}
let loading=false;async function refresh(){if(loading)return;loading=true;let target=document.getElementById('content');target.textContent='Consultando…';try{let r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error('Falha na consulta');current=await r.json();document.getElementById('updated').textContent='Consulta: '+new Date(current.at).toLocaleString();render()}catch(e){target.textContent='Não foi possível consultar o painel: '+e.message}finally{loading=false}}
refresh();setInterval(refresh,60000);</script></html>'''


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
