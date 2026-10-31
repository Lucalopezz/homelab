#!/bin/bash
# Exceções IPv4 exclusivas desta VM na cadeia de usuário do Docker.
# O bloqueio de destinos internos é aplicado antes, por lab_download_guard (-10).
set -euo pipefail
/usr/sbin/nft list table inet lab_download_guard >/dev/null
if ! /usr/sbin/iptables -w 5 -S DOCKER-USER >/dev/null 2>&1; then
  echo 'DOCKER-USER ausente; nenhuma regra iptables adicionada. Validar a saída da VM.'
  exit 0
fi
outbound=(-i virbr-dl -s 192.168.250.0/24 -m comment --comment lab-downloads-out -j ACCEPT)
inbound=(-o virbr-dl -d 192.168.250.0/24 -m conntrack --ctstate ESTABLISHED,RELATED -m comment --comment lab-downloads-return -j ACCEPT)
/usr/sbin/iptables -w 5 -C DOCKER-USER "${outbound[@]}" 2>/dev/null || /usr/sbin/iptables -w 5 -I DOCKER-USER 1 "${outbound[@]}"
/usr/sbin/iptables -w 5 -C DOCKER-USER "${inbound[@]}" 2>/dev/null || /usr/sbin/iptables -w 5 -I DOCKER-USER 1 "${inbound[@]}"
