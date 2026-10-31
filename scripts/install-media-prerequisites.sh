#!/bin/bash
# Executar SOMENTE dentro da VM Debian lab-downloads.
set -euo pipefail
test "$EUID" = 0
test "$(hostname)" = lab-downloads
test -f /var/lib/lab-downloads-ready
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl gnupg clamav clamav-daemon clamav-freshclam clamdscan file ffmpeg python3-requests python3-magic python3-yaml
install -d -m 755 /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod 644 /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<'EOF'
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: trixie
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker version --format '{{.Server.Version}}'
clamscan --version
