#!/bin/bash
# Iniciar só depois da autorização e da execução de configure-host.sh.
set -euo pipefail
test "$EUID" = 0 || { echo 'Execute com sudo, depois de autorizar a configuração do Fedora.' >&2; exit 1; }
findmnt --mountpoint /mnt/dados >/dev/null
systemctl restart lab-downloads-firewall.service
nft list table inet lab_download_guard >/dev/null
if systemctl is-active --quiet docker.service; then
  systemctl restart lab-downloads-docker.service
fi
if ! LC_ALL=C virsh -c qemu:///system net-info lab-downloads | grep -Eq '^Active: +yes$'; then
  LC_ALL=C virsh -c qemu:///system net-start lab-downloads
fi
LC_ALL=C virsh -c qemu:///system start lab-downloads
echo 'A primeira inicialização instala os pacotes no Debian; aguarde o cloud-init.'
