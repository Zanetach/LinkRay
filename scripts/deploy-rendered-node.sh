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
docker compose up -d
