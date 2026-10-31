#!/usr/bin/env python3
"""Prepara somente arquivos no lab; lê a API existente para reutilizar o acesso."""

import json, os, pwd, grp, subprocess
from pathlib import Path
import requests

root = Path(__file__).resolve().parents[1]
assert root == Path("/mnt/dados/lab")
if os.geteuid() == 0:
    raise SystemExit(
        "Executar sem sudo, com o usuário proprietário de lab; o container deve usar UID sem privilégios."
    )
os.umask(0o077)
for name, mode in [
    ("biblioteca", 0o750),
    ("biblioteca/filmes", 0o750),
    ("biblioteca/series", 0o750),
    (".em-recebimento", 0o700),
    ("state", 0o700),
    ("runtime", 0o700),
    ("runtime/cache", 0o700),
]:
    p = root / "jellyfin" / name
    if p.is_symlink():
        raise SystemExit("Diretório de trabalho não pode ser link simbólico")
    if not p.exists():
        p.mkdir(parents=True)
        p.chmod(mode)
key = root / "secrets/jellyfin_pull_ed25519"
if not key.exists():
    subprocess.run(
        [
            "ssh-keygen",
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-f",
            str(key),
            "-C",
            "jellyfin-coleta-readonly",
        ],
        check=True,
    )
secret = root / "secrets/jellyfin-host.json"
s = requests.Session()
s.trust_env = False
if not secret.exists():
    c = json.loads((root / "secrets/media-stack.json").read_text())
    r = s.get(
        "http://192.168.250.10:5055/api/v1/settings/jellyfin",
        headers={"X-Api-Key": c["seerr_key"]},
        timeout=15,
    )
    r.raise_for_status()
    v = r.json()
    assert v.get("apiKey")
    secret.write_text(json.dumps({"api_key": v["apiKey"]}, indent=2) + "\n")
unit = (
    (root / "jellyfin/config/lab-jellyfin-sync.service.in")
    .read_text()
    .replace("@LAB_USER@", pwd.getpwuid(os.getuid()).pw_name)
    .replace("@LAB_GROUP@", grp.getgrgid(os.getgid()).gr_name)
)
(root / "jellyfin/config/lab-jellyfin-sync.service").write_text(unit)
lock = root / "jellyfin/images.lock.json"
if not lock.exists():
    response = s.get(
        "https://auth.docker.io/token",
        params={
            "service": "registry.docker.io",
            "scope": "repository:jellyfin/jellyfin:pull",
        },
        timeout=30,
    )
    response.raise_for_status()
    token = response.json()["token"]
    response = s.head(
        "https://registry-1.docker.io/v2/jellyfin/jellyfin/manifests/12.4",
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json",
        },
        timeout=30,
    )
    response.raise_for_status()
    digest = response.headers["Docker-Content-Digest"]
    assert digest.startswith("sha256:") and len(digest) == 71
    lock.write_text(
        json.dumps(
            {"version": "12.4", "image": "jellyfin/jellyfin@" + digest}, indent=2
        )
        + "\n"
    )
v = json.loads(lock.read_text())
(root / "jellyfin/.env").write_text(
    f"LAB_JELLYFIN_IMAGE={v['image']}\nLAB_JELLYFIN_UID={os.getuid()}\nLAB_JELLYFIN_GID={os.getgid()}\n"
)
print(
    "Chave SFTP restrita, acesso à API, diretórios e versão fixada preparados dentro de lab."
)
