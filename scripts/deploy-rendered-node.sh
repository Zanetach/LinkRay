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

cd /opt/marzban-node
if ! docker image inspect linkray-node:latest >/dev/null 2>&1; then
  docker image inspect gozargah/marzban-node:latest >/dev/null 2>&1 || docker pull gozargah/marzban-node:latest
  docker tag gozargah/marzban-node:latest linkray-node:latest
  docker rmi gozargah/marzban-node:latest >/dev/null 2>&1 || true
fi
docker rm -f marzban-node-marzban-node-1 2>/dev/null || true
docker compose up -d --force-recreate --remove-orphans linkray-node
