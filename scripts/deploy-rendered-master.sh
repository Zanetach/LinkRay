#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 /path/to/rendered-master" >&2
  exit 2
fi

src="$1"
linkray_xray_unit="$src/etc/systemd/system/linkray-xray.service"
linkray_xray_enabled=0

test -f "$src/var/lib/marzban/xray_config.json"
test -f "$src/opt/marzban/docker-compose.yml"
test -f "$src/etc/nginx/conf.d/marzban-panel.conf"
test -f "$src/etc/systemd/system/linkray-api.service"
test -f "$src/etc/systemd/system/linkray-clash.service"
test -f "$src/etc/systemd/system/linkray-egern.service"
test -f "$src/etc/systemd/system/linkray-shadowrocket.service"
test -f "$src/etc/systemd/system/linkray-singbox.service"
test -f "$src/etc/systemd/system/linkray-singbox-runtime.service"
test -f "$src/etc/systemd/system/linkray-snell-runtime.service"
test -f "$src/etc/systemd/system/linkray-snell@.service"
test -f "$src/etc/systemd/system/linkray-snell-usage.service"
test -f "$src/etc/systemd/system/linkray-sub-auto.service"
test -f "$src/etc/systemd/system/linkray-relay.service"
test -f "$src/etc/systemd/system/linkray-rules-update.service"
test -f "$src/etc/systemd/system/linkray-rules-update.timer"
test -f "$src/var/lib/marzban/linkray/hosts.sql"
test -f "$src/var/lib/marzban/linkray/linkray-manifest.json"
test -f "$src/var/lib/marzban/linkray/source-patches/marzban-dashboard/README.md"
test -f "$src/var/lib/marzban/linkray/source-patches/marzban-dashboard/linkray-dashboard.patch"
test -f "$src/var/lib/marzban/linkray/xray/runtime.json"
test -f "$src/var/lib/marzban/linkray/singbox/config.json"
test -f "$src/var/lib/marzban/linkray/singbox/users.json"
test -f "$src/var/lib/marzban/linkray/snell/snell-server.conf"
test -f "$src/etc/sysctl.d/99-linkray-network.conf"
test -f "$src/etc/modules-load.d/linkray-bbr.conf"
test -f "$src/var/lib/marzban/linkray/rules/cn-domains.txt"
test -f "$src/var/lib/marzban/linkray/rules/cn-ip-cidrs.txt"
test -f "$src/var/lib/marzban/linkray/patches/clash.py"
test -f "$src/var/lib/marzban/linkray/patches/0_xray_core.py"
test -f "$src/var/lib/marzban/linkray/patches/xray_init.py"
test -f "$src/var/lib/marzban/linkray/jobs/linkray_singbox_usages.py"
test -f "$src/var/lib/marzban/templates/subscription/index.html"
test -f "$src/var/lib/marzban/dashboard-patches/index.linkray.js"

install -d \
  /var/lib/marzban \
  /var/lib/marzban/templates/clash \
  /var/lib/marzban/templates/subscription \
  /var/lib/marzban/dashboard-patches \
  /var/lib/marzban/linkray/patches \
  /var/lib/marzban/linkray/jobs \
  /var/lib/marzban/linkray/source-patches/marzban-dashboard \
  /var/lib/marzban/linkray/xray \
  /var/lib/marzban/linkray/singbox \
  /var/lib/marzban/linkray/snell \
  /var/lib/marzban/linkray/rules \
  /opt/marzban \
  /etc/nginx/conf.d \
  /etc/systemd/system \
  /etc/sysctl.d \
  /etc/modules-load.d
install -m 0644 "$src/var/lib/marzban/xray_config.json" /var/lib/marzban/xray_config.json
install -m 0644 "$src/var/lib/marzban/templates/clash/default.yml" /var/lib/marzban/templates/clash/default.yml
install -m 0644 "$src/var/lib/marzban/templates/subscription/index.html" /var/lib/marzban/templates/subscription/index.html
install -m 0644 "$src/var/lib/marzban/linkray/hosts.sql" /var/lib/marzban/linkray/hosts.sql
install -m 0644 "$src/var/lib/marzban/linkray/linkray-manifest.json" /var/lib/marzban/linkray/linkray-manifest.json
install -m 0644 "$src/var/lib/marzban/linkray/source-patches/marzban-dashboard/README.md" /var/lib/marzban/linkray/source-patches/marzban-dashboard/README.md
install -m 0644 "$src/var/lib/marzban/linkray/source-patches/marzban-dashboard/linkray-dashboard.patch" /var/lib/marzban/linkray/source-patches/marzban-dashboard/linkray-dashboard.patch
install -m 0644 "$src/var/lib/marzban/linkray/xray/runtime.json" /var/lib/marzban/linkray/xray/runtime.json
install -m 0644 "$src/var/lib/marzban/linkray/singbox/config.json" /var/lib/marzban/linkray/singbox/config.json
test -f /var/lib/marzban/linkray/singbox/users.json || install -m 0644 "$src/var/lib/marzban/linkray/singbox/users.json" /var/lib/marzban/linkray/singbox/users.json
install -m 0600 "$src/var/lib/marzban/linkray/snell/snell-server.conf" /var/lib/marzban/linkray/snell/snell-server.conf
install -m 0644 "$src/etc/sysctl.d/99-linkray-network.conf" /etc/sysctl.d/99-linkray-network.conf
install -m 0644 "$src/etc/modules-load.d/linkray-bbr.conf" /etc/modules-load.d/linkray-bbr.conf
install -m 0644 "$src/var/lib/marzban/linkray/rules/cn-domains.txt" /var/lib/marzban/linkray/rules/cn-domains.txt
install -m 0644 "$src/var/lib/marzban/linkray/rules/cn-ip-cidrs.txt" /var/lib/marzban/linkray/rules/cn-ip-cidrs.txt
install -m 0644 "$src/var/lib/marzban/linkray/patches/clash.py" /var/lib/marzban/linkray/patches/clash.py
install -m 0644 "$src/var/lib/marzban/linkray/patches/0_xray_core.py" /var/lib/marzban/linkray/patches/0_xray_core.py
install -m 0644 "$src/var/lib/marzban/linkray/patches/xray_init.py" /var/lib/marzban/linkray/patches/xray_init.py
install -m 0644 "$src/var/lib/marzban/linkray/jobs/linkray_singbox_usages.py" /var/lib/marzban/linkray/jobs/linkray_singbox_usages.py
install -m 0644 "$src/var/lib/marzban/dashboard-patches/index.html" /var/lib/marzban/dashboard-patches/index.html
install -m 0644 "$src/var/lib/marzban/dashboard-patches/index.linkray.js" /var/lib/marzban/dashboard-patches/index.linkray.js
install -m 0644 "$src/var/lib/marzban/dashboard-patches/index.original.js" /var/lib/marzban/dashboard-patches/index.original.js
install -m 0644 "$src/opt/marzban/docker-compose.yml" /opt/marzban/docker-compose.yml
install -m 0644 "$src/etc/nginx/conf.d/marzban-panel.conf" /etc/nginx/conf.d/marzban-panel.conf
install -m 0644 "$src/etc/systemd/system/linkray-api.service" /etc/systemd/system/linkray-api.service
install -m 0644 "$src/etc/systemd/system/linkray-clash.service" /etc/systemd/system/linkray-clash.service
install -m 0644 "$src/etc/systemd/system/linkray-egern.service" /etc/systemd/system/linkray-egern.service
install -m 0644 "$src/etc/systemd/system/linkray-shadowrocket.service" /etc/systemd/system/linkray-shadowrocket.service
install -m 0644 "$src/etc/systemd/system/linkray-singbox.service" /etc/systemd/system/linkray-singbox.service
install -m 0644 "$src/etc/systemd/system/linkray-singbox-runtime.service" /etc/systemd/system/linkray-singbox-runtime.service
install -m 0644 "$src/etc/systemd/system/linkray-snell-runtime.service" /etc/systemd/system/linkray-snell-runtime.service
install -m 0644 "$src/etc/systemd/system/linkray-snell@.service" /etc/systemd/system/linkray-snell@.service
install -m 0644 "$src/etc/systemd/system/linkray-snell-usage.service" /etc/systemd/system/linkray-snell-usage.service
install -m 0644 "$src/etc/systemd/system/linkray-sub-auto.service" /etc/systemd/system/linkray-sub-auto.service
install -m 0644 "$src/etc/systemd/system/linkray-relay.service" /etc/systemd/system/linkray-relay.service
install -m 0644 "$src/etc/systemd/system/linkray-rules-update.service" /etc/systemd/system/linkray-rules-update.service
install -m 0644 "$src/etc/systemd/system/linkray-rules-update.timer" /etc/systemd/system/linkray-rules-update.timer
if [[ -f "$src/etc/systemd/system/linkray-xray.service" ]]; then
  install -m 0644 "$linkray_xray_unit" /etc/systemd/system/linkray-xray.service
  linkray_xray_enabled=1
else
  systemctl stop linkray-xray 2>/dev/null || true
fi

cd /opt/marzban
if ! docker image inspect linkray:latest >/dev/null 2>&1; then
  docker image inspect gozargah/marzban:latest >/dev/null 2>&1 || docker pull gozargah/marzban:latest
  docker tag gozargah/marzban:latest linkray:latest
  docker rmi gozargah/marzban:latest >/dev/null 2>&1 || true
fi
docker rm -f marzban-marzban-1 2>/dev/null || true
docker compose up -d --force-recreate --remove-orphans linkray
sqlite3 /var/lib/marzban/db.sqlite3 < /var/lib/marzban/linkray/hosts.sql
sqlite3 /var/lib/marzban/db.sqlite3 \
  "delete from node_user_usages where node_id not in (select id from nodes);
   delete from node_usages where node_id not in (select id from nodes);
   delete from node_user_usages where node_id in (select id from nodes);
   delete from node_usages where node_id in (select id from nodes);
   delete from nodes;"
modprobe tcp_bbr || true
sysctl --system
default_if="$(ip route show default 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -1)"
if [[ -n "$default_if" ]]; then
  tc qdisc replace dev "$default_if" root fq 2>/dev/null || true
fi
systemctl daemon-reload
if [[ "$linkray_xray_enabled" -eq 1 ]]; then
  systemctl enable --now linkray-xray
else
  systemctl disable linkray-xray 2>/dev/null || true
fi
systemctl enable --now linkray-api
systemctl enable --now linkray-clash
systemctl enable --now linkray-egern
systemctl enable --now linkray-shadowrocket
systemctl enable --now linkray-singbox
systemctl enable --now linkray-singbox-runtime
systemctl enable --now linkray-snell-runtime
systemctl enable --now linkray-snell-usage
systemctl enable --now linkray-sub-auto
systemctl enable --now linkray-rules-update.timer
systemctl start linkray-rules-update.service || true
systemctl enable --now linkray-relay
if [[ "$linkray_xray_enabled" -eq 1 ]]; then
  systemctl restart linkray-xray
fi
systemctl restart linkray-api
systemctl restart linkray-clash
systemctl restart linkray-egern
systemctl restart linkray-shadowrocket
systemctl restart linkray-singbox
systemctl restart linkray-singbox-runtime
systemctl restart linkray-snell-runtime
systemctl restart linkray-snell-usage
systemctl restart linkray-sub-auto
systemctl restart linkray-relay
nginx -t
systemctl reload nginx
