#!/bin/bash
# Executado SOMENTE dentro do Debian, pelo cloud-init.
set -euo pipefail
exec > >(tee -a /var/log/lab-downloads-setup.log) 2>&1

disk=/dev/disk/by-id/virtio-lab-downloads
test -b "$disk"
test "$(blockdev --getsize64 "$disk")" = 214748364800

# Só inicializar o disco identificado pelo serial, vazio e do tamanho esperado.
if ! blkid "$disk" >/dev/null 2>&1; then
  test -z "$(wipefs --noheadings --output TYPE "$disk")"
  mkfs.ext4 -E nodiscard -L lab-downloads "$disk"
fi
test "$(blkid -s LABEL -o value "$disk")" = lab-downloads
test "$(blkid -s TYPE -o value "$disk")" = ext4
uuid=$(blkid -s UUID -o value "$disk")
mkdir -p /srv/downloads
if ! grep -q ' /srv/downloads ' /etc/fstab; then
  printf 'UUID=%s /srv/downloads ext4 defaults 0 2\n' "$uuid" >> /etc/fstab
fi
systemctl daemon-reload
mountpoint -q /srv/downloads || mount /srv/downloads
chown root:root /srv/downloads
chmod 755 /srv/downloads
install -d -o torrent -g torrent -m 750 /srv/downloads/incompletos /srv/downloads/concluidos
install -d -o torrent -g torrent -m 700 /home/torrent/.config /home/torrent/.config/qBittorrent
chown torrent:torrent /home/torrent/.config/qBittorrent/qBittorrent.conf
chmod 600 /home/torrent/.config/qBittorrent/qBittorrent.conf

sshd -t
systemctl reload ssh
systemctl enable --now qbittorrent-nox@torrent.service
touch /var/lib/lab-downloads-ready
echo 'Configuração de downloads concluída.'
