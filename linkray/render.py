from __future__ import annotations

import json
import shutil
import shlex
from collections.abc import Sequence
from pathlib import Path

from .config import DEFAULT_PORTS, RELAY_PORT_OFFSET, LinkRayConfig, NodeHost, RenderResult, relay_port
from .rules import BUILTIN_CN_DOMAIN_SUFFIXES, BUILTIN_CN_IP_CIDRS, RouteRules, write_route_rules


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = Path(__file__).resolve().parent
DASHBOARD_PATCH_JS = "index.linkray.js"


def first_existing_path(*paths: Path) -> Path:
    for path in paths:
        if path.exists():
            return path
    return paths[0]


TEMPLATE_ROOT = first_existing_path(PROJECT_ROOT / "templates", PACKAGE_ROOT / "assets/templates")
PATCH_ROOT = first_existing_path(PROJECT_ROOT / "patches", PACKAGE_ROOT / "assets/patches")


def tls_stream(config: LinkRayConfig) -> dict:
    return {
        "network": "tcp",
        "security": "tls",
        "tlsSettings": {
            "serverName": config.domain,
            "minVersion": "1.2",
            "certificates": [
                {
                    "certificateFile": config.cert_file,
                    "keyFile": config.key_file,
                }
            ],
        },
    }


def ws_tls_stream(config: LinkRayConfig, path: str) -> dict:
    stream = tls_stream(config)
    stream["network"] = "ws"
    stream["wsSettings"] = {"path": path}
    return stream


def grpc_tls_stream(config: LinkRayConfig, service_name: str) -> dict:
    stream = tls_stream(config)
    stream["network"] = "grpc"
    stream["grpcSettings"] = {
        "serviceName": service_name,
        "multiMode": False,
    }
    return stream


def httpupgrade_tls_stream(config: LinkRayConfig, path: str) -> dict:
    stream = tls_stream(config)
    stream["network"] = "httpupgrade"
    stream["httpupgradeSettings"] = {"path": path}
    return stream


def reality_stream(config: LinkRayConfig, network: str = "tcp") -> dict:
    stream = {
        "network": network,
        "security": "reality",
        "realitySettings": {
            "show": False,
            "dest": config.reality_dest,
            "xver": 0,
            "serverNames": [config.reality_server_name],
            "privateKey": config.reality_private_key,
            "shortIds": [config.reality_short_id],
        },
    }
    if network == "grpc":
        stream["grpcSettings"] = {
            "serviceName": config.grpc_service_name,
            "multiMode": False,
        }
    return stream


def xhttp_reality_stream(config: LinkRayConfig, path: str) -> dict:
    stream = reality_stream(config, network="xhttp")
    stream["xhttpSettings"] = {
        "path": path,
        "mode": "auto",
    }
    return stream


def xray_config(config: LinkRayConfig) -> dict:
    config.validate()
    ports = config.port_map()
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "VLESS TCP TLS",
                "listen": "0.0.0.0",
                "port": ports["vless_tls"],
                "protocol": "vless",
                "settings": {"clients": [], "decryption": "none"},
                "streamSettings": tls_stream(config),
            },
            {
                "tag": "VLESS TCP REALITY",
                "listen": "0.0.0.0",
                "port": ports["vless_reality"],
                "protocol": "vless",
                "settings": {"clients": [], "decryption": "none"},
                "streamSettings": reality_stream(config),
            },
            {
                "tag": "VLESS GRPC REALITY",
                "listen": "0.0.0.0",
                "port": ports["vless_grpc_reality"],
                "protocol": "vless",
                "settings": {"clients": [], "decryption": "none"},
                "streamSettings": reality_stream(config, network="grpc"),
            },
            {
                "tag": "Trojan TCP TLS",
                "listen": "0.0.0.0",
                "port": ports["trojan_tls"],
                "protocol": "trojan",
                "settings": {"clients": []},
                "streamSettings": tls_stream(config),
            },
            {
                "tag": "VMess TCP TLS",
                "listen": "0.0.0.0",
                "port": ports["vmess_tls"],
                "protocol": "vmess",
                "settings": {"clients": []},
                "streamSettings": tls_stream(config),
            },
            {
                "tag": "Shadowsocks TCP UDP",
                "listen": "0.0.0.0",
                "port": ports["shadowsocks"],
                "protocol": "shadowsocks",
                "settings": {"clients": [], "network": "tcp,udp"},
            },
            {
                "tag": "VLESS WS TLS",
                "listen": "0.0.0.0",
                "port": ports["vless_ws_tls"],
                "protocol": "vless",
                "settings": {"clients": [], "decryption": "none"},
                "streamSettings": ws_tls_stream(config, "/vless-ws"),
            },
            {
                "tag": "VLESS GRPC TLS",
                "listen": "0.0.0.0",
                "port": ports["vless_grpc_tls"],
                "protocol": "vless",
                "settings": {"clients": [], "decryption": "none"},
                "streamSettings": grpc_tls_stream(config, config.grpc_service_name),
            },
            {
                "tag": "VLESS XHTTP REALITY",
                "listen": "0.0.0.0",
                "port": ports["vless_xhttp_reality"],
                "protocol": "vless",
                "settings": {"clients": [], "decryption": "none"},
                "streamSettings": xhttp_reality_stream(config, "/vless-xhttp"),
            },
            {
                "tag": "VMess WS TLS",
                "listen": "0.0.0.0",
                "port": ports["vmess_ws_tls"],
                "protocol": "vmess",
                "settings": {"clients": []},
                "streamSettings": ws_tls_stream(config, "/vmess-ws"),
            },
            {
                "tag": "VMess HTTPUpgrade TLS",
                "listen": "0.0.0.0",
                "port": ports["vmess_httpupgrade_tls"],
                "protocol": "vmess",
                "settings": {"clients": []},
                "streamSettings": httpupgrade_tls_stream(config, "/vmess-httpupgrade"),
            },
            {
                "tag": "Trojan GRPC TLS",
                "listen": "0.0.0.0",
                "port": ports["trojan_grpc_tls"],
                "protocol": "trojan",
                "settings": {"clients": []},
                "streamSettings": grpc_tls_stream(config, "trojan-grpc"),
            },
        ],
        "outbounds": [
            {"protocol": "freedom", "tag": "direct"},
            {"protocol": "blackhole", "tag": "blocked"},
        ],
        "routing": {
            "rules": [
                {"type": "field", "ip": ["geoip:private"], "outboundTag": "blocked"}
            ]
        },
    }


def master_compose() -> str:
    return f"""services:
  marzban:
    image: gozargah/marzban:latest
    restart: always
    env_file: .env
    network_mode: host
    volumes:
      - /var/lib/marzban:/var/lib/marzban
      - /var/lib/marzban/linkray/bin/xray:/usr/local/bin/xray:ro
      - /var/lib/marzban/linkray/patches/clash.py:/code/app/subscription/clash.py:ro
      - /var/lib/marzban/dashboard-patches/index.html:/code/app/dashboard/build/index.html:ro
      - /var/lib/marzban/dashboard-patches/{DASHBOARD_PATCH_JS}:/code/app/dashboard/build/statics/{DASHBOARD_PATCH_JS}:ro
      - /var/lib/marzban/dashboard-patches/index.original.js:/code/app/dashboard/build/statics/index.a1cce931.js:ro
"""


def node_compose() -> str:
    return """services:
  marzban-node:
    image: gozargah/marzban-node:latest
    restart: always
    network_mode: host
    environment:
      SSL_CLIENT_CERT_FILE: "/var/lib/marzban-node/ssl_client_cert.pem"
      SERVICE_PROTOCOL: "rest"
    volumes:
      - /var/lib/marzban-node:/var/lib/marzban-node
      - /var/lib/marzban:/var/lib/marzban
"""


def nginx_panel(config: LinkRayConfig) -> str:
    return f"""server {{
    listen {config.panel_port} ssl;
    listen [::]:{config.panel_port} ssl;
    http2 on;
    server_name {config.domain};

    ssl_certificate {config.cert_file};
    ssl_certificate_key {config.key_file};

    location = /statics/{DASHBOARD_PATCH_JS} {{
        alias /var/lib/marzban/dashboard-patches/{DASHBOARD_PATCH_JS};
        default_type application/javascript;
        add_header Cache-Control "no-store";
    }}

    location = /statics/index.a1cce931.js {{
        alias /var/lib/marzban/dashboard-patches/index.original.js;
        default_type application/javascript;
        add_header Cache-Control "no-store";
    }}

    location ~ ^/sub/[^/]+/?$ {{
        proxy_pass http://127.0.0.1:61993;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header User-Agent $http_user_agent;
        proxy_set_header Accept $http_accept;
        proxy_set_header Accept-Language $http_accept_language;
        add_header Cache-Control "no-store";
    }}

    location ~ ^/sub/[^/]+/egern/?$ {{
        proxy_pass http://127.0.0.1:61992;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header User-Agent $http_user_agent;
        proxy_set_header Accept $http_accept;
        proxy_set_header Accept-Language $http_accept_language;
        add_header Cache-Control "no-store";
    }}

    location ~ ^/sub/[^/]+/shadowrocket/?$ {{
        proxy_pass http://127.0.0.1:61994;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header User-Agent $http_user_agent;
        proxy_set_header Accept $http_accept;
        proxy_set_header Accept-Language $http_accept_language;
        add_header Cache-Control "no-store";
    }}

    location / {{
        proxy_pass http://127.0.0.1:{config.marzban_http_port};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }}

    location /api/linkray/ {{
        proxy_pass http://127.0.0.1:61990/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        add_header Cache-Control "no-store";
    }}

    location = /linkray/ports.html {{
        return 302 /dashboard/;
    }}

    location = /linkray/ports.json {{
        proxy_pass http://127.0.0.1:61990/nodes;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        add_header Cache-Control "no-store";
    }}
}}
"""


def dotenv_value(value: str) -> str:
    return shlex.quote(value)


def marzban_env(config: LinkRayConfig) -> str:
    return "\n".join(
        [
            'UVICORN_HOST = "0.0.0.0"',
            f"UVICORN_PORT = {config.marzban_http_port}",
            f"SUDO_USERNAME = {dotenv_value(config.admin_username)}",
            f"SUDO_PASSWORD = {dotenv_value(config.admin_password)}",
            'SQLALCHEMY_DATABASE_URL = "sqlite:////var/lib/marzban/db.sqlite3"',
            f"XRAY_JSON = {dotenv_value('/var/lib/marzban/xray_config.json')}",
            f"XRAY_SUBSCRIPTION_URL_PREFIX = {dotenv_value(f'https://{config.domain}:{config.panel_port}')}",
            'CUSTOM_TEMPLATES_DIRECTORY = "/var/lib/marzban/templates"',
            'CLASH_SUBSCRIPTION_TEMPLATE = "clash/default.yml"',
            "DOCS = False",
            "",
        ]
    )


ACTIVE_INBOUND_TAGS = (
    "VLESS TCP TLS",
    "VLESS TCP REALITY",
    "VLESS GRPC REALITY",
    "Trojan TCP TLS",
    "VMess TCP TLS",
    "Shadowsocks TCP UDP",
    "VLESS WS TLS",
    "VLESS GRPC TLS",
    "VLESS XHTTP REALITY",
    "VMess WS TLS",
    "VMess HTTPUpgrade TLS",
    "Trojan GRPC TLS",
)


def default_nodes(config: LinkRayConfig) -> list[NodeHost]:
    return [NodeHost("primary", config.domain)]


def linkray_api_service(nodes: Sequence[NodeHost], config: LinkRayConfig) -> str:
    node_flags = [f"--node {shlex.quote(f'{node.name}={node.domain}')}" for node in nodes]
    inbound_flags = [f"--inbound {shlex.quote(f'{key}={port}')}" for key, port in config.inbound_ports]
    flags = " ".join([*node_flags, *inbound_flags])
    return f"""[Unit]
Description=LinkRay node status API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/linkray api --listen 127.0.0.1 --port 61990 {flags}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""


def linkray_egern_service(config: LinkRayConfig) -> str:
    return f"""[Unit]
Description=LinkRay Egern subscription adapter
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/linkray egern --listen 127.0.0.1 --port 61992 --marzban-url http://127.0.0.1:{config.marzban_http_port}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""


def linkray_shadowrocket_service(config: LinkRayConfig) -> str:
    return f"""[Unit]
Description=LinkRay Shadowrocket subscription adapter
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/linkray shadowrocket --listen 127.0.0.1 --port 61994 --marzban-url http://127.0.0.1:{config.marzban_http_port}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""


def linkray_sub_auto_service(config: LinkRayConfig) -> str:
    return f"""[Unit]
Description=LinkRay automatic subscription format router
After=network-online.target linkray-egern.service linkray-shadowrocket.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/linkray sub-auto --listen 127.0.0.1 --port 61993 --marzban-url http://127.0.0.1:{config.marzban_http_port} --egern-url http://127.0.0.1:61992 --shadowrocket-url http://127.0.0.1:61994
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""


def linkray_rules_update_service() -> str:
    return """[Unit]
Description=LinkRay CN route rule updater
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/linkray rules update --output /var/lib/marzban/linkray/rules
"""


def linkray_rules_update_timer() -> str:
    return """[Unit]
Description=Refresh LinkRay CN route rules daily

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
"""


def linkray_relay_service(nodes: Sequence[NodeHost], config: LinkRayConfig) -> str:
    relay_nodes = list(nodes[1:])
    node_flags = [
        f"--node {shlex.quote(f'{node.name}={node.domain}:{RELAY_PORT_OFFSET}')}"
        for node in relay_nodes
    ]
    inbound_flags = [f"--inbound {shlex.quote(f'{key}={port}')}" for key, port in config.inbound_ports]
    flags = " ".join([*node_flags, *inbound_flags])
    return f"""[Unit]
Description=LinkRay TCP relay for secondary nodes
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/linkray relay --listen 0.0.0.0 {flags}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""


def sql_string(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def host_rows(config: LinkRayConfig, nodes: Sequence[NodeHost]) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    ports = config.port_map()
    for node_index, node in enumerate(nodes):
        node.validate()
        address = node.domain if node_index == 0 else config.domain
        def public_port(key: str) -> int:
            return relay_port(ports[key], node_index)
        rows.extend(
            [
                (
                    f"{node.name}-VLESS_TLS_Vision",
                    address,
                    public_port("vless_tls"),
                    "VLESS TCP TLS",
                    node.domain,
                    None,
                    "inbound_default",
                    "none",
                    "chrome",
                    0,
                    0,
                    None,
                    0,
                    None,
                    0,
                    None,
                    0,
                ),
                (
                    f"{node.name}-VLESS_Reality_Vision",
                    address,
                    public_port("vless_reality"),
                    "VLESS TCP REALITY",
                    config.reality_server_name,
                    None,
                    "inbound_default",
                    "none",
                    "chrome",
                    0,
                    0,
                    None,
                    0,
                    None,
                    0,
                    None,
                    0,
                ),
                (
                    f"{node.name}-VLESS_Reality_gRPC",
                    address,
                    public_port("vless_grpc_reality"),
                    "VLESS GRPC REALITY",
                    config.reality_server_name,
                    None,
                    "inbound_default",
                    "none",
                    "chrome",
                    0,
                    0,
                    None,
                    0,
                    None,
                    0,
                    None,
                    0,
                ),
                (
                    f"{node.name}-Trojan_TLS",
                    address,
                    public_port("trojan_tls"),
                    "Trojan TCP TLS",
                    node.domain,
                    None,
                    "inbound_default",
                    "none",
                    "chrome",
                    0,
                    0,
                    None,
                    0,
                    None,
                    0,
                    None,
                    0,
                ),
                (
                    f"{node.name}-VMess_TLS",
                    address,
                    public_port("vmess_tls"),
                    "VMess TCP TLS",
                    node.domain,
                    None,
                    "inbound_default",
                    "none",
                    "chrome",
                    0,
                    0,
                    None,
                    0,
                    None,
                    0,
                    None,
                    0,
                ),
                (
                    f"{node.name}-Shadowsocks",
                    address,
                    public_port("shadowsocks"),
                    "Shadowsocks TCP UDP",
                    None,
                    None,
                    "inbound_default",
                    "none",
                    "none",
                    0,
                    0,
                    None,
                    0,
                    None,
                    0,
                    None,
                    0,
                ),
                (
                    f"{node.name}-VLESS_WS_TLS",
                    address,
                    public_port("vless_ws_tls"),
                    "VLESS WS TLS",
                    node.domain,
                    node.domain,
                    "inbound_default",
                    "none",
                    "chrome",
                    0,
                    0,
                    "/vless-ws",
                    0,
                    None,
                    0,
                    None,
                    0,
                ),
                (
                    f"{node.name}-VLESS_gRPC_TLS",
                    address,
                    public_port("vless_grpc_tls"),
                    "VLESS GRPC TLS",
                    node.domain,
                    None,
                    "inbound_default",
                    "none",
                    "chrome",
                    0,
                    0,
                    config.grpc_service_name,
                    0,
                    None,
                    0,
                    None,
                    0,
                ),
                (
                    f"{node.name}-VLESS_XHTTP_Reality",
                    address,
                    public_port("vless_xhttp_reality"),
                    "VLESS XHTTP REALITY",
                    config.reality_server_name,
                    None,
                    "inbound_default",
                    "none",
                    "chrome",
                    0,
                    0,
                    "/vless-xhttp",
                    0,
                    None,
                    0,
                    None,
                    0,
                ),
                (
                    f"{node.name}-VMess_WS_TLS",
                    address,
                    public_port("vmess_ws_tls"),
                    "VMess WS TLS",
                    node.domain,
                    node.domain,
                    "inbound_default",
                    "none",
                    "chrome",
                    0,
                    0,
                    "/vmess-ws",
                    0,
                    None,
                    0,
                    None,
                    0,
                ),
                (
                    f"{node.name}-VMess_HTTPUpgrade_TLS",
                    address,
                    public_port("vmess_httpupgrade_tls"),
                    "VMess HTTPUpgrade TLS",
                    node.domain,
                    node.domain,
                    "inbound_default",
                    "none",
                    "chrome",
                    0,
                    0,
                    "/vmess-httpupgrade",
                    0,
                    None,
                    0,
                    None,
                    0,
                ),
                (
                    f"{node.name}-Trojan_gRPC_TLS",
                    address,
                    public_port("trojan_grpc_tls"),
                    "Trojan GRPC TLS",
                    node.domain,
                    None,
                    "inbound_default",
                    "none",
                    "chrome",
                    0,
                    0,
                    "trojan-grpc",
                    0,
                    None,
                    0,
                    None,
                    0,
                ),
            ]
        )
    return rows


def hosts_sql(config: LinkRayConfig, nodes: Sequence[NodeHost]) -> str:
    columns = (
        "remark",
        "address",
        "port",
        "inbound_tag",
        "sni",
        "host",
        "security",
        "alpn",
        "fingerprint",
        "allowinsecure",
        "is_disabled",
        "path",
        "mux_enable",
        "fragment_setting",
        "random_user_agent",
        "noise_setting",
        "use_sni_as_host",
    )
    lines = [
        "BEGIN;",
        "-- LinkRay-managed inbounds and hosts. Review before applying to /var/lib/marzban/db.sqlite3.",
    ]
    for tag in ACTIVE_INBOUND_TAGS:
        lines.append(f"INSERT OR IGNORE INTO inbounds(tag) VALUES ({sql_string(tag)});")
    tags = ", ".join(sql_string(tag) for tag in ACTIVE_INBOUND_TAGS)
    lines.append(f"DELETE FROM hosts WHERE inbound_tag IN ({tags});")
    column_list = ", ".join(columns)
    for row in host_rows(config, nodes):
        values = ", ".join(sql_string(item) for item in row)
        lines.append(f"INSERT INTO hosts({column_list}) VALUES ({values});")
    lines.append("COMMIT;")
    lines.append("")
    return "\n".join(lines)


def write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def copy_file(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def render_master(
    config: LinkRayConfig,
    output: Path,
    nodes: Sequence[NodeHost] | None = None,
) -> RenderResult:
    effective_nodes = list(nodes) if nodes else default_nodes(config)
    write_route_rules(
        output / "var/lib/marzban/linkray/rules",
        RouteRules(
            cn_domain_suffixes=list(BUILTIN_CN_DOMAIN_SUFFIXES),
            cn_ip_cidrs=list(BUILTIN_CN_IP_CIDRS),
        ),
    )
    files = [
        write_text(output / "var/lib/marzban/xray_config.json", json.dumps(xray_config(config), indent=2) + "\n"),
        write_text(output / "opt/marzban/.env", marzban_env(config)),
        write_text(output / "opt/marzban/docker-compose.yml", master_compose()),
        write_text(output / "etc/nginx/conf.d/marzban-panel.conf", nginx_panel(config)),
        write_text(output / "etc/systemd/system/linkray-api.service", linkray_api_service(effective_nodes, config)),
        write_text(output / "etc/systemd/system/linkray-egern.service", linkray_egern_service(config)),
        write_text(output / "etc/systemd/system/linkray-shadowrocket.service", linkray_shadowrocket_service(config)),
        write_text(output / "etc/systemd/system/linkray-sub-auto.service", linkray_sub_auto_service(config)),
        write_text(output / "etc/systemd/system/linkray-rules-update.service", linkray_rules_update_service()),
        write_text(output / "etc/systemd/system/linkray-rules-update.timer", linkray_rules_update_timer()),
        write_text(output / "etc/systemd/system/linkray-relay.service", linkray_relay_service(effective_nodes, config)),
        write_text(output / "var/lib/marzban/linkray/hosts.sql", hosts_sql(config, effective_nodes)),
        output / "var/lib/marzban/linkray/rules/cn-domains.txt",
        output / "var/lib/marzban/linkray/rules/cn-ip-cidrs.txt",
        copy_file(TEMPLATE_ROOT / "marzban/clash/default.yml", output / "var/lib/marzban/templates/clash/default.yml"),
        copy_file(PATCH_ROOT / "marzban-subscription/current/clash.py", output / "var/lib/marzban/linkray/patches/clash.py"),
        copy_file(
            PATCH_ROOT / "marzban-subscription-page/current/index.html",
            output / "var/lib/marzban/templates/subscription/index.html",
        ),
        copy_file(PATCH_ROOT / "marzban-dashboard/current/index.html", output / "var/lib/marzban/dashboard-patches/index.html"),
        copy_file(PATCH_ROOT / "marzban-dashboard/current/index.linkray.js", output / f"var/lib/marzban/dashboard-patches/{DASHBOARD_PATCH_JS}"),
        copy_file(PATCH_ROOT / "marzban-dashboard/current/index.original.js", output / "var/lib/marzban/dashboard-patches/index.original.js"),
    ]
    return RenderResult(output=output, files=tuple(files))


def render_node(output: Path) -> RenderResult:
    files = [write_text(output / "opt/marzban-node/docker-compose.yml", node_compose())]
    return RenderResult(output=output, files=tuple(files))


def validate_rendered(path: Path) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        return [f"{path} does not exist"]
    xray_path = path / "var/lib/marzban/xray_config.json"
    if xray_path.exists():
        try:
            data = json.loads(xray_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{xray_path}: invalid JSON: {exc}")
        else:
            inbounds = data.get("inbounds", [])
            ports = {item.get("port") for item in inbounds}
            expected_count = len(DEFAULT_PORTS)
            if len(inbounds) != expected_count or len(ports) != expected_count:
                errors.append(f"{xray_path}: expected {expected_count} unique inbound ports, got {sorted(ports)}")
    hosts_sql_path = path / "var/lib/marzban/linkray/hosts.sql"
    if xray_path.exists() and not hosts_sql_path.exists():
        errors.append(f"{path}: missing var/lib/marzban/linkray/hosts.sql")
    service_paths = [
        path / "etc/systemd/system/linkray-api.service",
        path / "etc/systemd/system/linkray-egern.service",
        path / "etc/systemd/system/linkray-shadowrocket.service",
        path / "etc/systemd/system/linkray-sub-auto.service",
        path / "etc/systemd/system/linkray-rules-update.service",
        path / "etc/systemd/system/linkray-rules-update.timer",
    ]
    if (path / "opt/marzban/docker-compose.yml").exists():
        for service_path in service_paths:
            if not service_path.exists():
                errors.append(f"{path}: missing {service_path.relative_to(path)}")
    clash_patch_path = path / "var/lib/marzban/linkray/patches/clash.py"
    if (path / "opt/marzban/docker-compose.yml").exists() and not clash_patch_path.exists():
        errors.append(f"{path}: missing var/lib/marzban/linkray/patches/clash.py")
    required_any = [
        path / "opt/marzban/docker-compose.yml",
        path / "opt/marzban-node/docker-compose.yml",
    ]
    if not any(item.exists() for item in required_any):
        errors.append(f"{path}: missing master or node docker-compose.yml")
    return errors
