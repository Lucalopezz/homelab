#!/bin/bash
# Desligar a VM de forma graciosa; --all também para o Jellyfin.
set -euo pipefail
test "$EUID" = 0 || { echo 'Use: sudo bash scripts/stop-lab.sh [--all]' >&2; exit 1; }
test $# = 0 || test "${1:-}" = --all
export LC_ALL=C
if [ -f /etc/systemd/system/lab-jellyfin-sync.timer ]; then systemctl stop lab-jellyfin-sync.timer lab-jellyfin-sync.service; fi
state=$(virsh -c qemu:///system domstate lab-downloads)
if [ "$state" = running ]; then
  virsh -c qemu:///system shutdown lab-downloads
  for attempt in $(seq 1 45); do
    state=$(virsh -c qemu:///system domstate lab-downloads)
    if [ "$state" = 'shut off' ]; then break; fi
    sleep 2
  done
fi
if [ "$state" != 'shut off' ]; then echo 'Desligamento ainda não terminou; não foi forçado.' >&2; exit 1; fi
if [ "${1:-}" = --all ]; then docker stop --timeout 60 medias-jellyfin-1; fi
echo 'VM desligada. Os downloads foram preservados.'
