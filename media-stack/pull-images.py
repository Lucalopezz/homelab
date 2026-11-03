#!/usr/bin/env python3
"""Baixa as imagens fixadas no manifesto e prepara o arquivo de ambiente."""

import concurrent.futures
import json
import os
from pathlib import Path
import re
import subprocess


ROOT = Path("/opt/media-stack")
REPOSITORIES = {
    "SONARR": "lscr.io/linuxserver/sonarr",
    "RADARR": "lscr.io/linuxserver/radarr",
    "PROWLARR": "lscr.io/linuxserver/prowlarr",
    "BAZARR": "lscr.io/linuxserver/bazarr",
    "SEERR": "ghcr.io/seerr-team/seerr",
}


def validate_manifest(images):
    if set(images) != set(REPOSITORIES):
        raise SystemExit("Manifesto de imagens incompleto ou com serviços inesperados.")

    for name, reference in images.items():
        expected_repository = REPOSITORIES[name]
        pattern = re.escape(expected_repository) + r"@sha256:[0-9a-f]{64}"
        if not re.fullmatch(pattern, reference):
            raise SystemExit("Referência inválida no manifesto: " + name)


def pull_image(item):
    name, image = item
    subprocess.run(["docker", "pull", image], check=True)
    image_info = json.loads(
        subprocess.check_output(["docker", "image", "inspect", image])
    )[0]
    if (image_info["Os"], image_info["Architecture"]) != ("linux", "amd64"):
        raise RuntimeError("Arquitetura inesperada: " + name)

    print(name, "imagem obtida e fixada por digest", flush=True)
    return name + "_IMAGE", image


def main():
    if os.geteuid() != 0 or os.uname().nodename != "lab-downloads":
        raise SystemExit("Executar somente na VM, com sudo.")

    os.umask(0o077)
    if (ROOT / ".env").exists():
        raise SystemExit(
            ".env já existe: preservar a instalação e revisar antes de "
            "atualizar imagens."
        )

    images = json.loads((ROOT / "images.lock.json").read_text())
    validate_manifest(images)

    credentials = json.loads((ROOT / "credentials.json").read_text())
    seerr_key = credentials["seerr_key"]
    if not re.fullmatch(r"[0-9a-f]{64}", seerr_key):
        raise SystemExit("Chave Seerr inválida; não gerar .env.")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        locked_images = dict(executor.map(pull_image, images.items()))

    locked_images["SEERR_API_KEY"] = seerr_key
    with (ROOT / ".env").open("x") as target:
        target.write(
            "".join(f"{key}={value}\n" for key, value in locked_images.items())
        )

    subprocess.run(["docker", "compose", "config", "--quiet"], cwd=ROOT, check=True)
    subprocess.run(
        ["systemctl", "enable", "--now", "lab-media.service"],
        check=True,
    )


if __name__ == "__main__":
    main()
