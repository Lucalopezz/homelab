#!/bin/bash
# Instala apenas as duas unidades do sincronizador; requer autorização externa.
set -euo pipefail
test "$EUID" = 0
root=/mnt/dados/lab
findmnt --mountpoint /mnt/dados >/dev/null
test -s "$root/secrets/jellyfin-host.json"
test -s "$root/secrets/jellyfin_pull_ed25519"
if [ -e /etc/systemd/system/lab-jellyfin-sync.service ] || [ -e /etc/systemd/system/lab-jellyfin-sync.timer ]; then
  test "${1:-}" = --update-reviewed-units || { echo 'Unidades já existem; revisar antes de atualizar.' >&2; exit 1; }
  systemctl stop lab-jellyfin-sync.timer lab-jellyfin-sync.service
fi
python3 - <<'CLEAN'
from pathlib import Path
import shutil
stage=Path('/mnt/dados/lab/jellyfin/.em-recebimento')
for child in stage.iterdir():
    if child.name.startswith('tmp') and child.is_dir() and not child.is_symlink():
        shutil.rmtree(child)
CLEAN
systemd-analyze verify "$root/jellyfin/config/lab-jellyfin-sync.service" "$root/jellyfin/config/lab-jellyfin-sync.timer"
install -m 644 "$root/jellyfin/config/lab-jellyfin-sync.service" /etc/systemd/system/lab-jellyfin-sync.service
install -m 644 "$root/jellyfin/config/lab-jellyfin-sync.timer" /etc/systemd/system/lab-jellyfin-sync.timer
lab_group=$(stat -c %G "$root/jellyfin")
chown -R root:"$lab_group" "$root/jellyfin/biblioteca" "$root/jellyfin/state" "$root/jellyfin/.em-recebimento"
find "$root/jellyfin/biblioteca" "$root/jellyfin/state" "$root/jellyfin/.em-recebimento" -type d -exec chmod 2770 {} +
find "$root/jellyfin/state" -type f -exec chmod 640 {} +
systemctl daemon-reload
systemctl enable --now lab-jellyfin-sync.timer
systemctl start lab-jellyfin-sync.service
systemctl status lab-jellyfin-sync.timer --no-pager
systemctl show lab-jellyfin-sync.service -p Result -p ExecMainStatus
