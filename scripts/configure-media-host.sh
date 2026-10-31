#!/bin/bash
# Complemento autorizado: memória da VM e exceção exclusiva para Jellyfin.
set -euo pipefail
test "$EUID" = 0
root=/mnt/dados/lab
virt-xml-validate "$root/config/downloads-vm.xml" domain
nft -c -f "$root/config/downloads-guard.nft"
install -m 600 "$root/config/downloads-guard.nft" /etc/nftables/lab-downloads.nft
systemctl restart lab-downloads-firewall.service
systemctl restart lab-downloads-docker.service
virsh -c qemu:///system setmaxmem lab-downloads 6291456 --config
virsh -c qemu:///system setmem lab-downloads 6291456 --config
echo 'Firewall aplicado; memória de 6 GiB configurada para a próxima partida da VM.'
