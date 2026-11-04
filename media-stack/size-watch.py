#!/usr/bin/env python3
"""Detecta mídia acima do limite do ClamAV e tenta alternativas seguras."""
import datetime as dt
import json
import re
import time
from pathlib import Path, PurePosixPath

LIMIT = 2 * 1024**3
VIDEO = {'.mkv', '.mp4', '.m4v', '.webm', '.avi', '.mov', '.ts', '.m2ts'}
EXTRAS = {'extras', 'extra', 'featurettes', 'featurette', 'special features', 'bonus'}
ELIGIBLE = {'downloading', 'stalledDL', 'metaDL', 'queuedDL'}
BACKOFF = 24 * 3600


def classify(files):
    """Retorna índices de vídeos grandes e distingue extras por pasta explícita."""
    result = []
    for index, f in enumerate(files):
        name = f.get('name', '')
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or '..' in path.parts or '\\' in name
                or path.suffix.lower() not in VIDEO or f.get('priority', 0) <= 0
                or f.get('size', 0) < LIMIT):
            continue
        extra = any(part.casefold() in EXTRAS for part in path.parts[:-1])
        result.append((index, f, extra))
    return result


def save(path, state):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def inspect(session, base, sonarr, torrents, state, save_state, now=None):
    """Opera somente em downloads em andamento; nunca apaga arquivos."""
    now = time.time() if now is None else now
    state.setdefault('items', {})
    searched = False
    for t in torrents:
        if t.get('category') != 'sonarr' or t.get('state') not in ELIGIBLE:
            continue
        torrent_hash = t['hash']
        r = session.get(base + 'torrents/files', params={'hash': torrent_hash}, timeout=12)
        r.raise_for_status(); files = r.json()
        remaining = sum(f.get('priority', 0) > 0 and Path(f.get('name','')).suffix.lower() in VIDEO for f in files)
        for index, f, extra in classify(files):
            key = torrent_hash + ':' + str(index)
            item = state['items'].setdefault(key, {})
            item.update({'torrent': t.get('name',''), 'file': f['name'], 'size': f['size'],
                         'updated': dt.datetime.now(dt.timezone.utc).isoformat()})
            ident = f.get('index', index)
            if extra and remaining > 1:
                # Registrar antes da operação; reexecução após falha é idempotente.
                item.update(status='extra-grande', reason='Extra acima de 2 GiB: retirada solicitada da seleção.')
                save_state()
                response = session.post(base + 'torrents/filePrio', data={'hash': torrent_hash, 'id': ident, 'priority': 0}, timeout=12)
                response.raise_for_status()
                item.update(status='extra-ignorado', reason='Extra acima de 2 GiB retirado da seleção; arquivo já baixado não é apagado.')
                remaining -= 1
                save_state()
                continue
            if extra:
                item.update(status='revisao', reason='Extra grande é o único vídeo selecionado; sem alteração.')
                continue
            if item.get('alternative'):
                continue
            if searched or now - item.get('attempt_at', 0) < BACKOFF:
                item.setdefault('status', 'episodio-grande')
                item.setdefault('reason', 'Vídeo acima de 2 GiB aguardando busca de alternativa.')
                continue
            item.update(status='episodio-grande', reason='Vídeo acima de 2 GiB; buscando uma versão menor quando a identificação for segura.')
            # Só episódios com numeração explícita e parse inequívoco do Sonarr.
            match = re.search(r'(?i)(?<![a-z0-9])s(\d{1,2})e(\d{1,3})(?!\d)', f['name'])
            if not match or re.search(r'(?i)s\d{1,2}e\d{1,3}(?:e\d{1,3}|[-_]e?\d{1,3})', f['name']):
                item.update(status='revisao', reason='Vídeo grande sem episódio inequívoco; busca manual necessária.')
                continue
            searched = True
            item['attempt_at'] = now
            item['reason'] = 'Consultando fontes para o episódio grande.'
            save_state()  # Evita solicitações repetidas se o processo for interrompido.
            try:
                headers = {'X-Api-Key': sonarr['api_key']}
                api = sonarr['url'].rstrip('/') + '/api/v3/'
                p = session.get(api + 'parse', params={'title': Path(f['name']).name}, headers=headers, timeout=20)
                p.raise_for_status(); parsed = p.json(); eps = parsed.get('episodes') or []
                season, episode = map(int, match.groups())
                if (len(eps) != 1 or not eps[0].get('id') or eps[0].get('seasonNumber') != season
                        or eps[0].get('episodeNumber') != episode or not (parsed.get('series') or {}).get('id')):
                    raise ValueError('Sonarr não identificou um único episódio com segurança')
                eid = eps[0]['id']
                releases = session.get(api + 'release', params={'episodeId': eid}, headers=headers, timeout=60)
                releases.raise_for_status()
                pattern = re.compile(r'(?i)(?<![a-z0-9])s0*%de0*%d(?!\d)' % (season, episode))
                options = [x for x in releases.json() if x.get('approved') and x.get('protocol') == 'torrent'
                           and 0 < x.get('size', 0) < LIMIT and (x.get('seeders') or 0) > 0
                           and pattern.search(x.get('title','')) and not re.search(r'(?i)s\d{1,2}e\d{1,3}(?:e\d{1,3}|[-_]e?\d{1,3})', x.get('title',''))
                           and x.get('guid') and x.get('indexerId')]
                if not options:
                    item.update(status='sem-fonte', reason='Nenhuma fonte menor aprovada e com fonte disponível; nova tentativa depois.')
                    continue
                pick = max(options, key=lambda x: (x.get('seeders') or 0))
                post = session.post(api + 'release', json={'guid':pick['guid'], 'indexerId':pick['indexerId']}, headers=headers, timeout=30)
                post.raise_for_status()
                item.update(status='alternativa-solicitada', reason='Sonarr aceitou uma versão menor; aguarda download e triagem.', alternative=pick['title'])
                save_state()
                if remaining > 1:
                    # Nunca retirar o único vídeo e nunca remover dados já baixados.
                    response = session.post(base + 'torrents/filePrio', data={'hash':torrent_hash,'id':ident,'priority':0}, timeout=12)
                    response.raise_for_status(); remaining -= 1
                    item['reason'] += ' O episódio grande foi retirado da seleção do pacote.'
            except Exception as exc:
                item.update(status='revisao', reason='Busca automática não concluída: ' + type(exc).__name__)
            finally:
                save_state()
    save_state()
