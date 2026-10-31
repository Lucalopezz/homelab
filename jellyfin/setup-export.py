#!/usr/bin/env python3
"""Prepara conta SFTP restrita e emissão de manifesto dentro da VM."""

import os, pwd, subprocess
from pathlib import Path

assert os.geteuid() == 0 and os.uname().nodename == "lab-downloads"
root = Path("/opt/jellyfin-export")


def run(*a):
    subprocess.run(a, check=True)


try:
    pwd.getpwnam("jellyfin-coleta")
except KeyError:
    run("useradd", "--create-home", "--shell", "/bin/sh", "jellyfin-coleta")
run("usermod", "-aG", "midia", "jellyfin-coleta")
p = Path("/srv/downloads/biblioteca/.publicacao")
p.mkdir(exist_ok=True)
os.chown(p, 1101, 1100)
p.chmod(0o2750)
p = Path("/var/lib/jellyfin-export")
p.mkdir(exist_ok=True)
os.chown(p, 1101, 1101)
p.chmod(0o700)
u = pwd.getpwnam("jellyfin-coleta")
ssh = Path(u.pw_dir) / ".ssh"
ssh.mkdir(mode=0o700, exist_ok=True)
os.chown(ssh, u.pw_uid, u.pw_gid)
key = (root / "pull-key.pub").read_text().strip()
assert key.startswith("ssh-ed25519 ")
auth = ssh / "authorized_keys"
auth.write_text("restrict " + key + "\n")
os.chown(auth, u.pw_uid, u.pw_gid)
auth.chmod(0o600)
Path(
    "/etc/ssh/sshd_config.d/10-jellyfin-coleta.conf"
).write_text("""Match User jellyfin-coleta
    ChrootDirectory /srv/downloads/biblioteca
    ForceCommand internal-sftp -R -d /
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    AuthenticationMethods publickey
    DisableForwarding yes
    PermitTTY no
Match all
""")
run("/usr/sbin/sshd", "-t")
run("systemctl", "reload", "ssh")
for name in ("jellyfin-export.service", "jellyfin-export.timer"):
    run(
        "install",
        "-m",
        "644",
        str(root / "config" / name),
        "/etc/systemd/system/" + name,
    )
run("systemctl", "daemon-reload")
run("systemctl", "enable", "--now", "jellyfin-export.timer")
run("systemctl", "start", "jellyfin-export.service")
print("Exportação SFTP somente leitura preparada.")
