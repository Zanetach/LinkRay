# Deployment Guide

## Install Command

From the LinkRay repo on the server:

```bash
./install.sh
```

This installs LinkRay into `/opt/linkray/venv` and creates `/usr/local/bin/linkray`, so operational commands use `linkray ...` instead of `python3 -m linkray ...`.

## Fresh Server Bootstrap

On a new master server, run the dry-run first:

```bash
export CF_Token='YOUR_CLOUDFLARE_DNS_API_TOKEN'
linkray bootstrap master \
  --domain edge-a.example.com \
  --node edge-a=edge-a.example.com \
  --node edge-b=edge-b.example.com \
  --admin-username admin \
  --admin-password 'CHANGE_THIS_PASSWORD' \
  --issue-cert
```

Apply it after reviewing the output:

```bash
linkray bootstrap master \
  --domain edge-a.example.com \
  --node edge-a=edge-a.example.com \
  --node edge-b=edge-b.example.com \
  --admin-username admin \
  --admin-password 'CHANGE_THIS_PASSWORD' \
  --issue-cert \
  --apply
```

The master bootstrap writes LinkRay-managed files, installs required system packages, installs Docker when missing, builds sing-box with LinkRay-required tags, obtains the TLS certificate through acme.sh DNS Cloudflare, starts Marzban, applies `hosts.sql`, validates Nginx, reloads Nginx, and runs `doctor`.

By default, Xray-core remains Marzban-managed for compatibility with Marzban user, subscription, and traffic workflows. To render the optional unified runtime shape where LinkRay owns the Xray systemd unit, pass:

```bash
--xray-runtime linkray
```

That mode adds `linkray-xray.service` and removes the Xray binary bind mount from the Marzban Docker Compose file.

LinkRay builds `/usr/local/bin/sing-box` with:

```text
with_v2ray_api with_quic with_utls with_clash_api
```

The ordinary upstream release binary does not include the V2Ray API stats service needed by the LinkRay sing-box usage sync job. That job also reconciles active Marzban usernames with the local sing-box sidecar, pruning disabled, deleted, expired, or limited users from the sing-box runtime config.

LinkRay also installs the pinned Snell v5 server binary and renders:

```text
/var/lib/marzban/linkray/snell/snell-server.conf
/etc/systemd/system/linkray-snell-runtime.service
/etc/systemd/system/linkray-snell@.service
/etc/systemd/system/linkray-snell-usage.service
```

The Clash/Mihomo and Shadowrocket adapters generate per-user Snell credentials on subscription request, write `/var/lib/marzban/linkray/snell/users/<instance>.conf`, and start `linkray-snell@<instance>`. Snell usage sync is handled by `linkray-snell-usage.service`: it maintains per-user port counters and lets the Marzban job write deltas into user, admin, and hourly usage tables.

If Reality values are not provided through `--reality-private-key` and `--reality-short-id`, `bootstrap master --apply` generates them automatically before writing `/var/lib/marzban/xray_config.json`.

On a new node server, place the Marzban node client certificate at `/var/lib/marzban-node/ssl_client_cert.pem`, then run:

```bash
linkray bootstrap node --apply
```

The node bootstrap installs required packages, installs Docker when missing, writes `/opt/marzban-node/docker-compose.yml`, starts Marzban Node, and runs `doctor`.

## Master Render

```bash
linkray render master \
  --domain edge-a.example.com \
  --node edge-a=edge-a.example.com \
  --node edge-b=edge-b.example.com \
  --output /tmp/linkray-master
linkray validate --path /tmp/linkray-master
```

Render the optional LinkRay-managed Xray runtime:

```bash
linkray render master \
  --domain edge-a.example.com \
  --node edge-a=edge-a.example.com \
  --node edge-b=edge-b.example.com \
  --xray-runtime linkray \
  --output /tmp/linkray-master
linkray validate --path /tmp/linkray-master
```

The rendered master tree contains:

- `var/lib/marzban/xray_config.json`
- `var/lib/marzban/linkray/hosts.sql`
- `var/lib/marzban/linkray/patches/clash.py`
- `var/lib/marzban/linkray/jobs/linkray_singbox_usages.py`
- `var/lib/marzban/linkray/singbox/config.json`
- `var/lib/marzban/linkray/singbox/users.json`
- `var/lib/marzban/linkray/snell/snell-server.conf`
- `var/lib/marzban/linkray/snell/users/` after users request Snell-capable subscriptions
- `var/lib/marzban/templates/clash/default.yml`
- `var/lib/marzban/dashboard-patches/*`
- `opt/marzban/docker-compose.yml`
- `etc/nginx/conf.d/marzban-panel.conf`
- `etc/systemd/system/linkray-api.service`
- `etc/systemd/system/linkray-clash.service`
- `etc/systemd/system/linkray-egern.service`
- `etc/systemd/system/linkray-shadowrocket.service`
- `etc/systemd/system/linkray-singbox.service`
- `etc/systemd/system/linkray-singbox-runtime.service`
- `etc/systemd/system/linkray-snell-runtime.service`
- `etc/systemd/system/linkray-snell@.service`
- `etc/systemd/system/linkray-snell-usage.service`
- `etc/systemd/system/linkray-sub-auto.service`
- `etc/systemd/system/linkray-relay.service`
- `etc/systemd/system/linkray-xray.service` when rendered with `--xray-runtime linkray`

## Node Render

```bash
linkray render node --output /tmp/linkray-node
linkray validate --path /tmp/linkray-node
```

The rendered node tree contains:

- `opt/marzban-node/docker-compose.yml`

## Master Deployment Shape

1. Install Docker and the Docker Compose plugin.
2. Create `/opt/marzban/.env` with Marzban production values.
3. Copy rendered `/tmp/linkray-master/var/lib/marzban/*` into `/var/lib/marzban/`.
4. Copy rendered `/tmp/linkray-master/opt/marzban/docker-compose.yml` into `/opt/marzban/docker-compose.yml`.
5. Copy rendered `/tmp/linkray-master/etc/nginx/conf.d/marzban-panel.conf` into `/etc/nginx/conf.d/marzban-panel.conf`.
6. Copy rendered `/tmp/linkray-master/etc/systemd/system/linkray-*.service` into `/etc/systemd/system/`.
7. Review and apply `/var/lib/marzban/linkray/hosts.sql`:

```bash
sqlite3 /var/lib/marzban/db.sqlite3 < /var/lib/marzban/linkray/hosts.sql
```

8. Run:

```bash
cd /opt/marzban && docker compose up -d
systemctl daemon-reload
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
```

The helper script performs the same copy and service steps for a prepared host:

```bash
sudo scripts/deploy-rendered-master.sh /tmp/linkray-master
```

## Install Command

Use install without `--apply` to preview file operations:

```bash
linkray install master \
  --domain edge-a.example.com \
  --node edge-a=edge-a.example.com \
  --node edge-b=edge-b.example.com
```

Use `--apply` to copy rendered files. Existing files are backed up with a `.linkray.bak-<timestamp>` suffix before replacement.

```bash
linkray install master \
  --domain edge-a.example.com \
  --node edge-a=edge-a.example.com \
  --node edge-b=edge-b.example.com \
  --apply
```

The install command copies files only. It does not automatically run `sqlite3`, `docker compose`, or `nginx -t`.

## Doctor

Run file-only checks against a rendered or staged root:

```bash
linkray doctor --role master --root /tmp/linkray-master --no-runtime
linkray doctor --role node --root /tmp/linkray-node --no-runtime
```

Run runtime checks from inside a live server:

```bash
linkray doctor --role master
linkray doctor --role node
```

`doctor` checks:

- Required LinkRay/Marzban files.
- Nginx systemd state.
- Standalone `xray.service` is inactive.
- Marzban-managed Xray process exists in the default mode.
- `linkray-xray.service` and the LinkRay-managed Xray process exist when the manifest says `xray_runtime_mode=linkray`.
- Expected LinkRay ports are listening.
- The sing-box runtime API port and Hysteria2/TUIC/AnyTLS inbound ports are listening on the master.
- The Snell runtime service and Snell inbound port are listening on the master.

## Secondary Node Relay

For two-node deployments, LinkRay advertises the second node through master-side relay ports so clients that cannot directly reach the second node still see normal, non-chained proxy entries. The first secondary node uses `inbound_port + 100`; for example, `18080` becomes `18180` on the master and relays to the secondary node's `18080`. TLS SNI and WebSocket Host remain the secondary node domain, so Xray protocol handshakes still terminate on the secondary node.

## Node Deployment Shape

1. Install Docker and the Docker Compose plugin.
2. Copy rendered `/tmp/linkray-node/opt/marzban-node/docker-compose.yml` into `/opt/marzban-node/docker-compose.yml`.
3. Install the node certificate at `/var/lib/marzban-node/ssl_client_cert.pem`.
4. Run:

```bash
cd /opt/marzban-node && docker compose up -d
```

## Post-Deployment Verification

Check master:

```bash
curl -ksS -o /dev/null -w '%{http_code}\n' https://<master-domain>:<panel-port>/api/system
ss -lntup
```

Check subscription from a client machine:

```bash
curl -ksS '<marzban-subscription-url>/clash-meta' -o /tmp/linkray.yaml
mihomo -t -f /tmp/linkray.yaml
curl -ksS '<marzban-subscription-url>/shadowrocket-conf' -o /tmp/linkray-shadowrocket.conf
curl -ksS '<marzban-subscription-url>/shadowrocket' -o /tmp/linkray-shadowrocket.txt
curl -ksS '<marzban-subscription-url>/sing-box' -o /tmp/linkray-sing-box.json
sing-box check -c /tmp/linkray-sing-box.json
```

Expected result for a two-node deployment:

- 24 proxies
- 19 policy groups
- 79 rules
- `mihomo -t` succeeds
