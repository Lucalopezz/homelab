#!/bin/bash
# Testa apenas os destinos previamente confirmados neste notebook.
# Leitura do firewall exige privilégios; não altera regras ou serviços.
set -euo pipefail
test "$EUID" = 0
root=/mnt/dados/lab
nft list table inet lab_download_guard
for url in http://192.168.250.1:8096 http://192.168.0.1; do
  # Um serviço acessível pelo host é necessário para validar o bloqueio.
  curl --fail --silent --show-error --connect-timeout 2 --max-time 3 --output /dev/null "$url"
done
python3 - <<'PY'
import socket
with socket.create_connection(('192.168.250.1', 22), timeout=3):
    print('SSH do Fedora disponível para comparação: OK')
PY
ssh -F "$root/config/ssh_config" -o BatchMode=yes lab-downloads-admin 'python3 -' <<'PY'
import socket
import urllib.request
assert urllib.request.urlopen('https://www.debian.org', timeout=8).status == 200
print('Internet IPv4: OK')
assert urllib.request.urlopen('http://192.168.250.1:8096/System/Info/Public', timeout=5).status == 200
print('Exceção autorizada para API do Jellyfin: OK')
for ip, port in [('192.168.250.1', 22), ('192.168.0.1', 80),
                 ('192.168.1.116', 8096), ('192.168.0.107', 8096)]:
    try:
        conn = socket.create_connection((ip, port), timeout=3)
    except (TimeoutError, OSError) as exc:
        print(f'Conexão VM -> {ip}:{port}: bloqueada ({type(exc).__name__})')
    else:
        conn.close()
        raise SystemExit(f'FALHA de isolamento: conexão permitida para {ip}:{port}')
PY
nft list table inet lab_download_guard
