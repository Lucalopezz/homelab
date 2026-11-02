#!/usr/bin/env python3
"""VM: recuperar aprovação interrompida e cópias incompletas, sem novo download.

Sem --apply apenas apresenta o plano. A execução requer acesso administrativo.
Nunca aprova bytes diferentes dos registrados na cópia examinada pelo ClamAV.
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import sqlite3
import stat
import tempfile
import time

PUBLIC = Path('/srv/downloads/aprovados')
LIBRARY = Path('/srv/downloads/biblioteca')
STATE = Path('/var/lib/media-triage')
COLLISION = 'Já existe uma cópia aprovada com esse identificador'


def parts(name):
    p = PurePosixPath(name)
    if (not name or p.is_absolute() or '..' in p.parts or '\\' in name
            or any(ord(c) < 32 for c in name) or len(p.parts) > 10):
        raise ValueError('Caminho recusado')
    return p.parts


def open_under(root, name):
    items = parts(name)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for item in items[:-1]:
            child = os.open(item, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        result = os.open(items[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    finally:
        os.close(fd)
    if not stat.S_ISREG(os.fstat(result).st_mode):
        os.close(result)
        raise ValueError('Arquivo não regular')
    return result


def stamp(s):
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


def verified_copy(root, name, expected, output=None):
    fd = open_under(root, name)
    try:
        before = os.fstat(fd)
        digest = hashlib.sha256()
        with os.fdopen(fd, 'rb', closefd=False) as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                if output is not None:
                    output.write(chunk)
        if stamp(before) != stamp(os.fstat(fd)) or digest.hexdigest() != expected:
            raise ValueError('Cópia aprovada mudou ou não confere com o SHA256 registrado')
    finally:
        os.close(fd)


def repair_copy(source_root, source_name, expected, relative):
    parts(relative)
    if parts(relative)[0] not in ('series', 'filmes'):
        raise ValueError('Destino fora da biblioteca de mídia')
    fd = open_under(LIBRARY, relative)
    try:
        before = os.fstat(fd)
    finally:
        os.close(fd)
    if time.time() - before.st_mtime < 120:
        raise ValueError('Destino foi modificado recentemente; aguardar importação')
    source_fd = open_under(source_root, source_name)
    try:
        source_size = os.fstat(source_fd).st_size
    finally:
        os.close(source_fd)
    if before.st_size >= source_size:
        raise ValueError('Recuperação automática restrita a cópia comprovadamente menor')
    target = LIBRARY / relative
    # Conferir também os pais antes de criar o temporário no mesmo filesystem.
    if target.parent.resolve() != target.parent.absolute():
        raise ValueError('Links no destino recusados')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.recuperando-', suffix='.part',
                                         dir=target.parent, delete=False) as out:
            temporary = Path(out.name)
            verified_copy(source_root, source_name, expected, out)
            out.flush()
            os.fsync(out.fileno())
            os.fchown(out.fileno(), before.st_uid, before.st_gid)
            os.fchmod(out.fileno(), stat.S_IMODE(before.st_mode))
        if stamp(target.lstat()) != stamp(before):
            raise ValueError('Destino mudou durante a recuperação; nada substituído')
        quarantine = LIBRARY / '.recuperacao'
        quarantine.mkdir(mode=0o700, exist_ok=True)
        if quarantine.is_symlink():
            raise ValueError('Diretório de recuperação inválido')
        saved = quarantine / (target.name + '.' + str(time.time_ns()) + '.incompleto')
        # Hardlink mantém a cópia parcial recuperável sem uma janela de ausência
        # no nome publicado. O arquivo completo entra com uma única troca atômica.
        os.link(target, saved, follow_symlinks=False)
        os.replace(temporary, target)
        temporary = None
        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return {'path': relative, 'old_size': before.st_size, 'new_size': source_size,
                'partial_preserved': str(saved)}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hash', required=True)
    parser.add_argument('--repair-path', action='append', default=[])
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch('[0-9a-fA-F]{40,64}', args.hash):
        raise ValueError('Hash inválido')
    lock_fd = os.open(STATE / (args.hash + '.lock'), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    if os.geteuid() == 0 and os.fstat(lock_fd).st_uid == 0:
        account = pwd.getpwnam('triagem')
        os.fchown(lock_fd, account.pw_uid, account.pw_gid)
    with os.fdopen(lock_fd, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        db = sqlite3.connect('file:' + str(STATE / 'state.sqlite3') + '?mode=ro', uri=True)
        original = db.execute('SELECT status,details,updated FROM items WHERE hash=?', (args.hash,)).fetchone()
        if not original:
            raise ValueError('Torrent sem registro de triagem')
        status, raw, updated = original
        details = json.loads(raw)
        collision = status == 'revisao' and details.get('reason') == COLLISION
        if status != 'aprovado' and not collision:
            raise ValueError('Estado não elegível; não contornar revisão ou reprovação')
        if collision:
            choices = [p for section in ('series', 'filmes', 'manuais')
                       for p in (PUBLIC / section).glob('*__' + args.hash[:8])]
            if len(choices) != 1:
                raise ValueError('Cópia aprovada ausente ou ambígua')
            destination = choices[0]
        else:
            destination = Path(details['destination'])
        relative = destination.relative_to(PUBLIC).as_posix()
        fd = open_under(PUBLIC, relative + '/TRIAGEM.json')
        with os.fdopen(fd) as handle:
            marker_stat = os.fstat(handle.fileno())
            marker = json.load(handle)
        if (marker_stat.st_uid != pwd.getpwnam('triagem').pw_uid
                or marker_stat.st_mode & 0o222
                or marker.get('hash') != args.hash or marker.get('scanner') != 'ClamAV'
                or not marker.get('verified_at') or not marker.get('sha256')):
            raise ValueError('Registro de aprovação não confiável')
        hashes = marker['sha256']
        for name, digest in hashes.items():
            parts(name)
            if not re.fullmatch('[0-9a-f]{64}', digest):
                raise ValueError('SHA256 inválido no registro')
        if not collision and details.get('files') != hashes:
            raise ValueError('Banco e registro da cópia aprovada divergem')
        print(json.dumps({'hash': args.hash, 'status': status, 'files': len(hashes),
                          'repair_paths': args.repair_path, 'apply': args.apply}), flush=True)
        if not args.apply:
            return
        if collision:
            for name, digest in hashes.items():
                verified_copy(PUBLIC, relative + '/' + name, digest)
                print(json.dumps({'verified': name}), flush=True)
            # Commit condicional: um registro alterado por outra execução não é sobrescrito.
            db.close()
            db = sqlite3.connect(STATE / 'state.sqlite3')
            restored = {'name': marker['torrent'], 'destination': str(destination),
                        'files': hashes, 'normalized_subtitles': marker.get('normalized_subtitles', []),
                        'recovered_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                        'recovered_from': {'status': status, 'reason': details.get('reason'),
                                           'updated': updated}}
            with db:
                row = db.execute('SELECT status,details,updated FROM items WHERE hash=?', (args.hash,)).fetchone()
                if row != original:
                    raise ValueError('Registro mudou durante a conferência')
                db.execute('UPDATE items SET status=?,details=?,updated=? WHERE hash=?',
                           ('aprovado', json.dumps(restored), restored['recovered_at'], args.hash))
            print(json.dumps({'approval_recovered': args.hash}), flush=True)
        for target in args.repair_path:
            candidates = [n for n in hashes if Path(n).name == Path(target).name]
            if len(candidates) != 1:
                raise ValueError('Correspondência de arquivo ausente ou ambígua')
            name = candidates[0]
            result = repair_copy(PUBLIC, relative + '/' + name, hashes[name], target)
            print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
