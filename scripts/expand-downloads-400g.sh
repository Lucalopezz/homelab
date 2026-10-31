#!/bin/bash
# Crescimento online e preservação do volume existente. Nunca usar qemu-img resize com a VM ligada.
set -euo pipefail
test "$EUID" = 0
export LC_ALL=C
root=/mnt/dados/lab
findmnt --mountpoint /mnt/dados >/dev/null
python3 - <<'PY'
import subprocess,xml.etree.ElementTree as ET
x=ET.fromstring(subprocess.check_output(['virsh','-c','qemu:///system','dumpxml','lab-downloads']))
d=next(d for d in x.findall('devices/disk') if d.findtext('serial')=='lab-downloads')
assert d.find('source').get('file')=='/mnt/dados/lab/disks/downloads.qcow2'
assert d.find('target').get('dev')=='vdb'
capacity=int(subprocess.check_output(['virsh','-c','qemu:///system','domblkinfo','lab-downloads','vdb'],text=True).splitlines()[0].split()[-1])
assert 214748364800<=capacity<=429496729600,'Recusar redução ou disco com tamanho inesperado'
PY
virsh -c qemu:///system blockresize lab-downloads vdb 429496729600B
ssh -F "$root/config/ssh_config" -o ConnectTimeout=8 lab-downloads-admin 'sudo python3 -' <<'VM'
from pathlib import Path
import subprocess,time
p='/dev/disk/by-id/virtio-lab-downloads'
assert Path(p).is_block_device()
def out(*a):return subprocess.check_output(a,text=True).strip()
for _ in range(20):
 if out('blockdev','--getsize64',p)=='429496729600':break
 time.sleep(1)
assert out('blockdev','--getsize64',p)=='429496729600'
assert out('blkid','-s','TYPE','-o','value',p)=='ext4'
assert out('blkid','-s','LABEL','-o','value',p)=='lab-downloads'
assert out('findmnt','-n','-o','SOURCE','--target','/srv/downloads')=='/dev/vdb'
subprocess.run(['resize2fs',p],check=True)
print(out('df','-h','/srv/downloads'))
VM
virsh -c qemu:///system domblkinfo lab-downloads vdb
