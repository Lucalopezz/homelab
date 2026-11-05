#!/usr/bin/env python3
"""Consulta episódios monitorados de uma série no Sonarr e no Jellyfin.

Por padrão não modifica nada. --rescan solicita ao Sonarr uma releitura da
biblioteca; não solicita downloads e não apaga arquivos.
"""
import argparse
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys
import time
import requests

ROOT=Path(__file__).resolve().parents[1]
SONARR='http://192.168.250.10:8989/api/v3/'
JELLY='http://127.0.0.1:8096/Items'
BUSY={'DownloadedEpisodesScan','ManualImport','RenameFiles','RenameSeries','RescanSeries'}


def parse_seasons(value):
    if value is None:return None
    try:
        result={int(x.strip()) for x in value.split(',') if x.strip()}
    except ValueError as exc:raise argparse.ArgumentTypeError('Use números separados por vírgula, por exemplo 1,2,3.') from exc
    if not result or any(n<=0 for n in result):raise argparse.ArgumentTypeError('As temporadas devem ser números positivos.')
    return result


def choose_series(series,series_id=None,title=None):
    if series_id is not None:
        matches=[s for s in series if s.get('id')==series_id]
    else:
        matches=[s for s in series if s.get('title','').casefold()==(title or '').casefold()]
    if len(matches)!=1:raise ValueError('Série não encontrada ou título ambíguo; use --list e --id.')
    if not matches[0].get('monitored'):raise ValueError('A série não está monitorada no Sonarr.')
    return matches[0]


def jelly_items(session,headers,kind):
    response=session.get(JELLY,params={'Recursive':'true','IncludeItemTypes':kind,'Fields':'Path,ProviderIds,SeriesId,ParentIndexNumber,IndexNumber','Limit':10000},headers=headers,timeout=20)
    response.raise_for_status();data=response.json()
    if len(data.get('Items',[]))!=data.get('TotalRecordCount'):raise ValueError('O catálogo do Jellyfin está incompleto.')
    return data['Items']


def report(session,series,sonarr_headers,seasons=None):
    response=session.get(SONARR+'episode',params={'seriesId':series['id']},headers=sonarr_headers,timeout=20);response.raise_for_status()
    episodes=response.json()
    if seasons is not None:episodes=[x for x in episodes if x.get('seasonNumber') in seasons]
    jelly_key=json.loads((ROOT/'secrets/jellyfin-host.json').read_text())['api_key']
    jelly_headers={'Authorization':'MediaBrowser Client="Lab", Device="Fedora", DeviceId="series-status", Version="1", Token="'+jelly_key+'"'}
    spec=importlib.util.spec_from_file_location('painel_local',ROOT/'media-stack/painel-local.py');panel=importlib.util.module_from_spec(spec);spec.loader.exec_module(panel)
    targets=panel.catalog_status([series],{series['id']:episodes},jelly_items(session,jelly_headers,'Series'),jelly_items(session,jelly_headers,'Episode'),dt.datetime.now(dt.timezone.utc))
    result=targets[series['title']]
    if result.get('error'):raise ValueError(result['error'])
    return {'serie':series['title'],'id':series['id'],'temporadas':sorted(seasons) if seasons else 'monitoradas',
            'episodios_lancados':result['expected'],'sem_arquivo_sonarr':result['sonarr_missing'],
            'no_jellyfin':result['expected']-result['jellyfin_missing'],'faltando_jellyfin':result['jellyfin_missing']}


def busy_commands(commands):
    return [x for x in commands if x.get('name') in BUSY and x.get('status') in ('started','queued')]


def main(args):
    credentials=json.loads((ROOT/'secrets/media-stack.json').read_text())
    session=requests.Session();session.trust_env=False;headers={'X-Api-Key':credentials['sonarr_key']}
    def get(path,params=None):
        response=session.get(SONARR+path,params=params,headers=headers,timeout=20);response.raise_for_status();return response.json()
    series=get('series')
    if args.list:
        print(json.dumps([{'id':s['id'],'titulo':s['title'],'monitorada':s.get('monitored')} for s in series],ensure_ascii=False,indent=2));return 0
    selected=choose_series(series,args.id,args.title)
    if args.rescan:
        deadline=time.monotonic()+args.timeout
        while True:
            active=busy_commands(get('command'))
            if not active:break
            if not args.wait:raise RuntimeError('Há importação ou releitura em andamento; aguarde ou use --wait.')
            if time.monotonic()>=deadline:raise TimeoutError('O prazo para aguardar importações terminou.')
            print('Aguardando importações ou releituras em andamento...',flush=True);time.sleep(min(30,max(0,deadline-time.monotonic())))
        response=session.post(SONARR+'command',json={'name':'RescanSeries','seriesId':selected['id']},headers=headers,timeout=30);response.raise_for_status();command=response.json();ident=command['id']
        print(json.dumps({'releitura_solicitada':ident,'estado':command.get('status')},ensure_ascii=False),flush=True)
        if not args.wait:return 0
        while True:
            command=get('command/'+str(ident));status=command.get('status')
            if status=='completed':break
            if status in ('failed','aborted','cancelled'):raise RuntimeError('A releitura não foi concluída: '+str(status))
            if time.monotonic()>=deadline:raise TimeoutError('O prazo para a releitura terminou.')
            time.sleep(min(15,max(0,deadline-time.monotonic())))
    result=report(session,selected,headers,args.seasons)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    selection=p.add_mutually_exclusive_group(required=True)
    selection.add_argument('--list',action='store_true',help='listar séries e seus IDs')
    selection.add_argument('--id',type=int,help='ID da série no Sonarr')
    selection.add_argument('--title',help='título exato da série no Sonarr')
    p.add_argument('--seasons',type=parse_seasons,help='temporadas a conferir, por exemplo 1,2,3; padrão: todas monitoradas')
    p.add_argument('--rescan',action='store_true',help='solicitar releitura no Sonarr; não baixa nem remove mídia')
    p.add_argument('--wait',action='store_true',help='aguardar importações e releitura; requer --rescan')
    p.add_argument('--timeout',type=int,default=21600,help='prazo total da espera em segundos (padrão: 21600)')
    return p


if __name__=='__main__':
    p=parser();args=p.parse_args()
    if args.id is not None and args.id<=0:p.error('--id deve ser positivo')
    if args.wait and not args.rescan:p.error('--wait requer --rescan')
    if args.list and (args.rescan or args.seasons):p.error('--list não aceita --rescan ou --seasons')
    if args.timeout<=0:p.error('--timeout deve ser positivo')
    try:raise SystemExit(main(args))
    except (OSError,ValueError,RuntimeError,requests.RequestException) as exc:
        print('Não foi possível concluir a consulta:',str(exc)[:400],file=sys.stderr);raise SystemExit(1)
