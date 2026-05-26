# LinkRay

LinkRay packages a Marzban + Xray-core deployment into repeatable configuration and deployment assets.

It does not replace Marzban. Marzban remains the user, subscription, traffic, and node management control plane. Xray-core remains the proxy runtime. LinkRay owns the installation layout, Xray inbound set, Clash/Mihomo subscription template, Nginx entrypoint, and dashboard patch assets.

## Scope

LinkRay targets this baseline:

- One Marzban master plus optional Marzban Node servers.
- Xray-core managed by Marzban and Marzban Node.
- Twelve Xray-core inbound protocol families on every node:
  - VLESS TLS Vision
  - VLESS Reality Vision
  - VLESS Reality gRPC
  - Trojan TLS
  - VMess TLS
  - Shadowsocks TCP/UDP
  - VLESS WS TLS
  - VLESS gRPC TLS
  - VLESS XHTTP Reality
  - VMess WS TLS
  - VMess HTTPUpgrade TLS
  - Trojan gRPC TLS
- Clash/Mihomo template with policy groups and routing rules.
- Subscription format routing:
  - `/sub/<token>` is an automatic entrypoint that keeps browser, Egern, Shadowrocket, Clash/Mihomo, sing-box, and generic Base64 clients on the right response format when their client headers are identifiable
  - `/sub/<token>/egern` exposes an Egern-specific proxy resource for clients that do not identify themselves reliably
- Marzban dashboard patch:
  - the user Link button shows 自动识别订阅 first, then Clash/Mihomo, Shadowrocket, Egern, sing-box, and v2ray-json links
  - Create User protocol cards show the concrete LinkRay inbound forms under Vmess, Vless, Trojan, and Shadowsocks
  - Users page embeds Node Info backed by `linkray api`, with 10 rows per page and manual refresh
- Compatibility routes:
  - `/linkray/ports.html` redirects to `/dashboard/`
  - `/linkray/ports.json` proxies to `/api/linkray/nodes`
- Sidecar services:
  - `linkray-api.service` reports node port status
  - `linkray-egern.service` converts Marzban subscriptions into Egern YAML
  - `linkray-sub-auto.service` routes the base subscription URL to the best available format

sing-box, Hysteria2, TUIC, and AnyTLS are intentionally out of scope for v1. They need a separate stats and subscription integration layer before they can fit the Marzban-first model.

## Quick Start

Install the `linkray` command once:

```bash
./install.sh
```

Bootstrap a fresh master server from inside this repo:

```bash
export CF_Token='YOUR_CLOUDFLARE_DNS_API_TOKEN'
linkray bootstrap master \
  --domain edge-a.example.com \
  --node edge-a=edge-a.example.com \
  --node edge-b=edge-b.example.com \
  --admin-username admin \
  --admin-password 'CHANGE_THIS_PASSWORD' \
  --issue-cert \
  --apply
```

When it succeeds, open the Marzban dashboard at:

```text
https://<master-domain>:<panel-port>/dashboard/
```

If `--reality-private-key` and `--reality-short-id` are omitted during `--apply`, LinkRay generates them automatically and writes them into `/var/lib/marzban/xray_config.json`.

Bootstrap a fresh node server after placing its Marzban node client certificate at `/var/lib/marzban-node/ssl_client_cert.pem`:

```bash
linkray bootstrap node --apply
```

Run the same commands without `--apply` first to preview every file operation and shell command.

## Render And Install

Render master files:

```bash
linkray render master \
  --domain edge-a.example.com \
  --node edge-a=edge-a.example.com \
  --node edge-b=edge-b.example.com \
  --output /tmp/linkray-master
linkray validate --path /tmp/linkray-master
```

Override inbound ports when an existing environment does not use the defaults:

```bash
linkray render master \
  --domain edge-a.example.com \
  --node edge-a=edge-a.example.com \
  --inbound vless_tls=28080 \
  --inbound vless_reality=28081 \
  --output /tmp/linkray-master
```

The same `--inbound key=port` flags are supported by `linkray api` and `linkray ports`, so the dashboard Node Info panel can follow production port changes without code edits.

Deploy a rendered master tree on a prepared server:

```bash
sudo scripts/deploy-rendered-master.sh /tmp/linkray-master
```

Render node files:

```bash
linkray render node --output /tmp/linkray-node
linkray validate --path /tmp/linkray-node
```

Preview install actions without writing files:

```bash
linkray install master \
  --domain edge-a.example.com \
  --node edge-a=edge-a.example.com \
  --node edge-b=edge-b.example.com
linkray install node
```

Apply into a test root:

```bash
linkray install master \
  --domain edge-a.example.com \
  --node edge-a=edge-a.example.com \
  --node edge-b=edge-b.example.com \
  --root /tmp/linkray-install-master \
  --apply
```

## Verify

Run tests:

```bash
python3 -m unittest discover -s tests -v
```

Check a rendered or installed root:

```bash
linkray doctor --role master --root /tmp/linkray-install-master --no-runtime
linkray doctor --role node --root /tmp/linkray-install-node --no-runtime
```

Check a live server from inside that server:

```bash
linkray doctor --role master
linkray doctor --role node
```

## Production Rule

Do not hand-edit live Marzban container files as the primary workflow. Export known-good changes into this repo, render files from LinkRay, then deploy those rendered files.

The current dashboard patch under `patches/marzban-dashboard/current/` is a compatibility snapshot from a Marzban dashboard build. It should eventually be replaced by a source-level dashboard patch against a pinned Marzban version.

## Marzban Host SQL

`render master` and `install master` generate `var/lib/marzban/linkray/hosts.sql`. This SQL initializes Marzban `inbounds` and `hosts` rows for the selected nodes.

Review the SQL before applying it:

```bash
sqlite3 /var/lib/marzban/db.sqlite3 < /var/lib/marzban/linkray/hosts.sql
```

For a two-node topology, the SQL creates 24 host rows: 2 nodes times 12 protocol entries.
