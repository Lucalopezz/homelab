#!/bin/bash
# Aplicar a memória persistente já autorizada, com desligamento gracioso.
set -euo pipefail
test "$EUID" = 0
export LC_ALL=C
virsh -c qemu:///system shutdown lab-downloads
for tentativa in $(seq 1 60); do
  if virsh -c qemu:///system domstate lab-downloads | grep -q 'shut off'; then
    bash /mnt/dados/lab/scripts/start-vm.sh
    exit 0
  fi
  sleep 2
done
echo 'A VM não terminou o desligamento; não foi forçada.' >&2
exit 1
