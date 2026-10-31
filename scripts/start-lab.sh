#!/bin/bash
# Partida diária idempotente. Não cria discos nem recria containers.
set -euo pipefail
test "$EUID" = 0 || { echo 'Use: sudo bash scripts/start-lab.sh' >&2; exit 1; }
root=/mnt/dados/lab
findmnt --mountpoint /mnt/dados >/dev/null
export LC_ALL=C
state=$(virsh -c qemu:///system domstate lab-downloads)
case "$state" in
  running)
    systemctl restart lab-downloads-firewall.service
    nft list table inet lab_download_guard >/dev/null
    if systemctl is-active --quiet docker.service; then systemctl restart lab-downloads-docker.service; fi
    ;;
  'shut off')
    if [ -f /etc/systemd/system/lab-jellyfin-sync.timer ]; then systemctl stop lab-jellyfin-sync.timer lab-jellyfin-sync.service; fi
    bash "$root/scripts/start-vm.sh"
    echo 'Aguardando a interface do Seerr antes de iniciar a cópia; no HD isso pode levar alguns minutos.'
    python3 - <<'READY'
import time,urllib.request
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
for attempt in range(150):
    try:
        with opener.open('http://192.168.250.10:5055/api/v1/status',timeout=2) as response:
            if response.status==200:break
    except OSError:pass
    if attempt and attempt%15==0:print('Serviços da VM ainda carregando...',flush=True)
    time.sleep(2)
else:print('VM iniciada; serviços ainda carregando. O sincronizador tentará novamente pelo timer.')
READY
    ;;
  *) echo "VM no estado '$state'; inspecionar sem forçar reinício." >&2; exit 1 ;;
esac
if systemctl is-active --quiet docker.service && docker inspect medias-jellyfin-1 >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' medias-jellyfin-1)" != true ]; then docker start medias-jellyfin-1; fi
fi
if [ -f /etc/systemd/system/lab-jellyfin-sync.timer ]; then systemctl start lab-jellyfin-sync.timer; fi
echo 'Laboratório iniciado; aguarde os serviços da VM carregarem.'
echo 'Seerr: http://192.168.250.10:5055'
echo 'qBittorrent: http://192.168.250.10:8080'
echo 'Jellyfin: http://127.0.0.1:8096'
