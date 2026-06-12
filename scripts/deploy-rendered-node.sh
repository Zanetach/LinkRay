#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 /path/to/rendered-node" >&2
  exit 2
fi

src="$1"
test -f "$src/opt/linkray-node-app/current/main.py"
test -f "$src/opt/linkray-node-app/current/requirements.txt"
test -f "$src/etc/systemd/system/linkray-node.service"
test -f "$src/etc/systemd/system/linkray-xray.service"
test -f "$src/etc/sysctl.d/99-linkray-network.conf"
test -f "$src/etc/modules-load.d/linkray-bbr.conf"

install -d \
  /opt/linkray-node-app \
  /var/lib/marzban/linkray/xray \
  /var/lib/marzban/linkray/singbox \
  /var/lib/marzban/linkray/snell \
  /etc/systemd/system \
  /etc/sysctl.d \
  /etc/modules-load.d

tmp_app="/opt/linkray-node-app/current.tmp"
rm -rf "$tmp_app"
install -d "$tmp_app"
cp -a "$src/opt/linkray-node-app/current/." "$tmp_app/"
rm -rf /opt/linkray-node-app/current
mv "$tmp_app" /opt/linkray-node-app/current

python3 -m venv /opt/linkray-node-app/venv
/opt/linkray-node-app/venv/bin/python -m pip install --upgrade pip
/opt/linkray-node-app/venv/bin/python -m pip install -r /opt/linkray-node-app/current/requirements.txt

install -m 0644 "$src/etc/systemd/system/linkray-node.service" /etc/systemd/system/linkray-node.service
install -m 0644 "$src/etc/systemd/system/linkray-xray.service" /etc/systemd/system/linkray-xray.service
install -m 0644 "$src/etc/sysctl.d/99-linkray-network.conf" /etc/sysctl.d/99-linkray-network.conf
install -m 0644 "$src/etc/modules-load.d/linkray-bbr.conf" /etc/modules-load.d/linkray-bbr.conf

if [[ -f "$src/etc/systemd/system/linkray-singbox-runtime.service" ]]; then
  test -f "$src/etc/systemd/system/linkray-snell-runtime.service"
  test -f "$src/etc/systemd/system/linkray-snell@.service"
  test -f "$src/etc/systemd/system/linkray-snell-usage.service"
  test -f "$src/var/lib/marzban/linkray/singbox/config.json"
  test -f "$src/var/lib/marzban/linkray/singbox/users.json"
  test -f "$src/var/lib/marzban/linkray/snell/snell-server.conf"

  install -m 0644 "$src/etc/systemd/system/linkray-singbox-runtime.service" /etc/systemd/system/linkray-singbox-runtime.service
  install -m 0644 "$src/etc/systemd/system/linkray-snell-runtime.service" /etc/systemd/system/linkray-snell-runtime.service
  install -m 0644 "$src/etc/systemd/system/linkray-snell@.service" /etc/systemd/system/linkray-snell@.service
  install -m 0644 "$src/etc/systemd/system/linkray-snell-usage.service" /etc/systemd/system/linkray-snell-usage.service
  install -m 0644 "$src/var/lib/marzban/linkray/singbox/config.json" /var/lib/marzban/linkray/singbox/config.json
  test -f /var/lib/marzban/linkray/singbox/users.json || install -m 0644 "$src/var/lib/marzban/linkray/singbox/users.json" /var/lib/marzban/linkray/singbox/users.json
  install -m 0600 "$src/var/lib/marzban/linkray/snell/snell-server.conf" /var/lib/marzban/linkray/snell/snell-server.conf
  if [[ -f "$src/var/lib/marzban/linkray/linkray-manifest.json" ]]; then
    install -m 0644 "$src/var/lib/marzban/linkray/linkray-manifest.json" /var/lib/marzban/linkray/linkray-manifest.json
  fi
fi

if command -v docker >/dev/null 2>&1; then
  docker update --restart=no linkray-node 2>/dev/null || true
  docker stop linkray-node 2>/dev/null || true
  docker rm -f marzban-node-marzban-node-1 2>/dev/null || true
fi

modprobe tcp_bbr || true
sysctl --system
default_if="$(ip route show default 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -1)"
if [[ -n "$default_if" ]]; then
  tc qdisc replace dev "$default_if" root fq 2>/dev/null || true
fi

systemctl daemon-reload
systemctl enable linkray-xray
systemctl enable --now linkray-node
systemctl restart linkray-node

if [[ -f /etc/systemd/system/linkray-singbox-runtime.service ]]; then
  systemctl enable --now linkray-singbox-runtime
  systemctl enable --now linkray-snell-runtime
  systemctl enable --now linkray-snell-usage
  systemctl restart linkray-singbox-runtime
  systemctl restart linkray-snell-runtime
  systemctl restart linkray-snell-usage
fi
