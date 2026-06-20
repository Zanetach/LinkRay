# Deployment Guide

This guide describes the stable LinkRay v0.2.0 deployment shape. A fresh
environment is expected to become usable from a release tarball plus one
`bootstrap master --apply` command. Additional servers join with
`bootstrap node --apply`.

## Install Command

From the LinkRay repo on the server:

```bash
./install.sh
```

This installs LinkRay into `/opt/linkray/venv` and creates `/usr/local/bin/linkray`, so operational commands use `linkray ...` instead of `python3 -m linkray ...`.

From a release artifact:

```bash
curl -L https://github.com/Zanetach/LinkRay/releases/download/v0.2.0/linkray-0.2.0.tar.gz -o linkray-0.2.0.tar.gz
tar -xzf linkray-0.2.0.tar.gz
cd linkray-0.2.0
sudo ./install.sh
```

## Architecture Boundary

Only the `master` role installs Docker and runs the LinkRay panel container. The `node` role is intentionally host-native: it does not install Docker, does not run Docker Compose, and does not deploy a panel. Node deployment starts only systemd services for LinkRay Node, Xray-core, optional sing-box, optional Snell, and usage sync.

This boundary is part of the packaging contract. Future release bundles and one-click installers must preserve it:

- `linkray bootstrap master` may install Docker and start `container_name: linkray`.
- `linkray bootstrap node` must not install Docker and must not start a container.
- `scripts/deploy-rendered-master.sh` may run Docker Compose.
- `scripts/deploy-rendered-node.sh` may stop/remove old legacy node containers, but must not install Docker or run Docker Compose.

## Fresh Server Bootstrap

For a new master server, this is the intended one-command operational path
after `install.sh`:

```bash
export CF_Token='YOUR_CLOUDFLARE_DNS_API_TOKEN'
sudo -E linkray bootstrap master \
  --domain edge-a.example.com \
  --node edge-a=edge-a.example.com \
  --node edge-b=edge-b.example.com \
  --admin-username admin \
  --admin-password 'CHANGE_THIS_PASSWORD' \
  --issue-cert \
  --apply
```

The resulting dashboard is available at:

```text
https://edge-a.example.com:9443/dashboard/
```

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

The master bootstrap writes LinkRay-managed files, installs required system packages, installs Docker when missing, applies BBR/fq network acceleration, builds sing-box with LinkRay-required tags, obtains the TLS certificate through acme.sh DNS Cloudflare, starts the LinkRay panel container, applies `hosts.sql`, validates Nginx, reloads Nginx, and runs `doctor`.

By default, Xray-core remains LinkRay panel-managed for compatibility with user, subscription, and traffic workflows. To render the optional unified runtime shape where LinkRay owns the Xray systemd unit, pass:

```bash
--xray-runtime linkray
```

That mode adds `linkray-xray.service` and removes the Xray binary bind mount from the LinkRay Docker Compose file.

LinkRay builds `/usr/local/bin/sing-box` with:

```text
with_v2ray_api with_quic with_utls with_clash_api
```

The ordinary upstream release binary does not include the V2Ray API stats service needed by the LinkRay sing-box usage sync job. That job also reconciles active LinkRay usernames with the local sing-box sidecar, pruning disabled, deleted, expired, or limited users from the sing-box runtime config.

Both master and node bootstraps render, install, and apply these network acceleration defaults:

```text
/etc/sysctl.d/99-linkray-network.conf
/etc/modules-load.d/linkray-bbr.conf
```

The sysctl file enables `fq` queueing, `bbr` congestion control, MTU probing, TCP Fast Open, and disables slow start after idle. Runtime bootstrap and rendered deployment scripts also run `modprobe tcp_bbr`, `sysctl --system`, and `tc qdisc replace dev <default-iface> root fq` so the active server benefits immediately without a reboot.

LinkRay also installs the pinned Snell v5 server binary and renders:

```text
/var/lib/marzban/linkray/snell/snell-server.conf
/etc/systemd/system/linkray-snell-runtime.service
/etc/systemd/system/linkray-snell@.service
/etc/systemd/system/linkray-snell-usage.service
```

The Shadowrocket adapter keeps `/shadowrocket` as the normal node subscription path. The full `/shadowrocket-conf` configuration path generates per-user Snell credentials, writes `/var/lib/marzban/linkray/snell/users/<instance>.conf`, and starts `linkray-snell@<instance>`. Clash/Mihomo subscriptions deliberately exclude Snell v5 because common Mihomo cores reject `version: 5`. Snell usage sync is handled by `linkray-snell-usage.service`: it maintains per-user port counters and lets the LinkRay job write deltas into user, admin, and hourly usage tables.

If Reality values are not provided through `--reality-private-key` and `--reality-short-id`, `bootstrap master --apply` generates them automatically before writing `/var/lib/marzban/xray_config.json`.

On a new node server, place the LinkRay node client certificate at `/var/lib/marzban-node/ssl_client_cert.pem`, then run:

```bash
linkray bootstrap node \
  --domain edge-b.example.com \
  --apply
```

The node bootstrap installs required packages, installs the LinkRay Node host app under `/opt/linkray-node-app/current`, creates `/opt/linkray-node-app/venv`, installs Xray-core under `/var/lib/marzban/linkray/bin`, starts `linkray-node.service`, enables `linkray-xray.service`, and runs `doctor`.

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
linkray render node --domain edge-b.example.com --output /tmp/linkray-node
linkray validate --path /tmp/linkray-node
```

The rendered node tree contains:

- `opt/linkray-node-app/current/*`
- `etc/systemd/system/linkray-node.service`
- `etc/systemd/system/linkray-xray.service`
- `etc/systemd/system/linkray-singbox-runtime.service` when rendered with a node domain
- `etc/systemd/system/linkray-snell-runtime.service` when rendered with a node domain
- `etc/systemd/system/linkray-snell@.service` when rendered with a node domain
- `etc/systemd/system/linkray-snell-usage.service` when rendered with a node domain
- `var/lib/marzban/linkray/singbox/config.json` when rendered with a node domain
- `var/lib/marzban/linkray/singbox/users.json` when rendered with a node domain
- `var/lib/marzban/linkray/snell/snell-server.conf` when rendered with a node domain

## Master Deployment Shape

1. Install Docker and the Docker Compose plugin.
2. Create `/opt/marzban/.env` with LinkRay production values.
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

`linkray-rules-update.service` downloads local MetaCubeX rule assets into `/var/lib/marzban/linkray/rules`. After it runs, these paths should exist:

```bash
test -s /var/lib/marzban/linkray/rules/geosite.dat
test -s /var/lib/marzban/linkray/rules/geoip.dat
test -s /var/lib/marzban/linkray/rules/mihomo/geosite-cn.mrs
test -s /var/lib/marzban/linkray/rules/mihomo/geoip-cn.mrs
test -s /var/lib/marzban/linkray/rules/sing-box/geosite-cn.srs
test -s /var/lib/marzban/linkray/rules/sing-box/geoip-cn.srs
```

Clash/Mihomo and sing-box subscriptions point to these same-origin files through `/linkray/rules/`, so clients do not need to fetch rule assets from GitHub directly.

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

- Required LinkRay files.
- Nginx systemd state.
- Standalone `xray.service` is inactive.
- LinkRay panel-managed Xray process exists in the default mode.
- `linkray-xray.service` and the LinkRay-managed Xray process exist when the manifest says `xray_runtime_mode=linkray`.
- Expected LinkRay ports are listening.
- The sing-box runtime API port and Hysteria2/TUIC/AnyTLS inbound ports are listening on the master.
- The Snell runtime service and Snell inbound port are listening on the master.

## Secondary Node Relay

For two-node deployments, LinkRay advertises the second node through master-side relay ports so clients that cannot directly reach the second node still see normal, non-chained proxy entries. The first secondary node uses `inbound_port + 100`; for example, `18080` becomes `18180` on the master and relays to the secondary node's `18080`. TLS SNI and WebSocket Host remain the secondary node domain, so Xray protocol handshakes still terminate on the secondary node.

## Node Deployment Shape

1. Install the node certificate at `/var/lib/marzban-node/ssl_client_cert.pem`.
2. Copy rendered `/tmp/linkray-node/opt/linkray-node-app/current/*` into `/opt/linkray-node-app/current/`.
3. Create `/opt/linkray-node-app/venv` and install `/opt/linkray-node-app/current/requirements.txt`.
4. Copy rendered systemd units into `/etc/systemd/system/`.
5. Install the Xray-core binary and geo data under `/var/lib/marzban/linkray/bin/`.
6. Stop any old `linkray-node` Docker container if it exists.
7. Run:

```bash
systemctl daemon-reload
systemctl enable linkray-xray
systemctl enable --now linkray-node
systemctl restart linkray-node
```

Use the helper script for the same prepared-host steps:

```bash
sudo scripts/deploy-rendered-node.sh /tmp/linkray-node
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
curl -ksS '<marzban-subscription-url>/clash-meta-full' -o /tmp/linkray-full.yaml
mihomo -t -f /tmp/linkray-full.yaml
curl -ksS '<marzban-subscription-url>/shadowrocket' -o /tmp/linkray-shadowrocket-sub.txt
curl -ksS '<marzban-subscription-url>/shadowrocket-conf' -o /tmp/linkray-shadowrocket.conf
curl -ksS '<marzban-subscription-url>/sing-box' -o /tmp/linkray-sing-box.json
sing-box check -c /tmp/linkray-sing-box.json
```

Expected result for a two-node deployment:

- Stable Clash/Mihomo contains the conservative client-safe subset
- Full Clash/Mihomo contains the complete Xray inventory for diagnostics
- 19 policy groups
- 79 rules
- `mihomo -t` succeeds
