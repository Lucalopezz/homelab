#!/usr/bin/env python3
"""Gera credenciais novas da stack sem imprimir seus valores."""

import json
import os
from pathlib import Path
import secrets


ROOT = Path(__file__).resolve().parents[1]
MEDIA_CREDENTIALS = ROOT / "secrets/media-stack.json"
TORRENT_PASSWORD = ROOT / "secrets/qbittorrent-password"


def main():
    os.umask(0o077)
    if MEDIA_CREDENTIALS.exists():
        raise SystemExit("Credenciais já existem; não serão substituídas.")

    config = {
        "username": "lab",
        "password": secrets.token_urlsafe(24),
        "sonarr_key": secrets.token_hex(16),
        "radarr_key": secrets.token_hex(16),
        "prowlarr_key": secrets.token_hex(16),
        "seerr_key": secrets.token_hex(32),
        "bazarr_key": secrets.token_hex(16),
        "qbit_password": TORRENT_PASSWORD.read_text().strip(),
    }
    MEDIA_CREDENTIALS.write_text(json.dumps(config, indent=2) + "\n")
    print("Credenciais geradas em secrets/media-stack.json, sem exibir valores.")


if __name__ == "__main__":
    main()
