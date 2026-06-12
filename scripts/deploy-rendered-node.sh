#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 /path/to/rendered-node" >&2
  exit 2
fi

src="$1"
test -f "$src/opt/marzban-node/docker-compose.yml"

install -d /opt/marzban-node
install -m 0644 "$src/opt/marzban-node/docker-compose.yml" /opt/marzban-node/docker-compose.yml

if [[ -f "$src/etc/systemd/system/linkray-singbox-runtime.service" ]]; then
  test -f "$src/etc/systemd/system/linkray-snell-runtime.service"
  test -f "$src/etc/systemd/system/linkray-snell@.service"
  test -f "$src/etc/systemd/system/linkray-snell-usage.service"
  test -f "$src/var/lib/marzban/linkray/singbox/config.json"
  test -f "$src/var/lib/marzban/linkray/singbox/users.json"
  test -f "$src/var/lib/marzban/linkray/snell/snell-server.conf"

  install -d \
    /etc/systemd/system \
    /var/lib/marzban/linkray/singbox \
    /var/lib/marzban/linkray/snell
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

cd /opt/marzban-node
if ! docker image inspect linkray-node:latest >/dev/null 2>&1; then
  docker image inspect gozargah/marzban-node:latest >/dev/null 2>&1 || docker pull gozargah/marzban-node:latest
  docker tag gozargah/marzban-node:latest linkray-node:latest
  docker rmi gozargah/marzban-node:latest >/dev/null 2>&1 || true
fi
docker rm -f marzban-node-marzban-node-1 2>/dev/null || true
docker compose up -d --force-recreate --remove-orphans linkray-node

if [[ -f /etc/systemd/system/linkray-singbox-runtime.service ]]; then
  systemctl daemon-reload
  systemctl enable --now linkray-singbox-runtime
  systemctl enable --now linkray-snell-runtime
  systemctl enable --now linkray-snell-usage
  systemctl restart linkray-singbox-runtime
  systemctl restart linkray-snell-runtime
  systemctl restart linkray-snell-usage
fi
