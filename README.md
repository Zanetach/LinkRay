<div align="center">
  <h1>LinkRay</h1>
  <p><b>Repeatable Marzban + Xray-core deployment tooling for multi-node proxy operations.</b></p>
  <a href="https://github.com/Zanetach/LinkRay/stargazers"><img src="https://img.shields.io/github/stars/Zanetach/LinkRay?style=flat-square" alt="Stars"></a>
  <a href="https://github.com/Zanetach/LinkRay/releases"><img src="https://img.shields.io/github/v/tag/Zanetach/LinkRay?label=version&style=flat-square" alt="Version"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/python-3.9%2B-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python 3.9+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square" alt="License"></a>
</div>

![LinkRay README hero](assets/linkray-readme-hero.png)

## Why

LinkRay packages a Marzban + Xray-core deployment into repeatable configuration, rendered assets, sidecar services, and health checks. Marzban remains the user, subscription, traffic, and node management control plane. Xray-core remains the proxy runtime. LinkRay owns the operational layer around them: installation layout, inbound definitions, subscription adapters, Nginx entrypoint, dashboard patch assets, and node status surfaces.

The goal is simple: stop hand-editing live container files as the primary workflow. Make changes in this repository, render the deployment tree, validate it, then apply the rendered files to a prepared host.

## What It Builds

| Surface | LinkRay owns |
|---|---|
| Master render | Marzban Docker Compose, Nginx config, Xray config, SQL host initialization, dashboard patches, subscription templates, sidecar systemd units |
| Node render | Marzban Node Docker Compose and install shape |
| Inbound set | 12 Xray-core inbound protocol families with overridable ports |
| Subscription routing | Browser/client-aware `/sub/<token>` routing plus Egern and Shadowrocket adapters |
| Dashboard patch | User link ordering, concrete protocol card labels, and Node Info backed by `linkray api` |
| Multi-node relay | Master-side TCP relay ports for secondary nodes, avoiding client-side proxy chaining |
| Runtime checks | `linkray doctor` file and runtime health checks for master and node roles |

## Protocol Coverage

LinkRay renders these inbound families for every node:

| Family | Transport / security |
|---|---|
| VLESS TLS Vision | TCP + TLS |
| VLESS Reality Vision | TCP + Reality |
| VLESS Reality gRPC | gRPC + Reality |
| Trojan TLS | TCP + TLS |
| VMess TLS | TCP + TLS |
| Shadowsocks | TCP / UDP |
| VLESS WS TLS | WebSocket + TLS |
| VLESS gRPC TLS | gRPC + TLS |
| VLESS XHTTP Reality | XHTTP + Reality |
| VMess WS TLS | WebSocket + TLS |
| VMess HTTPUpgrade TLS | HTTPUpgrade + TLS |
| Trojan gRPC TLS | gRPC + TLS |

sing-box, Hysteria2, TUIC, and AnyTLS are intentionally out of scope for v1. They need a separate stats and subscription integration layer before they can fit the Marzban-first model.

## Install

Install the `linkray` command once from inside the repository:

```bash
./install.sh
```

The installer must run as root because it writes the default install location and command shim:

```text
/opt/linkray/venv
/usr/local/bin/linkray
```

After installation:

```bash
linkray --help
```

## Fresh Master Bootstrap

Preview every file operation and shell command before applying:

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

Apply only after reviewing the dry run:

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

When it succeeds, open:

```text
https://<master-domain>:<panel-port>/dashboard/
```

If `--reality-private-key` and `--reality-short-id` are omitted during `--apply`, LinkRay generates them automatically and writes them into `/var/lib/marzban/xray_config.json`.

## Fresh Node Bootstrap

Place the Marzban node client certificate first:

```text
/var/lib/marzban-node/ssl_client_cert.pem
```

Then bootstrap the node:

```bash
linkray bootstrap node --apply
```

## Render First

Render master files into a staging directory:

```bash
linkray render master \
  --domain edge-a.example.com \
  --node edge-a=edge-a.example.com \
  --node edge-b=edge-b.example.com \
  --output /tmp/linkray-master
linkray validate --path /tmp/linkray-master
```

Render node files:

```bash
linkray render node --output /tmp/linkray-node
linkray validate --path /tmp/linkray-node
```

Override inbound ports when production already reserves the defaults:

```bash
linkray render master \
  --domain edge-a.example.com \
  --node edge-a=edge-a.example.com \
  --inbound vless_tls=28080 \
  --inbound vless_reality=28081 \
  --output /tmp/linkray-master
```

The same `--inbound key=port` flags are supported by `linkray api` and `linkray ports`, so the dashboard Node Info panel can follow production port changes without code edits.

## Command Map

| Command | Purpose |
|---|---|
| `linkray render master` | Render master deployment files |
| `linkray render node` | Render Marzban Node files |
| `linkray validate --path <dir>` | Validate a rendered tree |
| `linkray install master` | Copy rendered master files into a root, dry-run by default |
| `linkray install node` | Copy rendered node files into a root, dry-run by default |
| `linkray bootstrap master` | Configure a fresh master end to end |
| `linkray bootstrap node` | Configure a fresh node end to end |
| `linkray doctor --role master` | Check master files and runtime health |
| `linkray doctor --role node` | Check node files and runtime health |
| `linkray api` | Serve node status JSON for the dashboard patch |
| `linkray egern` | Convert Marzban subscriptions into Egern YAML |
| `linkray shadowrocket` | Convert Marzban subscriptions into Shadowrocket config |
| `linkray sub-auto` | Route the base subscription URL to the best identifiable format |
| `linkray relay` | Expose master-side relay ports for secondary nodes |
| `linkray rules update` | Refresh CN domain and IP CIDR routing rule files |

## Subscription Routes

| Route | Output |
|---|---|
| `/sub/<token>` | Automatic format routing for identifiable clients |
| `/sub/<token>/egern` | Egern-specific proxy resource |
| `/sub/<token>/shadowrocket` | Shadowrocket node subscription |
| `/linkray/ports.html` | Compatibility redirect to `/dashboard/` |
| `/linkray/ports.json` | Proxy to `/api/linkray/nodes` |

## Sidecar Services

Rendered master deployments include these LinkRay-managed systemd units:

| Unit | Purpose |
|---|---|
| `linkray-api.service` | Reports node port status |
| `linkray-egern.service` | Converts Marzban subscriptions into Egern YAML |
| `linkray-shadowrocket.service` | Converts Marzban subscriptions into Shadowrocket config |
| `linkray-sub-auto.service` | Routes base subscription URLs by client headers |
| `linkray-rules-update.service` | Refreshes route rule files |
| `linkray-rules-update.timer` | Schedules route rule refreshes |
| `linkray-relay.service` | Relays secondary-node ports from the master |

For a two-node topology, LinkRay publishes secondary nodes through master relay ports by default. The first secondary node uses each inbound port plus `100` for its public subscription port, while TLS SNI and WebSocket Host still point at the real secondary-node domain.

## Deploy Rendered Files

Deploy a rendered master tree on a prepared host:

```bash
sudo scripts/deploy-rendered-master.sh /tmp/linkray-master
```

Or use install mode to preview and apply file copies:

```bash
linkray install master \
  --domain edge-a.example.com \
  --node edge-a=edge-a.example.com \
  --node edge-b=edge-b.example.com

linkray install master \
  --domain edge-a.example.com \
  --node edge-a=edge-a.example.com \
  --node edge-b=edge-b.example.com \
  --apply
```

The install command copies files only. It does not automatically run `sqlite3`, `docker compose`, or `nginx -t`.

## Verify

Run the test suite:

```bash
python3 -m unittest discover -s tests -v
```

Check a rendered or installed root:

```bash
linkray doctor --role master --root /tmp/linkray-master --no-runtime
linkray doctor --role node --root /tmp/linkray-node --no-runtime
```

Check a live server from inside that server:

```bash
linkray doctor --role master
linkray doctor --role node
```

## Production Rule

Do not hand-edit live Marzban container files as the primary workflow. Export known-good changes into this repo, render files from LinkRay, validate them, then deploy those rendered files.

The current dashboard patch under `patches/marzban-dashboard/current/` is a compatibility snapshot from a Marzban dashboard build. It should eventually be replaced by a source-level dashboard patch against a pinned Marzban version.

## Marzban Host SQL

`render master` and `install master` generate:

```text
var/lib/marzban/linkray/hosts.sql
```

This SQL initializes Marzban `inbounds` and `hosts` rows for the selected nodes. Review it before applying:

```bash
sqlite3 /var/lib/marzban/db.sqlite3 < /var/lib/marzban/linkray/hosts.sql
```

For a two-node topology, the SQL creates 24 host rows: 2 nodes times 12 protocol entries.

## Repository Layout

```text
linkray/                                  # Python CLI and deployment renderer
linkray/assets/                           # packaged templates and dashboard patches
templates/                                # source deployment templates
patches/                                  # source Marzban patch snapshots
scripts/deploy-rendered-master.sh         # deploy rendered master tree to a prepared host
scripts/deploy-rendered-node.sh           # deploy rendered node tree to a prepared host
tests/                                    # unittest coverage for renderer, adapters, doctor, relay, installer
docs/DEPLOYMENT.md                        # detailed deployment guide
install.sh                                # root installer for /usr/local/bin/linkray
pyproject.toml                            # Python package metadata
```

## More

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the full deployment guide.

## License

MIT License. See [LICENSE](LICENSE).
