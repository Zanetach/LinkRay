#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 /path/to/rendered-master" >&2
  exit 2
fi

src="$1"
test -f "$src/var/lib/marzban/xray_config.json"
test -f "$src/opt/marzban/docker-compose.yml"
test -f "$src/etc/nginx/conf.d/marzban-panel.conf"
test -f "$src/etc/systemd/system/linkray-api.service"
test -f "$src/etc/systemd/system/linkray-egern.service"
test -f "$src/etc/systemd/system/linkray-sub-auto.service"
test -f "$src/etc/systemd/system/linkray-relay.service"
test -f "$src/etc/systemd/system/linkray-rules-update.service"
test -f "$src/etc/systemd/system/linkray-rules-update.timer"
test -f "$src/var/lib/marzban/linkray/hosts.sql"
test -f "$src/var/lib/marzban/linkray/rules/cn-domains.txt"
test -f "$src/var/lib/marzban/linkray/rules/cn-ip-cidrs.txt"
test -f "$src/var/lib/marzban/linkray/patches/clash.py"
test -f "$src/var/lib/marzban/templates/subscription/index.html"
test -f "$src/var/lib/marzban/dashboard-patches/index.linkray.js"

install -d \
  /var/lib/marzban \
  /var/lib/marzban/templates/clash \
  /var/lib/marzban/templates/subscription \
  /var/lib/marzban/dashboard-patches \
  /var/lib/marzban/linkray/patches \
  /var/lib/marzban/linkray/rules \
  /opt/marzban \
  /etc/nginx/conf.d \
  /etc/systemd/system
install -m 0644 "$src/var/lib/marzban/xray_config.json" /var/lib/marzban/xray_config.json
install -m 0644 "$src/var/lib/marzban/templates/clash/default.yml" /var/lib/marzban/templates/clash/default.yml
install -m 0644 "$src/var/lib/marzban/templates/subscription/index.html" /var/lib/marzban/templates/subscription/index.html
install -m 0644 "$src/var/lib/marzban/linkray/hosts.sql" /var/lib/marzban/linkray/hosts.sql
install -m 0644 "$src/var/lib/marzban/linkray/rules/cn-domains.txt" /var/lib/marzban/linkray/rules/cn-domains.txt
install -m 0644 "$src/var/lib/marzban/linkray/rules/cn-ip-cidrs.txt" /var/lib/marzban/linkray/rules/cn-ip-cidrs.txt
install -m 0644 "$src/var/lib/marzban/linkray/patches/clash.py" /var/lib/marzban/linkray/patches/clash.py
install -m 0644 "$src/var/lib/marzban/dashboard-patches/index.html" /var/lib/marzban/dashboard-patches/index.html
install -m 0644 "$src/var/lib/marzban/dashboard-patches/index.linkray.js" /var/lib/marzban/dashboard-patches/index.linkray.js
install -m 0644 "$src/var/lib/marzban/dashboard-patches/index.original.js" /var/lib/marzban/dashboard-patches/index.original.js
install -m 0644 "$src/opt/marzban/docker-compose.yml" /opt/marzban/docker-compose.yml
install -m 0644 "$src/etc/nginx/conf.d/marzban-panel.conf" /etc/nginx/conf.d/marzban-panel.conf
install -m 0644 "$src/etc/systemd/system/linkray-api.service" /etc/systemd/system/linkray-api.service
install -m 0644 "$src/etc/systemd/system/linkray-egern.service" /etc/systemd/system/linkray-egern.service
install -m 0644 "$src/etc/systemd/system/linkray-sub-auto.service" /etc/systemd/system/linkray-sub-auto.service
install -m 0644 "$src/etc/systemd/system/linkray-relay.service" /etc/systemd/system/linkray-relay.service
install -m 0644 "$src/etc/systemd/system/linkray-rules-update.service" /etc/systemd/system/linkray-rules-update.service
install -m 0644 "$src/etc/systemd/system/linkray-rules-update.timer" /etc/systemd/system/linkray-rules-update.timer

cd /opt/marzban
docker compose up -d
sqlite3 /var/lib/marzban/db.sqlite3 < /var/lib/marzban/linkray/hosts.sql
systemctl daemon-reload
systemctl enable --now linkray-api
systemctl enable --now linkray-egern
systemctl enable --now linkray-sub-auto
systemctl enable --now linkray-rules-update.timer
systemctl start linkray-rules-update.service || true
systemctl enable --now linkray-relay
systemctl restart linkray-api
systemctl restart linkray-egern
systemctl restart linkray-sub-auto
systemctl restart linkray-relay
nginx -t
systemctl reload nginx
