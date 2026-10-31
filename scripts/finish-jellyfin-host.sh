#!/bin/bash
# Retomada autorizada: inicia VM existente e corrige somente as duas unidades do sync.
set -euo pipefail
test "$EUID" = 0
root=/mnt/dados/lab
export LC_ALL=C
if [ "$(virsh -c qemu:///system domstate lab-downloads)" = 'shut off' ]; then
  bash "$root/scripts/start-vm.sh"
else
  systemctl restart lab-downloads-firewall.service
  systemctl restart lab-downloads-docker.service
fi
ready=false
for attempt in $(seq 1 30); do
  if ssh -F "$root/config/ssh_config" -o ConnectTimeout=3 -o BatchMode=yes -o LogLevel=ERROR lab-downloads-admin true; then ready=true; break; fi
  sleep 2
done
test "$ready" = true || { echo 'SSH da VM ainda indisponível; aguardar e conferir.' >&2; exit 1; }
bash "$root/scripts/install-jellyfin-sync-host.sh" --update-reviewed-units
