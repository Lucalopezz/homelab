#!/bin/bash
# Complemento do firewall autorizado: não reinicia Docker nem containers.
set -euo pipefail
test "$EUID" = 0
root=/mnt/dados/lab
/usr/sbin/nft -c -f "$root/config/downloads-guard.nft"
install -m 700 "$root/config/downloads-docker-compat.sh" /etc/nftables/lab-downloads-docker.sh
install -m 644 "$root/config/lab-downloads-docker.service" /etc/systemd/system/lab-downloads-docker.service
systemctl daemon-reload
systemctl enable --now lab-downloads-docker.service
if command -v iptables >/dev/null && /usr/sbin/iptables -w 5 -S DOCKER-USER >/dev/null 2>&1; then
  /usr/sbin/iptables -w 5 -S DOCKER-USER
else
  echo 'DOCKER-USER ausente; nenhuma regra iptables adicionada. Validar a saída da VM.'
fi
