<div align="center">
  <h1>LinkRay</h1>
  <p><b>Multi-node proxy operations with a LinkRay control plane, Xray-core, sing-box, Snell, unified subscriptions, traffic accounting, and repeatable deployment.</b></p>
  <a href="https://github.com/Zanetach/LinkRay/stargazers"><img src="https://img.shields.io/github/stars/Zanetach/LinkRay?style=flat-square" alt="Stars"></a>
  <a href="https://github.com/Zanetach/LinkRay/releases"><img src="https://img.shields.io/github/v/tag/Zanetach/LinkRay?label=version&style=flat-square" alt="Version"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/python-3.9%2B-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python 3.9+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square" alt="License"></a>
</div>

![LinkRay README hero](assets/linkray-readme-hero.png)

## What LinkRay Is

LinkRay is a deployment and operations layer for running a multi-node proxy service from a single panel and subscription surface. It reuses the Marzban API and data model internally, but the user-facing product, dashboard patches, subscription adapters, node status API, runtime services, traffic sync jobs, and deployment flow are managed by LinkRay.

The production goal is explicit:

- Keep user, subscription, traffic, and node management in one panel.
- Run Xray-core as the primary runtime.
- Add sing-box and Snell as LinkRay-managed advanced runtimes.
- Provide one user subscription surface across master and node servers.
- Make deployment reproducible through rendered files, bootstrap commands, release artifacts, and `linkray doctor`.
- Avoid hand-editing live container files as the normal workflow.

## Latest Release

Current release: [LinkRay v0.2.0](https://github.com/Zanetach/LinkRay/releases/tag/v0.2.0)

Release artifacts:

```text
linkray-0.2.0.tar.gz
linkray-0.2.0-py3-none-any.whl
```

v0.2.0 is the first stable deployment release. A fresh environment can be brought to a usable LinkRay service with the release tarball, `linkray bootstrap master --apply`, and, for extra servers, `linkray bootstrap node --apply`. The release includes LinkRay branding, the dashboard subscription dialog, Node Info, Xray-core host runtimes, sing-box advanced runtime, Snell runtime, local MetaCubeX rule assets, traffic sidecars, and BBR/fq network acceleration.

## Architecture

```text
                         clients
       Clash/Mihomo | sing-box | Egern | Shadowrocket | native links
                            |
                            v
                  https://<master>:9443/sub/<token>
                            |
                            v
              +-----------------------------+
              | LinkRay master              |
              |                             |
              | Docker: LinkRay panel       |
              | Host: Nginx                 |
              | Host: subscription/API sidecars |
              | Host: usage accounting sidecars |
              | Host: Xray-core runtime     |
              | Host: sing-box runtime      |
              | Host: Snell runtime         |
              | Host: TCP relay service     |
              +--------------+--------------+
                             |
                 node API / relay / shared users
                             |
              +--------------v--------------+
              | LinkRay node                |
              |                             |
              | No Docker                   |
              | Host: linkray-node          |
              | Host: Xray-core runtime     |
              | Host: sing-box runtime      |
              | Host: Snell runtime         |
              | Host: usage accounting sidecars |
              +-----------------------------+
```

### Role Boundary

| Role | Runs Docker | Runs panel | Runtime shape |
|---|---:|---:|---|
| `master` | Yes | Yes | LinkRay panel container plus host sidecars and runtimes |
| `node` | No | No | Host-native systemd services only |

This boundary is part of the packaging contract:

- `linkray bootstrap master` may install Docker and start `container_name: linkray`.
- `linkray bootstrap node` must not install Docker and must not start a node container.
- `scripts/deploy-rendered-master.sh` may run Docker Compose.
- `scripts/deploy-rendered-node.sh` may clean up old legacy node containers, but it must not install Docker or run Docker Compose.

## What LinkRay Owns

| Surface | Current capability |
|---|---|
| Control plane | LinkRay-branded panel on top of the Marzban API and database model |
| User lifecycle | Users, subscription links, usage limits, expiry, online state, and traffic accounting |
| Master deployment | Docker Compose for the panel, Nginx, dashboard patches, templates, SQL host initialization, systemd sidecars |
| Node deployment | Host-native LinkRay Node app, Xray-core, sing-box, Snell, and usage services |
| Xray-core | 12 inbound families per node, rendered with overridable ports |
| sing-box | Hysteria2, TUIC, AnyTLS runtime, generated user credentials, V2Ray API stats sync |
| Snell | Snell v5 runtime, per-user credentials, Shadowrocket output, usage sync |
| Subscriptions | Native, automatic routing, Clash/Mihomo, Egern, Shadowrocket, sing-box |
| Routing rules | Built-in CN direct rules, foreign service rules, rule refresh timer |
| Dashboard | Subscription dialog, protocol cards, Node Info panel, LinkRay branding |
| Node status | `/api/linkray/nodes`, 30-second dashboard refresh, manual refresh endpoint |
| Multi-node access | Master-side relay ports for secondary nodes |
| Health checks | `linkray doctor` file, manifest, systemd, container, process, port, and tuning checks |
| Network tuning | BBR/fq, MTU probing, TCP Fast Open, slow-start-after-idle disabled |

## Protocol Coverage

Every rendered node has these 12 Xray-core inbound families:

| Protocol | Runtime | Transport | Security | Notes |
|---|---|---|---|---|
| VLESS TLS Vision | Xray-core | TCP | TLS | Stable primary path |
| VLESS Reality Vision | Xray-core | TCP | Reality | Stable where clients support Reality |
| VLESS Reality gRPC | Xray-core | gRPC | Reality | Supported by compatible clients |
| Trojan TLS | Xray-core | TCP | TLS | Stable primary path |
| VMess TLS | Xray-core | TCP | TLS | Compatibility path |
| Shadowsocks | Xray-core | TCP / UDP | none | Compatibility path |
| VLESS WS TLS | Xray-core | WebSocket | TLS | CDN/client compatibility path |
| VLESS gRPC TLS | Xray-core | gRPC | TLS | gRPC compatibility path |
| VLESS XHTTP Reality | Xray-core | XHTTP | Reality | Rendered; some clients still have unstable delay tests |
| VMess WS TLS | Xray-core | WebSocket | TLS | Compatibility path |
| VMess HTTPUpgrade TLS | Xray-core | HTTPUpgrade | TLS | Compatibility path |
| Trojan gRPC TLS | Xray-core | gRPC | TLS | gRPC compatibility path |

Advanced LinkRay runtimes:

| Protocol | Runtime | Status | Subscription format |
|---|---|---|---|
| Hysteria2 | sing-box | experimental | sing-box |
| TUIC | sing-box | experimental | sing-box |
| AnyTLS | sing-box | experimental | sing-box |
| Snell v5 | Snell | experimental | Shadowrocket config |

Clash/Mihomo output deliberately excludes Snell v5 because common Mihomo cores reject `version: 5`. Use the `/shadowrocket-conf` full configuration path for Snell-capable Shadowrocket imports.

### Client Subscription Matrix

LinkRay separates server protocol inventory from client-compatible subscription output. A two-server deployment has 32 open server entries in Node Info: 12 Xray-core entries, 3 sing-box entries, and 1 Snell entry per server. Client subscriptions intentionally expose only the entries that the target client can import reliably.

| Client route | Stable output shape |
|---|---|
| `/sub/<token>` | Automatic client detection; falls back to native/base output |
| `/sub/<token>/clash-meta` | Stable Xray-core Clash/Mihomo YAML; filters timeout-prone relay or advanced entries |
| `/sub/<token>/clash-meta-full` | Full Xray-core Clash/Mihomo YAML for diagnostics; may include CA/LA and advanced entries that some clients cannot test reliably |
| `/sub/<token>/egern` | Egern-compatible Xray subset, including Reality where Egern supports it |
| `/sub/<token>/shadowrocket` | Shadowrocket node subscription for ordinary imports |
| `/sub/<token>/shadowrocket-conf` | Full Shadowrocket config with routing rules and Snell support |
| `/sub/<token>/sing-box` | sing-box JSON with Hysteria2, TUIC, AnyTLS, and supported Xray outbounds |

This is why a client may show fewer nodes than the Node Info panel. The dashboard reports server-side port availability; the subscription route reports the client-safe subset.

Check the generated capability matrix:

```bash
linkray protocols
linkray protocols --json
```

## Subscription Routes

| Route | Output |
|---|---|
| `/sub/<token>` | Automatic format routing for identifiable clients |
| `/sub/<token>/clash-meta` | LinkRay-generated stable Clash/Mihomo YAML |
| `/sub/<token>/clash-meta-full` | LinkRay-generated full Clash/Mihomo YAML for diagnostics |
| `/sub/<token>/egern` | Egern YAML |
| `/sub/<token>/shadowrocket` | Shadowrocket node subscription for normal subscription imports |
| `/sub/<token>/shadowrocket-conf` | Full Shadowrocket configuration with route rules and Snell support |
| `/sub/<token>/sing-box` | LinkRay-generated sing-box JSON with advanced outbounds |
| `/sub/<token>/v2ray-json` | v2ray JSON path from the underlying subscription layer when available |
| `/linkray/ports.html` | Compatibility redirect to `/dashboard/` |
| `/linkray/ports.json` | Proxy to `/api/linkray/nodes` |
| `/linkray/rules/` | Locally cached MetaCubeX rule assets for client subscriptions |

The dashboard link dialog is intentionally client-oriented:

- Clash/Mihomo: use for Clash Verge Rev, FlClash, Mihomo Party, and Mihomo-based clients.
- Egern: use the Egern-specific route.
- sing-box: use for sing-box clients and LinkRay advanced sing-box outbounds.
- Shadowrocket: use `/shadowrocket` for normal node subscriptions; use `/shadowrocket-conf` only when importing a full configuration.
- Native/Base subscription: use for v2rayN/v2rayNG and generic import paths.

Clash/Mihomo subscriptions protect proxy server domains from `fake-ip` DNS
pollution by adding those domains to `fake-ip-filter`, `nameserver-policy`, and,
when resolvable on the server, top-level `hosts`.

## Rule Assets

`linkray rules update` refreshes two layers of routing data:

- Compact text rules used by LinkRay's built-in Shadowrocket, Egern, Clash/Mihomo, and sing-box generators.
- Locally cached [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat) assets under `/var/lib/marzban/linkray/rules`, including `geoip.dat`, `geosite.dat`, `country.mmdb`, `GeoLite2-ASN.mmdb`, Mihomo `.mrs` rule sets, and sing-box `.srs` rule sets.

The master Nginx config exposes those cached files at `/linkray/rules/`. Clash/Mihomo subscriptions use that local URL for `geox-url` and CN `rule-providers`; sing-box subscriptions use it for remote binary `rule_set` entries. Clients no longer need to download these rule assets directly from GitHub at startup.

## Sidecar Services

Usage accounting sidecars are the small LinkRay services and jobs that collect traffic from runtimes that are not counted directly by the panel runtime path, then write those deltas back into the internal usage tables. On the master this includes the mounted `linkray_singbox_usages.py` panel job plus `linkray-snell-usage.service`. On a node this includes the host `linkray-snell-usage.service` for local Snell traffic deltas.

Rendered master deployments include these LinkRay-managed units:

| Unit | Purpose |
|---|---|
| `linkray-xray.service` | Xray-core runtime when rendered with `--xray-runtime linkray` |
| `linkray-api.service` | Node/port status API for the dashboard |
| `linkray-clash.service` | Clash/Mihomo subscription adapter |
| `linkray-egern.service` | Egern subscription adapter |
| `linkray-shadowrocket.service` | Shadowrocket subscription adapter |
| `linkray-singbox.service` | sing-box subscription adapter |
| `linkray-singbox-runtime.service` | Hysteria2, TUIC, AnyTLS runtime |
| `linkray-snell-runtime.service` | Shared Snell runtime |
| `linkray-snell@.service` | Per-user Snell instances |
| `linkray-snell-usage.service` | Snell usage deltas for LinkRay accounting |
| `linkray-sub-auto.service` | Client-aware subscription format router |
| `linkray-rules-update.service` | Route rule refresh job |
| `linkray-rules-update.timer` | Scheduled rule refresh |
| `linkray-relay.service` | Master-side relay ports for secondary nodes |

Rendered node deployments include:

| Unit | Purpose |
|---|---|
| `linkray-node.service` | Host-native LinkRay Node control service |
| `linkray-xray.service` | Host-native Xray-core runtime |
| `linkray-singbox-runtime.service` | Node sing-box advanced runtime |
| `linkray-snell-runtime.service` | Node Snell runtime |
| `linkray-snell@.service` | Node per-user Snell instances |
| `linkray-snell-usage.service` | Node Snell usage deltas |

## Network Acceleration

Fresh master and node deployments apply:

```text
net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr
net.ipv4.tcp_mtu_probing=1
net.ipv4.tcp_slow_start_after_idle=0
net.ipv4.tcp_fastopen=3
```

Files:

```text
/etc/sysctl.d/99-linkray-network.conf
/etc/modules-load.d/linkray-bbr.conf
```

Bootstrap and rendered deployment scripts also run:

```bash
modprobe tcp_bbr || true
sysctl --system
tc qdisc replace dev <default-iface> root fq
```

`linkray doctor` checks that the tuning files exist. Use system tools to verify runtime state:

```bash
sysctl net.ipv4.tcp_congestion_control net.core.default_qdisc
tc qdisc show dev "$(ip route show default | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -1)"
```

## Install LinkRay

From a release tarball:

```bash
curl -L https://github.com/Zanetach/LinkRay/releases/download/v0.2.0/linkray-0.2.0.tar.gz -o linkray-0.2.0.tar.gz
tar -xzf linkray-0.2.0.tar.gz
cd linkray-0.2.0
sudo ./install.sh
```

From a checkout:

```bash
git clone https://github.com/Zanetach/LinkRay.git
cd LinkRay
sudo ./install.sh
```

The installer writes:

```text
/opt/linkray/venv
/usr/local/bin/linkray
```

Check the CLI:

```bash
linkray --help
```

Build local release artifacts:

```bash
scripts/build-release.sh
```

The release script creates `dist/*.tar.gz` and `dist/*.whl`, installs the wheel into a temporary virtualenv, and smoke-tests `linkray --help`.

## Fresh Master Bootstrap

For a new master server, the shortest usable path is:

```bash
curl -L https://github.com/Zanetach/LinkRay/releases/download/v0.2.0/linkray-0.2.0.tar.gz -o linkray-0.2.0.tar.gz
tar -xzf linkray-0.2.0.tar.gz
cd linkray-0.2.0
sudo ./install.sh

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

After it finishes, open:

```text
https://edge-a.example.com:9443/dashboard/
```

The master bootstrap installs system packages, Docker for the panel only, host-native Xray-core, sing-box, Snell, Nginx, systemd sidecars, local rule assets, certificates when `--issue-cert` is set, network acceleration, and `linkray doctor` verification.

Run a dry-run first:

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

Apply after reviewing the output:

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

Open the dashboard:

```text
https://<master-domain>:<panel-port>/dashboard/
```

If Reality values are omitted during `--apply`, LinkRay generates them before writing `/var/lib/marzban/xray_config.json`.

By default, the master keeps the panel-compatible Xray behavior. To let LinkRay own Xray as a host systemd service on the master:

```bash
linkray bootstrap master \
  --domain edge-a.example.com \
  --node edge-a=edge-a.example.com \
  --xray-runtime linkray \
  --admin-username admin \
  --admin-password 'CHANGE_THIS_PASSWORD' \
  --apply
```

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

Or pull the certificate from a master over SSH:

```bash
linkray bootstrap node \
  --domain edge-b.example.com \
  --pull-cert-from root@edge-a.example.com \
  --remote-cert-path /var/lib/marzban/ssl_client_cert.pem \
  --apply
```

The node bootstrap installs required packages, the host LinkRay Node app, Xray-core, optional sing-box/Snell runtime files, BBR/fq tuning, and systemd services. It does not install Docker.

## Render And Deploy

Render master files:

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
linkray render node \
  --domain edge-b.example.com \
  --output /tmp/linkray-node
linkray validate --path /tmp/linkray-node
```

Deploy rendered files on prepared hosts:

```bash
sudo scripts/deploy-rendered-master.sh /tmp/linkray-master
sudo scripts/deploy-rendered-node.sh /tmp/linkray-node
```

Preview and apply file copies through the CLI:

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

`linkray install` copies rendered files only. It does not run `sqlite3`, Docker Compose, Nginx validation, or systemd restarts. Use bootstrap or deploy scripts for end-to-end host changes.

## Ports And Multi-node Relay

Default per-node public runtime ports:

| Range | Runtime |
|---|---|
| `443` | Primary Xray VLESS TCP TLS inbound for maximum client/network compatibility |
| `18081-18091` | Additional Xray-core protocol inbounds |
| `443/udp`, `8443/udp`, `8444/tcp` | sing-box Hysteria2, TUIC, AnyTLS |
| `19180` | Snell |

Multi-node subscriptions point each node at its own public domain and runtime
ports. The master hosts the panel and subscription adapters; secondary nodes do
not need Docker or the panel container.

Override Xray inbound ports:

```bash
linkray render master \
  --domain edge-a.example.com \
  --node edge-a=edge-a.example.com \
  --inbound vless_tls=28080 \
  --inbound vless_reality=28081 \
  --output /tmp/linkray-master
```

Override advanced runtime ports:

```bash
linkray render master \
  --domain edge-a.example.com \
  --singbox-inbound hysteria2=443 \
  --snell-inbound snell=29180 \
  --output /tmp/linkray-master
```

For secondary nodes, LinkRay can advertise master-side relay ports. The first secondary node uses `inbound_port + 100` by default, while TLS SNI and WebSocket Host remain the real secondary-node domain. This avoids client-side proxy chaining while still letting clients import ordinary node entries.

## Command Map

| Command | Purpose |
|---|---|
| `linkray render master` | Render master deployment files |
| `linkray render node` | Render host node files |
| `linkray validate --path <dir>` | Validate a rendered tree |
| `linkray install master` | Copy rendered master files, dry-run by default |
| `linkray install node` | Copy rendered node files, dry-run by default |
| `linkray bootstrap master` | Configure a fresh master end to end |
| `linkray bootstrap node` | Configure a fresh node end to end |
| `linkray doctor --role master` | Check master files and runtime health |
| `linkray doctor --role node` | Check node files and runtime health |
| `linkray api` | Serve node status JSON for the dashboard |
| `linkray clash` | Run the Clash/Mihomo subscription adapter |
| `linkray egern` | Run the Egern subscription adapter |
| `linkray shadowrocket` | Run the Shadowrocket subscription adapter |
| `linkray sing-box` | Run the sing-box subscription adapter |
| `linkray snell-usage` | Run the Snell usage sidecar |
| `linkray sub-auto` | Route base subscription URLs by client headers |
| `linkray relay` | Expose master-side relay ports for secondary nodes |
| `linkray rules update` | Refresh CN routing text files and MetaCubeX client rule assets |
| `linkray protocols` | Show protocol capability status |

## Verify

Run local tests:

```bash
python3 -m unittest discover -s tests -v
```

Check a rendered tree:

```bash
linkray doctor --role master --root /tmp/linkray-master --no-runtime
linkray doctor --role node --root /tmp/linkray-node --no-runtime
```

Check live servers from inside each server:

```bash
linkray doctor --role master
linkray doctor --role node
```

Check the dashboard node API:

```bash
curl -k https://<master-domain>:9443/api/linkray/nodes
```

For a two-node deployment with Xray, sing-box, and Snell enabled, the dashboard API should report 32 open entries: 16 per node.

## Dashboard Patch Maintenance

Runtime installs use the compiled compatibility snapshot in:

```text
patches/marzban-dashboard/current/
```

LinkRay also ships a source-level dashboard patch in:

```text
patches/marzban-dashboard/source/linkray-dashboard.patch
```

For upstream dashboard upgrades, apply the source-level patch to a compatible upstream checkout, rebuild `app/dashboard`, refresh the compatibility snapshot, and validate the subscription dialog plus Node Info panel before release.

## Repository Layout

```text
linkray/                                  # Python CLI, renderers, adapters, runtime helpers
linkray/assets/                           # Packaged templates, dashboard patches, node app
templates/                                # Source deployment templates
patches/                                  # Source and compatibility patch snapshots
scripts/build-release.sh                  # Build wheel and source distribution
scripts/deploy-rendered-master.sh         # Deploy rendered master tree to a prepared host
scripts/deploy-rendered-node.sh           # Deploy rendered node tree to a prepared host
docs/DEPLOYMENT.md                        # Detailed deployment guide
tests/                                    # unittest coverage for CLI, renderer, adapters, doctor, runtimes
install.sh                                # Root installer for /usr/local/bin/linkray
pyproject.toml                            # Python package metadata
```

## Production Rule

Do not hand-edit live LinkRay panel container files as the primary workflow. Export known-good changes into this repository, render files from LinkRay, validate them, then deploy the rendered files or publish a release.

## More

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for detailed deployment notes and operational commands.

## License

MIT License. See [LICENSE](LICENSE).
