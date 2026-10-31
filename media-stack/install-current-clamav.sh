#!/bin/bash
# Binários oficiais LTS isolados em /opt; preserva integração Debian de usuários/configurações.
set -euo pipefail
test "$EUID" = 0
test "$(hostname)" = lab-downloads
base=/opt/clamav-release
release=clamav-1.4.6
install -d -m 755 "$base"
if [ ! -f "$base/$release.deb" ]; then
  curl --fail --silent --show-error --location --retry 2 \
    "https://github.com/Cisco-Talos/clamav/releases/download/$release/$release.linux.x86_64.deb" -o "$base/$release.deb"
fi
printf '%s  %s\n' d3ee9e401974855a1edc1761b1425417d126de618d5f0c91cd51209f69f6fcc2 "$base/$release.deb" | sha256sum -c -
curl --fail --silent --show-error --location \
  "https://github.com/Cisco-Talos/clamav/releases/download/$release/$release.linux.x86_64.deb.sig" -o "$base/$release.deb.sig"
curl --fail --silent --show-error --location \
  https://raw.githubusercontent.com/Cisco-Talos/clamav-documentation/main/src/manual/cisco-talos.gpg -o "$base/cisco-talos.gpg"
install -d -m 700 "$base/gnupg"
gpg --homedir "$base/gnupg" --batch --import "$base/cisco-talos.gpg"
gpg --homedir "$base/gnupg" --batch --verify "$base/$release.deb.sig" "$base/$release.deb"
install -d -m 755 "$base/$release"
dpkg-deb --extract "$base/$release.deb" "$base/$release"
ln -sfn "$base/$release" "$base/current"
prefix="$base/current/usr/local"
test -x "$prefix/sbin/clamd"
test -x "$prefix/bin/clamdscan"
export LD_LIBRARY_PATH="$prefix/lib64:$prefix/lib"
"$prefix/bin/clamscan" --version
for binary in clamscan clamdscan freshclam; do
  cat > "/usr/local/bin/$binary" <<EOF
#!/bin/sh
export LD_LIBRARY_PATH=$prefix/lib64:$prefix/lib
exec $prefix/bin/$binary "\$@"
EOF
  chmod 755 "/usr/local/bin/$binary"
done
# O cliente universal procura configuração em /usr/local/etc por padrão.
cat > /usr/local/bin/clamdscan <<EOF
#!/bin/sh
export LD_LIBRARY_PATH=$prefix/lib64:$prefix/lib
exec $prefix/bin/clamdscan --config-file=/etc/clamav/clamd.conf "\$@"
EOF
chmod 755 /usr/local/bin/clamdscan
install -d /etc/systemd/system/clamav-freshclam.service.d
cat > /etc/systemd/system/clamav-daemon.service.d/current-engine.conf <<EOF
[Unit]
Requires=

[Service]
Environment=LD_LIBRARY_PATH=$prefix/lib64:$prefix/lib
ExecStart=
ExecStart=$prefix/sbin/clamd --foreground=true --config-file=/etc/clamav/clamd.conf
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
IPAddressDeny=any

[Install]
Also=
EOF
cat > /etc/systemd/system/clamav-freshclam.service.d/current-engine.conf <<EOF
[Service]
Environment=LD_LIBRARY_PATH=$prefix/lib64:$prefix/lib
ExecStart=
ExecStart=$prefix/bin/freshclam --config-file=/etc/clamav/freshclam.conf -d --foreground=true
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
EOF
systemctl daemon-reload
systemctl restart clamav-freshclam.service
systemctl disable --now clamav-daemon.socket
systemctl mask clamav-daemon.socket
install -m 644 /opt/media-stack/config/clamav-daemon.service /etc/systemd/system/clamav-daemon.service
cat > /etc/systemd/system/clamav-daemon.service.d/zzz-runtime.conf <<'EOF'
[Service]
ExecStartPre=
EOF
systemctl daemon-reload
systemctl restart clamav-daemon.service
