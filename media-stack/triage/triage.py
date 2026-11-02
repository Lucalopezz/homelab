#!/usr/bin/env python3
"""Libera cópias de mídia somente após validação de tipo e resposta limpa do ClamAV."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import subprocess
import time

import requests

RAW = Path('/srv/downloads/recebidos')
PUBLIC = Path('/srv/downloads/aprovados')
STATE = Path('/var/lib/media-triage')
MAX_MIB = 2560
MAX_BYTES = MAX_MIB * 1024 * 1024
# MaxScanTime do clamd é 1200 s; o cliente precisa permitir o término do motor.
SCAN_TIMEOUT = 1260
VIDEO = {'.mkv', '.mp4', '.m4v', '.webm', '.avi', '.mov', '.ts', '.m2ts'}
SUBTITLE = {'.srt', '.ass', '.ssa', '.vtt'}
DENIED = {'.exe', '.scr', '.bat', '.cmd', '.msi', '.lnk', '.com', '.vbs',
          '.pif', '.ps1', '.js', '.jse', '.wsf', '.hta', '.url', '.jar',
          '.rar', '.zip', '.7z', '.iso', '.img', '.dmg', '.sh', '.deb', '.rpm'}
CATEGORIES = {'sonarr': 'series', 'radarr': 'filmes', '': 'manuais', 'manual': 'manuais'}

class Rejected(Exception):
    pass

class Review(Exception):
    pass

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def safe_parts(name):
    path = PurePosixPath(name)
    if (not name or not path.parts or '\\' in name or any(ord(char) < 32 for char in name) or path.is_absolute()
            or '..' in path.parts or len(path.parts) > 10 or len(name) > 1024):
        raise Rejected('Nome de arquivo ou caminho inválido')
    return path.parts

def open_source(path):
    """Abrir abaixo de RAW sem seguir links, inclusive durante a travessia."""
    relative = path.relative_to(RAW)
    safe_parts(relative.as_posix())
    fd = os.open(RAW, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        result = os.open(relative.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    finally:
        os.close(fd)
    if not stat.S_ISREG(os.fstat(result).st_mode):
        os.close(result)
        raise Rejected('Tipo de arquivo não regular')
    return result

def stamp(info):
    return info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns

def selected_media(files):
    """Selecionar somente mídia desejada; manter a recusa de distribuições perigosas."""
    if len(files) > 2000:
        raise Review('Torrent com quantidade excessiva de arquivos')
    accepted = []
    for item in files:
        parts = safe_parts(item['name'])
        suffix = Path(parts[-1]).suffix.lower()
        if suffix in DENIED or re.search(r'\.(?:part\d+\.rar|r\d\d|7z\.\d+)$', item['name'], re.I):
            raise Rejected('Executável, script, imagem de disco ou pacote compactado na distribuição')
        if suffix not in VIDEO | SUBTITLE or item.get('priority') == 0:
            continue
        if not item.get('priority') or item.get('progress', 0) < 1:
            raise Review('Arquivo de mídia não foi baixado integralmente')
        if item['size'] > MAX_BYTES:
            raise Review(f'Arquivo acima de {MAX_MIB} MiB: necessária revisão manual')
        accepted.append((item, parts, suffix))
    if not any(suffix in VIDEO for _, _, suffix in accepted):
        raise Rejected('Torrent sem arquivo de vídeo utilizável')
    return accepted

def copy_source(source, destination):
    fd = open_source(source)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    digest = hashlib.sha256()
    try:
        before = os.fstat(fd)
        if before.st_size > MAX_BYTES:
            raise Review(f'Arquivo acima de {MAX_MIB} MiB: ClamAV não pode examiná-lo integralmente')
        with os.fdopen(fd, 'rb', closefd=False) as src, destination.open('xb') as dst:
            while chunk := src.read(1024 * 1024):
                dst.write(chunk)
                digest.update(chunk)
            dst.flush()
            os.fsync(dst.fileno())
        if stamp(before) != stamp(os.fstat(fd)):
            raise Rejected('Origem mudou durante a cópia')
    finally:
        os.close(fd)
    return digest.hexdigest()

def validate_media(path, normalize_subtitles=False):
    with path.open('rb') as handle:
        header = handle.read(8)
    if header.startswith((b'MZ', b'\x7fELF', b'#!')):
        raise Rejected('Executável ou script disfarçado de mídia')
    if path.suffix.lower() in SUBTITLE:
        if path.stat().st_size > 10 * 1024 * 1024:
            raise Rejected('Legenda excessivamente grande')
        sample = path.read_bytes()
        normalized_digest = None
        try:
            sample.decode('utf-8-sig')
        except UnicodeDecodeError:
            if not normalize_subtitles:
                raise Review('Legenda sem codificação UTF-8: revisar antes de liberar')
            if sample.startswith((b'\xff\xfe', b'\xfe\xff')):
                try:
                    text = sample.decode('utf-16')
                except UnicodeDecodeError as error:
                    raise Review('Legenda UTF-16 incompleta ou inválida') from error
            else:
                try:
                    text = sample.decode('cp1252')
                except UnicodeDecodeError:
                    text = sample.decode('iso-8859-1')
            if any((ord(char) < 32 and char not in '\t\r\n') or 127 <= ord(char) < 160 for char in text):
                raise Review('Legenda contém controles binários não admitidos')
            suffix = path.suffix.lower()
            if suffix == '.srt' and not re.search(r'\d{1,2}:\d{2}:\d{2}[,.]\d{3}\s+-->\s+\d{1,2}:\d{2}:\d{2}', text):
                raise Review('Legenda não reconhecida como SRT')
            if suffix in {'.ass', '.ssa'} and '[events]' not in text.lower():
                raise Review('Legenda não reconhecida como ASS/SSA')
            if suffix == '.vtt' and not text.lstrip().startswith('WEBVTT'):
                raise Review('Legenda não reconhecida como WebVTT')
            sample = text.encode('utf-8')
            path.write_bytes(sample)
            scan(path)
            normalized_digest = hashlib.sha256(sample).hexdigest()
        if b'\x00' in sample:
            raise Rejected('Conteúdo binário em legenda')
        return normalized_digest
    probe = subprocess.run([
        'ffprobe', '-v', 'error', '-max_alloc', '67108864',
        '-protocol_whitelist', 'file,pipe', '-probesize', '10000000',
        '-analyzeduration', '5000000', '-show_entries',
        'stream=codec_type,width,height:format=duration', '-of', 'json', str(path),
    ], capture_output=True, text=True, timeout=180)
    if probe.returncode:
        raise Rejected('Arquivo não reconhecido como vídeo válido')
    data = json.loads(probe.stdout)
    streams = [item for item in data.get('streams', []) if item.get('codec_type') == 'video']
    if not streams or float(data.get('format', {}).get('duration', 0)) < 10:
        raise Rejected('Vídeo sem duração ou trilha de vídeo utilizável')

def scan(path, on_start=None):
    # LOCK_EX funciona em descritor de leitura no Linux. Assim o exportador
    # mantém seu filesystem restrito e compartilha a mesma fila do scanner.
    with (STATE / 'clamav-scan.lock').open('rb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if on_start is not None:
            on_start()
        try:
            result = subprocess.run(['clamdscan', '--fdpass', '--no-summary', str(path)],
                                    capture_output=True, text=True, timeout=SCAN_TIMEOUT)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError('Antivírus excedeu o prazo de análise; arquivo não liberado') from error
    if result.returncode == 1:
        reason = (result.stdout + result.stderr).strip()[-1000:]
        if 'Heuristics.Limits.Exceeded' in reason:
            limit = re.search(r'Heuristics\.Limits\.Exceeded[\w.]*', reason)
            raise Review('Limite de análise do antivírus atingido: ' + (limit.group(0) if limit else 'não especificado'))
        raise Rejected('ClamAV detectou conteúdo suspeito: ' + reason)
    if result.returncode != 0:
        raise RuntimeError('ClamAV indisponível ou não concluiu a análise')

class Pipeline:
    def __init__(self):
        self.config = json.loads(Path('/etc/media-triage/credentials.json').read_text())
        self.qbit = requests.Session()
        self.qbit.trust_env = False
        self.qbit.headers['Referer'] = self.config['qbit']['url'] + '/'
        response = self.qbit.post(self.config['qbit']['url'] + '/api/v2/auth/login',
                                  data={'username': 'admin', 'password': self.config['qbit']['password']}, timeout=10)
        if response.text != 'Ok.':
            raise RuntimeError('Não foi possível autenticar no qBittorrent')
        self.db = sqlite3.connect(STATE / 'state.sqlite3')
        self.db.execute('CREATE TABLE IF NOT EXISTS items (hash TEXT PRIMARY KEY, status TEXT, details TEXT, updated TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, hash TEXT, previous_status TEXT, status TEXT, previous_details TEXT, details TEXT, at TEXT)')
        self.arr = requests.Session()
        self.arr.trust_env = False

    def qget(self, route, **params):
        response = self.qbit.get(self.config['qbit']['url'] + '/api/v2/' + route, params=params, timeout=15)
        response.raise_for_status()
        return response.json()

    def tag(self, torrent_hash, tag):
        self.qbit.post(self.config['qbit']['url'] + '/api/v2/torrents/removeTags',
                       data={'hashes': torrent_hash, 'tags': 'triagem-aprovada,triagem-reprovado,triagem-revisao,triagem-pendente,triagem-em-analise,triagem-substituida'}, timeout=10).raise_for_status()
        response = self.qbit.post(self.config['qbit']['url'] + '/api/v2/torrents/addTags',
                                  data={'hashes': torrent_hash, 'tags': tag}, timeout=10)
        response.raise_for_status()

    def record(self, torrent_hash, status, details):
        timestamp = now()
        encoded = json.dumps(details, ensure_ascii=False)
        with self.db:
            previous = self.db.execute('SELECT status,details FROM items WHERE hash=?', (torrent_hash,)).fetchone()
            self.db.execute('INSERT INTO events (hash,previous_status,status,previous_details,details,at) VALUES (?,?,?,?,?,?)',
                            (torrent_hash, previous[0] if previous else None, status,
                             previous[1] if previous else None, encoded, timestamp))
            self.db.execute('INSERT OR REPLACE INTO items VALUES (?,?,?,?)',
                            (torrent_hash, status, encoded, timestamp))

    def import_to_arr(self, torrent, destination):
        app = {'sonarr': 'sonarr', 'radarr': 'radarr'}.get(torrent['category'])
        if not app:
            return None
        cfg = self.config[app]
        path = '/data/aprovados/' + str(destination.relative_to(PUBLIC))
        headers = {'X-Api-Key': cfg['api_key']}
        current = self.arr.get(cfg['url'] + '/api/v3/command', headers=headers, timeout=(10, 60))
        current.raise_for_status()
        for command in current.json():
            body = command.get('body') or {}
            if (command.get('status') in ('queued', 'started')
                    and command.get('name') in ('DownloadedEpisodesScan', 'DownloadedMoviesScan')
                    and (body.get('path') == path or body.get('downloadClientId') == torrent['hash'])):
                return command['id']
        response = self.arr.post(cfg['url'] + '/api/v3/command',
            headers=headers, timeout=(10, 90),
            json={'name': 'DownloadedEpisodesScan' if app == 'sonarr' else 'DownloadedMoviesScan',
                  'path': path, 'downloadClientId': torrent['hash'], 'importMode': 'Copy'})
        response.raise_for_status()
        return response.json().get('id')

    def process(self, torrent):
        torrent_hash = torrent['hash']
        if not re.fullmatch('[0-9a-fA-F]{40,64}', torrent_hash):
            raise Rejected('Identificador de torrent inválido')
        with (STATE / (torrent_hash + '.lock')).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return self._process_locked(torrent)

    def _process_locked(self, torrent):
        torrent_hash = torrent['hash']
        if not re.fullmatch('[0-9a-fA-F]{40,64}', torrent_hash):
            raise Rejected('Identificador de torrent inválido')
        existing = self.db.execute('SELECT status,details FROM items WHERE hash=?', (torrent_hash,)).fetchone()
        if existing and existing[0] == 'substituido':
            if 'triagem-substituida' not in {tag.strip() for tag in torrent.get('tags', '').split(',')}:
                self.tag(torrent_hash, 'triagem-substituida')
            return
        if existing and existing[0] in ('aprovado', 'reprovado', 'revisao'):
            expected_tag = 'triagem-' + ('aprovada' if existing[0] == 'aprovado' else existing[0])
            if expected_tag not in {tag.strip() for tag in torrent.get('tags', '').split(',')}:
                self.tag(torrent_hash, expected_tag)
            return
        if existing and existing[0] == 'pendente-importacao':
            details = json.loads(existing[1])
            details['import_attempt_at'] = now()
            details['import_attempts'] = details.get('import_attempts', 0) + 1
            self.record(torrent_hash, 'pendente-importacao', details)
            command = self.import_to_arr(torrent, Path(details['destination']))
            details['import_command'] = command
            self.record(torrent_hash, 'aprovado', details)
            self.tag(torrent_hash, 'triagem-aprovada')
            return
        stage = PUBLIC / '.em-analise' / torrent_hash
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(mode=0o700)
        progress = {'name': torrent['name'], 'started_at': now()}
        def report(phase, filename=None):
            progress.update({'phase': phase, 'file': filename, 'phase_started_at': now()})
            self.record(torrent_hash, 'em-analise', progress)
        report('preparando')
        self.tag(torrent_hash, 'triagem-em-analise')
        try:
            save_path = Path(torrent['save_path'])
            if '..' in save_path.parts or not save_path.is_absolute() or not save_path.is_relative_to(RAW):
                raise Review('Download fora da pasta de recebidos')
            files = self.qget('torrents/files', hash=torrent_hash)
            accepted = selected_media(files)
            signatures = list(Path('/var/lib/clamav').glob('daily.c[lv]d'))
            if not signatures or max(path.stat().st_mtime for path in signatures) < time.time() - 7*86400:
                raise RuntimeError('Assinaturas do antivírus ausentes ou antigas')
            hashes = {}
            normalized_subtitles = []
            for item, parts, _ in accepted:
                dest = stage.joinpath(*parts)
                report('copiando', item['name'])
                hashes[item['name']] = copy_source(save_path.joinpath(*parts), dest)
                report('aguardando-antivirus', item['name'])
                scan(dest, on_start=lambda: report('antivirus', item['name']))
                report('validando-midia', item['name'])
                normalized_digest = validate_media(dest, normalize_subtitles=True)
                if normalized_digest:
                    hashes[item['name']] = normalized_digest
                    normalized_subtitles.append(item['name'])
            title = re.sub(r'[^\w .()-]', '_', torrent['name'])[:100].strip(' .') or 'download'
            destination = PUBLIC / CATEGORIES[torrent['category']] / (title + '__' + torrent_hash[:8])
            if destination.exists():
                raise Review('Já existe uma cópia aprovada com esse identificador')
            manifest = {'torrent': torrent['name'], 'hash': torrent_hash, 'verified_at': now(),
                        'sha256': hashes, 'normalized_subtitles': normalized_subtitles, 'scanner': 'ClamAV',
                        'note': 'Nenhuma ameaça detectada; este resultado não garante ausência de malware.'}
            (stage / 'TRIAGEM.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
            for parent, directories, names in os.walk(stage):
                os.chown(parent, -1, 1100)
                os.chmod(parent, 0o2750)
                for name in names:
                    path = Path(parent) / name
                    os.chown(path, -1, 1100)
                    os.chmod(path, 0o440)
            os.rename(stage, destination)
            details = {'name': torrent['name'], 'destination': str(destination), 'files': hashes, 'normalized_subtitles': normalized_subtitles}
            self.record(torrent_hash, 'pendente-importacao', details)
            details['import_command'] = self.import_to_arr(torrent, destination)
            self.record(torrent_hash, 'aprovado', details)
            self.tag(torrent_hash, 'triagem-aprovada')
            print(json.dumps({'hash': torrent_hash, 'status': 'aprovado'}, ensure_ascii=False), flush=True)
        except (Rejected, Review) as error:
            status = 'revisao' if isinstance(error, Review) else 'reprovado'
            self.record(torrent_hash, status, {'name': torrent['name'], 'reason': str(error)})
            self.qbit.post(self.config['qbit']['url'] + '/api/v2/torrents/stop',
                           data={'hashes': torrent_hash}, timeout=10).raise_for_status()
            self.tag(torrent_hash, 'triagem-' + status)
            print(json.dumps({'hash': torrent_hash, 'status': status, 'reason': str(error)}, ensure_ascii=False), flush=True)
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    def run(self, only_hash=None):
        states = dict(self.db.execute('SELECT hash,status FROM items'))
        priority = {'pendente-importacao': 0, 'reanalise-agendada': 1, 'erro': 2, 'em-analise': 2}
        torrents = self.qget('torrents/info', filter='completed')
        torrents.sort(key=lambda t: priority.get(states.get(t['hash']), 3))
        for torrent in torrents:
            if only_hash is not None and torrent['hash'] != only_hash:
                continue
            if torrent['category'] not in CATEGORIES or torrent['progress'] < 1:
                continue
            if torrent['state'] in ('checkingUP', 'moving', 'checkingResumeData', 'missingFiles', 'error'):
                continue
            try:
                self.process(torrent)
            except Exception as error:
                previous = self.db.execute('SELECT status,details FROM items WHERE hash=?', (torrent['hash'],)).fetchone()
                if previous and previous[0] == 'pendente-importacao':
                    details = json.loads(previous[1])
                    details['import_error'] = str(error)[:1000]
                    details['import_error_at'] = now()
                    self.record(torrent['hash'], 'pendente-importacao', details)
                elif not previous or previous[0] not in ('reprovado', 'revisao', 'substituido'):
                    self.record(torrent['hash'], 'erro', {'name': torrent['name'], 'reason': str(error)[:1000]})
                retained = previous[0] if previous else None
                tag = 'triagem-' + retained if retained in ('reprovado', 'revisao') else 'triagem-pendente'
                self.tag(torrent['hash'], tag)
                print(json.dumps({'hash': torrent['hash'], 'status': 'erro', 'reason': str(error)}, ensure_ascii=False), flush=True)
        report = [{'hash': row[0], 'status': row[1], 'details': json.loads(row[2]), 'updated': row[3]}
                  for row in self.db.execute('SELECT * FROM items ORDER BY updated DESC')]
        output = PUBLIC / 'STATUS/triagem.json'
        temporary = output.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        temporary.chmod(0o440)
        os.chown(temporary, -1, 1100)
        temporary.replace(output)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--retry', help='Reexaminar um hash específico após revisão administrativa')
    parser.add_argument('--only', help='Processar somente um torrent concluído, preservando a política de análise')
    arguments = parser.parse_args()
    if arguments.only and not re.fullmatch('[0-9a-fA-F]{40,64}', arguments.only):
        raise SystemExit('Hash inválido')
    pipeline = Pipeline()
    if arguments.retry:
        if not re.fullmatch('[0-9a-fA-F]{40,64}', arguments.retry):
            raise SystemExit('Hash inválido')
        if arguments.only and arguments.only != arguments.retry:
            raise SystemExit('--only e --retry devem indicar o mesmo torrent')
        with (STATE / (arguments.retry + '.lock')).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            row = pipeline.db.execute('SELECT status,details FROM items WHERE hash=?', (arguments.retry,)).fetchone()
            if row:
                details = json.loads(row[1])
                if row[0] in ('aprovado', 'substituido'):
                    raise SystemExit('Aprovação ou substituição existente: usar recuperação administrativa, sem apagar evidência')
                details['retry_requested_at'] = now()
                pipeline.record(arguments.retry, 'pendente-importacao' if row[0] == 'pendente-importacao' else 'reanalise-agendada', details)
    pipeline.run(only_hash=arguments.only or arguments.retry)
