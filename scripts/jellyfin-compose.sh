#!/bin/bash
# Sempre carregar o override do lab ao administrar o Jellyfin existente.
set -euo pipefail
exec docker compose -p medias --project-directory /mnt/dados/Medias \
  --env-file /mnt/dados/lab/jellyfin/.env \
  -f /mnt/dados/Medias/compose.yml \
  -f /mnt/dados/lab/jellyfin/compose.override.yaml "$@"
