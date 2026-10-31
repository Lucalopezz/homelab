#!/usr/bin/env python3
"""Audita os arquivos publicáveis sem criar commits nem ler discos da VM."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = {'images', 'disks', 'secrets', 'state', 'backups', 'coleta',
           'appdata', 'runtime', 'biblioteca', '.em-recebimento', 'node_modules', '.venv', '__pycache__'}
GENERATED = {'cloud-init/user-data', 'cloud-init/meta-data', 'cloud-init/network-config',
             'jellyfin/config/lab-jellyfin-sync.service'}
SUFFIXES = {'.qcow2', '.iso', '.torrent', '.dump', '.sqlite3', '.db',
            '.log', '.pem', '.key', '.pyc'}
PATTERNS = [
    re.compile(rb'-----BEGIN (?:OPENSSH |RSA |EC |DSA |ENCRYPTED )?PRIVATE KEY-----'),
    re.compile(rb'\bgh[pousr]_[A-Za-z0-9]{30,}\b'),
    re.compile(rb'\bgithub_pat_[A-Za-z0-9_]{50,}\b'),
    re.compile(rb'\bAKIA[0-9A-Z]{16}\b'),
]

def git(*args, directory=None, check=True):
    return subprocess.run(['git', *(directory or []), *args], cwd=ROOT,
                          capture_output=True, check=check)

def names(raw):
    return {os.fsdecode(value) for value in raw.split(b'\0') if value}

def private_path(name):
    path = Path(name)
    return (bool(set(path.parts) & PRIVATE) or name in GENERATED
            or path.name == 'credentials.json' or path.name == '.env'
            or (path.name.startswith('.env.') and path.name != '.env.example')
            or path.suffix in SUFFIXES or '.qcow2.' in path.name
            or '.sqlite3-' in path.name)

def known_secrets():
    # Comparação sem exibir os valores; ajuda a reconhecer credenciais deste lab.
    values = set()
    password = ROOT / 'secrets/qbittorrent-password'
    if password.exists():
        values.add(password.read_text().strip().encode())
    for name in ('media-stack.json', 'jellyfin-host.json'):
        media = ROOT / 'secrets' / name
        if not media.exists():
            continue
        for key, value in json.loads(media.read_text()).items():
            if ('password' in key or key.endswith('_key')) and isinstance(value, str):
                values.add(value.encode())
    return [value for value in values if len(value) >= 16]

def main():
    os.umask(0o077)
    state = ROOT / 'state'
    state.mkdir(mode=0o700, exist_ok=True)
    # Índice separado: verifica o .gitignore sem inicializar um repo de trabalho.
    with tempfile.TemporaryDirectory(prefix='publication-', dir=state) as temporary:
        git('init', '--bare', '--quiet', '--initial-branch=main', temporary)
        isolated = ['--git-dir=' + temporary, '--work-tree=' + str(ROOT),
                    '-c', 'core.excludesFile=/dev/null']
        candidates = names(git('ls-files', '--others', '--exclude-standard', '-z',
                               directory=isolated).stdout)
    tracked = set()
    if (ROOT / '.git').exists():
        tracked = names(git('ls-files', '--cached', '-z').stdout)
    candidates |= tracked
    secrets = known_secrets()
    problems = []
    for name in sorted(candidates):
        if private_path(name):
            problems.append((name, 'arquivo privado ou gerado incluído'))
            continue
        path = ROOT / name
        if path.is_symlink():
            problems.append((name, 'link simbólico: revisar destino antes de publicar'))
            continue
        versions = []
        if path.is_file():
            if path.stat().st_size > 2 * 1024 * 1024:
                problems.append((name, 'arquivo acima de 2 MiB: revisar conteúdo'))
                continue
            versions.append(path.read_bytes())
        if name in tracked:
            staged = git('show', ':' + name, check=False)
            if staged.returncode == 0:
                versions.append(staged.stdout)
        for data in versions:
            if any(value in data for value in secrets):
                problems.append((name, 'contém uma credencial local conhecida'))
                break
            if any(pattern.search(data) for pattern in PATTERNS):
                problems.append((name, 'possível chave privada ou token'))
                break
    if problems:
        for name, reason in problems:
            print('BLOQUEADO:', name, '—', reason)
        raise SystemExit(1)
    (state / 'publication-files.txt').write_text('\n'.join(sorted(candidates)) + '\n')
    print(f'OK: {len(candidates)} arquivos candidatos, sem os dados privados verificados.')
    print('Lista: state/publication-files.txt')
    print('Revise também git diff --cached antes de enviar; histórico remoto não é auditado.')

if __name__ == '__main__':
    main()
