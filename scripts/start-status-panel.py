#!/usr/bin/env python3
"""Start the host-only status panel once, as the desktop user."""
import fcntl
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def panel_process(pid, panel):
    try:
        proc = Path('/proc') / str(pid)
        if proc.stat().st_uid != os.getuid():
            return False
        args = (proc / 'cmdline').read_bytes().split(b'\0')
        cwd = (proc / 'cwd').resolve()
        return any((cwd / os.fsdecode(arg)).resolve() == panel for arg in args[1:] if arg)
    except (OSError, ValueError):
        return False


def listening(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.3):
            return True
    except OSError:
        return False


def start_panel(root, port=8765):
    root = Path(root).resolve()
    panel = root / 'media-stack/painel-local.py'
    state = root / 'state'
    state.mkdir(mode=0o700, exist_ok=True)
    pidfile = state / 'painel-local.pid'
    with (state / 'painel-start.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # Find even a panel started manually before the PID file existed.
        for proc in Path('/proc').iterdir():
            if proc.name.isdigit() and panel_process(int(proc.name), panel):
                if listening(port):
                    return 'Painel já em execução: http://127.0.0.1:8765'
                raise RuntimeError('O painel já está em execução, mas ainda não responde na porta 8765.')
        if listening(port):
            raise RuntimeError('A porta 8765 já está ocupada por outro processo; não alterei esse processo.')
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW
        fd = os.open(state / 'painel-local.log', flags, 0o600)
        with os.fdopen(fd, 'ab') as log:
            child = subprocess.Popen([sys.executable, str(panel)], cwd=root,
                                     stdin=subprocess.DEVNULL, stdout=log,
                                     stderr=subprocess.STDOUT, start_new_session=True)
        for _ in range(50):
            if child.poll() is not None:
                raise RuntimeError('O painel terminou ao iniciar; consulte state/painel-local.log.')
            if listening(port):
                pidfile.write_text(str(child.pid) + '\n')
                return 'Painel iniciado: http://127.0.0.1:8765'
            time.sleep(0.1)
        raise RuntimeError('O painel não respondeu a tempo; consulte state/painel-local.log.')


def main():
    if os.geteuid() == 0:
        print('Inicie o painel como seu usuário normal, sem sudo.', file=sys.stderr)
        return 1
    os.umask(0o077)
    try:
        print(start_panel(ROOT))
        return 0
    except (OSError, RuntimeError) as exc:
        print(f'Não foi possível iniciar o painel: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
