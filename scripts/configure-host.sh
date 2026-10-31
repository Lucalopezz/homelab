#!/bin/bash
# FORA DO ESCOPO LOCAL: só executar após autorização explícita do usuário.
# Não inicia a VM. Ver README.md e config/ antes de aprovar.
set -euo pipefail
root=/mnt/dados/lab
test "$EUID" = 0 || { echo 'Requer sudo e autorização para alterar o Fedora.' >&2; exit 1; }
test "${1:-}" = --apply-reviewed-host-changes || {
  echo 'Leia o README. Requer a opção --apply-reviewed-host-changes.' >&2; exit 1;
}
test "$(readlink -f "$(dirname "$0")/..")" = "$root"
findmnt --mountpoint /mnt/dados >/dev/null
for binary in virsh nft semanage restorecon systemctl; do command -v "$binary" >/dev/null; done
getent group qemu >/dev/null
for file in system.qcow2 downloads.qcow2 seed.iso; do test -f "$root/disks/$file"; done

# Evitar sobrescrever VMs, redes e arquivos administrativos preexistentes.
if virsh -c qemu:///system dominfo lab-downloads >/dev/null 2>&1; then
  echo 'Já existe uma VM lab-downloads. Pare e confira o estado.' >&2; exit 1
fi
if virsh -c qemu:///system net-info lab-downloads >/dev/null 2>&1; then
  echo 'Já existe uma rede lab-downloads. Pare e confira o estado.' >&2; exit 1
fi
test ! -e /etc/nftables/lab-downloads.nft
test ! -e /etc/systemd/system/lab-downloads-firewall.service
if ip link show virbr-dl >/dev/null 2>&1; then
  echo 'Já existe uma interface virbr-dl.' >&2; exit 1
fi
# A rede deve continuar sem sobreposição com redes reais, VPNs e containers.
python3 - <<'PY'
import ipaddress, json, subprocess
lab = ipaddress.ip_network('192.168.250.0/24')
for family in ('-4',):
    routes = json.loads(subprocess.check_output(['ip', '-j', family, 'route', 'show', 'table', 'all']))
    for route in routes:
        dst = route.get('dst', 'default')
        if dst == 'default':
            continue
        network = ipaddress.ip_network(dst, strict=False)
        if network.overlaps(lab):
            raise SystemExit(f'Rede já utilizada: {dst}')
PY
nft -c -f "$root/config/downloads-guard.nft"
virt-xml-validate "$root/config/downloads-network.xml" network
virt-xml-validate "$root/config/downloads-vm.xml" domain

# Instalar somente as duas configurações administrativas exclusivas do lab.
install -d -m 755 /etc/nftables
install -m 600 "$root/config/downloads-guard.nft" /etc/nftables/lab-downloads.nft
install -m 644 "$root/config/lab-downloads-firewall.service" /etc/systemd/system/lab-downloads-firewall.service
systemctl daemon-reload
systemctl enable --now lab-downloads-firewall.service
nft list table inet lab_download_guard
bash "$root/scripts/configure-docker-compat.sh"

# /mnt/dados está unlabeled_t neste Fedora. Rotular apenas os diretórios
# necessários à travessia e os discos; nunca relabelar todo o HD.
semanage fcontext -a -t mnt_t '/mnt/dados'
semanage fcontext -a -t virt_image_t '/mnt/dados/lab'
semanage fcontext -a -t virt_image_t '/mnt/dados/lab/disks(/.*)?'
restorecon -v /mnt/dados /mnt/dados/lab
restorecon -RFv "$root/disks"
chgrp qemu "$root/disks" "$root/disks/system.qcow2" "$root/disks/downloads.qcow2" "$root/disks/seed.iso"
chmod 750 "$root/disks"
chmod 660 "$root/disks/system.qcow2" "$root/disks/downloads.qcow2"
chmod 640 "$root/disks/seed.iso"

virsh -c qemu:///system net-define --validate "$root/config/downloads-network.xml"
virsh -c qemu:///system net-autostart lab-downloads --disable
virsh -c qemu:///system define --validate "$root/config/downloads-vm.xml"
virsh -c qemu:///system autostart lab-downloads --disable
date -Is > "$root/state/host-configured"
echo 'Host configurado. A VM permanece desligada; use scripts/start-vm.sh após conferir.'
