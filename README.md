<div align="center">
  <h1>LinkRay</h1>
  <p><b>Repeatable LinkRay + Xray-core + sing-box + Snell deployment tooling for multi-node proxy operations.</b></p>
  <a href="https://github.com/Zanetach/LinkRay/stargazers"><img src="https://img.shields.io/github/stars/Zanetach/LinkRay?style=flat-square" alt="Stars"></a>
  <a href="https://github.com/Zanetach/LinkRay/releases"><img src="https://img.shields.io/github/v/tag/Zanetach/LinkRay?label=version&style=flat-square" alt="Version"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/python-3.9%2B-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python 3.9+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square" alt="License"></a>
</div>

![LinkRay README hero](assets/linkray-readme-hero.png)

## Why

LinkRay packages the LinkRay control plane plus Xray-core into repeatable configuration, rendered assets, sidecar services, and health checks. LinkRay owns the user-facing panel, subscription, traffic, and node-management experience while reusing the Marzban API and data model internally. Xray-core remains the primary proxy runtime. LinkRay can also run experimental LinkRay-managed runtimes for Xray-core, sing-box, and Snell. The sing-box runtime powers Hysteria2, TUIC, and AnyTLS with generated user credentials and a LinkRay job that syncs sing-box stats back into the internal usage tables.

The goal is simple: stop hand-editing live container files as the primary workflow. Make changes in this repository, render the deployment tree, validate it, then apply the rendered files to a prepared host.

## What It Builds

| Surface | LinkRay owns |
|---|---|
| Master render | LinkRay panel Docker Compose, Nginx config, Xray config, SQL host initialization, dashboard patches, subscription templates, sidecar systemd units |
| Node render | Host systemd LinkRay Node service, LinkRay-managed Xray-core service, and optional host sing-box/Snell runtimes |
| Inbound set | 12 Xray-core inbound protocol families plus 3 experimental sing-box inbound families plus per-user Snell runtime support, all with overridable ports |
| Subscription routing | Browser/client-aware `/sub/<token>` routing plus Clash/Mihomo, Egern, Shadowrocket, and sing-box adapters |
| Dashboard patch | User link ordering, concrete protocol card labels, and Node Info backed by `linkray api` |
| Multi-node relay | Master-side TCP relay ports for secondary nodes, avoiding client-side proxy chaining |
| Runtime checks | `linkray doctor` file, manifest, port, and runtime health checks for master and node roles |

## Deployment Architecture Boundary

LinkRay has one fixed production split:

- `master` is the only role that installs Docker and runs the LinkRay panel container.
- `node` never installs Docker, never runs the panel, and never depends on Docker Compose.
- `node` runs host systemd services only: `linkray-node`, `linkray-xray`, optional `linkray-singbox-runtime`, optional `linkray-snell-runtime`, and usage services.
- Packaging and one-click deployment must keep this split explicit. A packaged node install may clean up old Docker containers, but it must not install Docker or start a node container.

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

Clash/Mihomo and sing-box are supported as client subscription formats through LinkRay sidecars. The master keeps the LinkRay dashboard/control plane in Docker. Secondary nodes run LinkRay Node, Xray-core, sing-box, and Snell as host systemd services, so CA and LA use the same runtime shape outside the panel container.

Hysteria2, TUIC, and AnyTLS are experimental production paths:

- `linkray-singbox-runtime.service` runs sing-box on the master.
- `linkray-singbox.service` creates per-subscription credentials when the sing-box subscription is requested.
- The generated sing-box subscription includes the normal LinkRay/Xray nodes plus Hysteria2, TUIC, and AnyTLS outbounds.
- `linkray_singbox_usages.py` is mounted into the LinkRay panel container and periodically syncs sing-box V2Ray API stats into the internal `users`, `admins`, `system`, and hourly usage tables.
- The same LinkRay job reconciles active usernames with the local sing-box sidecar so disabled, deleted, expired, or limited users are pruned from the sing-box runtime config.

The sing-box binary must be built with `with_v2ray_api`, `with_quic`, `with_utls`, and `with_clash_api`. `bootstrap master` does this automatically with Go 1.23.12. Check the explicit matrix with:

Snell is experimental but usable for supported clients:

- `linkray-snell-runtime.service` runs `snell-server`.
- `linkray-snell@.service` runs per-user Snell server instances.
- `linkray-snell-usage.service` exposes local Snell usage deltas for the LinkRay job.
- The generated config lives at `/var/lib/marzban/linkray/snell/snell-server.conf`.
- Per-user configs are written under `/var/lib/marzban/linkray/snell/users/`.
- Shadowrocket config can append per-user Snell v5 nodes; Clash/Mihomo subscriptions deliberately exclude Snell to avoid core validation failures on clients that do not support Snell v5.
- LinkRay traffic sync for Snell uses per-user port counters and writes usage into the same user, admin, and hourly tables as the sing-box sync job.

```bash
linkray protocols
linkray protocols --json
```

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

Build release artifacts locally:

```bash
scripts/build-release.sh
```

The release script creates `dist/*.tar.gz` and `dist/*.whl`, installs the wheel into a temporary virtualenv, and smoke-tests `linkray --help`.

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

`bootstrap master` builds `/usr/local/bin/sing-box` from source with:

```text
with_v2ray_api with_quic with_utls with_clash_api
```

These tags are required for the advanced runtime and for validating generated sing-box client configs. The ordinary upstream sing-box release binary does not include the V2Ray API stats service required for LinkRay usage sync.

`bootstrap master` and `bootstrap node` also install and apply LinkRay network acceleration defaults:

```text
net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr
net.ipv4.tcp_mtu_probing=1
net.ipv4.tcp_slow_start_after_idle=0
net.ipv4.tcp_fastopen=3
```

The settings are written to `/etc/sysctl.d/99-linkray-network.conf`, `tcp_bbr` is loaded through `/etc/modules-load.d/linkray-bbr.conf`, and the active default interface is switched to `fq` without requiring a reboot.

## Fresh Node Bootstrap

Place the LinkRay node client certificate first:

```text
/var/lib/marzban-node/ssl_client_cert.pem
```

Then bootstrap the node:

```bash
linkray bootstrap node \
  --domain edge-b.example.com \
  --apply
```

Or pull the certificate from a master over SSH during bootstrap:

```bash
linkray bootstrap node \
  --domain edge-b.example.com \
  --pull-cert-from root@edge-a.example.com \
  --remote-cert-path /var/lib/marzban/ssl_client_cert.pem \
  --apply
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

Render the optional unified Xray runtime mode when you are ready to let LinkRay own the Xray systemd service instead of mounting the Xray binary into the LinkRay panel container:

```bash
linkray render master \
  --domain edge-a.example.com \
  --node edge-a=edge-a.example.com \
  --node edge-b=edge-b.example.com \
  --xray-runtime linkray \
  --output /tmp/linkray-master
linkray validate --path /tmp/linkray-master
```

Render node files:

```bash
linkray render node --domain edge-b.example.com --output /tmp/linkray-node
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

Override experimental runtime ports when needed:

```bash
linkray render master \
  --domain edge-a.example.com \
  --singbox-inbound hysteria2=29080 \
  --snell-inbound snell=29180 \
  --output /tmp/linkray-master
```

## Command Map

| Command | Purpose |
|---|---|
| `linkray render master` | Render master deployment files |
| `linkray render node` | Render host LinkRay Node, Xray-core, sing-box, and Snell node files |
| `linkray validate --path <dir>` | Validate a rendered tree |
| `linkray install master` | Copy rendered master files into a root, dry-run by default |
| `linkray install node` | Copy rendered node files into a root, dry-run by default |
| `linkray bootstrap master` | Configure a fresh master end to end |
| `linkray bootstrap node` | Configure a fresh node end to end |
| `linkray doctor --role master` | Check master files and runtime health |
| `linkray doctor --role node` | Check node files and runtime health |
| `linkray api` | Serve node status JSON for the dashboard patch |
| `linkray egern` | Convert LinkRay subscriptions into Egern YAML |
| `linkray shadowrocket` | Convert LinkRay subscriptions into Shadowrocket config |
| `linkray sing-box` | Convert LinkRay subscriptions into compact sing-box JSON |
| `linkray sub-auto` | Route the base subscription URL to the best identifiable format |
| `linkray relay` | Expose master-side relay ports for secondary nodes |
| `linkray rules update` | Refresh CN domain and IP CIDR routing rule files |
| `linkray protocols` | Show supported and planned protocol capability status |

## Subscription Routes

| Route | Output |
|---|---|
| `/sub/<token>` | Automatic format routing for identifiable clients |
| `/sub/<token>/egern` | Egern-specific proxy resource |
| `/sub/<token>/shadowrocket` | Shadowrocket config with LinkRay route rules and Snell support |
| `/sub/<token>/shadowrocket-conf` | Backward-compatible alias for `/shadowrocket` |
| `/sub/<token>/sing-box` | LinkRay-generated sing-box JSON |
| `/linkray/ports.html` | Compatibility redirect to `/dashboard/` |
| `/linkray/ports.json` | Proxy to `/api/linkray/nodes` |

## Sidecar Services

Rendered master deployments include these LinkRay-managed systemd units:

| Unit | Purpose |
|---|---|
| `linkray-xray.service` | Optional Xray-core runtime when rendered with `--xray-runtime linkray` |
| `linkray-snell-runtime.service` | Runs the experimental Snell server runtime |
| `linkray-snell@.service` | Runs per-user Snell server instances generated by subscription adapters |
| `linkray-snell-usage.service` | Exposes per-user Snell traffic deltas to LinkRay |
| `linkray-api.service` | Reports node port status |
| `linkray-clash.service` | Converts LinkRay subscriptions into Clash/Mihomo YAML |
| `linkray-egern.service` | Converts LinkRay subscriptions into Egern YAML |
| `linkray-shadowrocket.service` | Converts LinkRay subscriptions into Shadowrocket config |
| `linkray-singbox.service` | Converts LinkRay subscriptions into compact sing-box JSON |
| `linkray-sub-auto.service` | Routes base subscription URLs by client headers |
| `linkray-rules-update.service` | Refreshes route rule files |
| `linkray-rules-update.timer` | Schedules route rule refreshes |
| `linkray-relay.service` | Relays secondary-node ports from the master |

For a two-node topology, LinkRay publishes secondary nodes through master relay ports by default. The first secondary node uses each inbound port plus `100` for its public subscription port, while TLS SNI and WebSocket Host still point at the real secondary-node domain.

## Dashboard Patch Maintenance

Runtime installs use the compiled compatibility snapshot in:

```text
patches/marzban-dashboard/current/
```

For upstream dashboard upgrades, LinkRay also ships a source-level patch in:

```text
patches/marzban-dashboard/source/linkray-dashboard.patch
```

Apply that patch to a compatible upstream source checkout, rebuild `app/dashboard`, then refresh the compatibility snapshot only after validating the LinkRay subscription dialog and Node Info panel.

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

Do not hand-edit live LinkRay panel container files as the primary workflow. Export known-good changes into this repo, render files from LinkRay, validate them, then deploy those rendered files.

The current dashboard patch under `patches/marzban-dashboard/current/` is a compatibility snapshot from an upstream dashboard build. It should eventually be replaced by a source-level dashboard patch against a pinned upstream version.

## LinkRay Host SQL

`render master` and `install master` generate:

```text
var/lib/marzban/linkray/hosts.sql
var/lib/marzban/linkray/linkray-manifest.json
```

The SQL initializes internal `inbounds` and `hosts` rows for the selected nodes. The manifest records render time, git commit, selected nodes, and non-secret config parameters for later `linkray doctor` checks. Review the SQL before applying:

```bash
sqlite3 /var/lib/marzban/db.sqlite3 < /var/lib/marzban/linkray/hosts.sql
```

For a two-node topology, the SQL creates 24 host rows: 2 nodes times 12 protocol entries.

## Repository Layout

```text
linkray/                                  # Python CLI and deployment renderer
linkray/assets/                           # packaged templates and dashboard patches
templates/                                # source deployment templates
patches/                                  # source dashboard patch snapshots
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
