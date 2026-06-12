from __future__ import annotations

import json
import shutil
import shlex
import subprocess
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from .config import DEFAULT_PORTS, LINKRAY_XRAY_API_PORT, RELAY_PORT_OFFSET, LinkRayConfig, NodeHost, RenderResult, relay_port
from .rules import BUILTIN_CN_DOMAIN_SUFFIXES, BUILTIN_CN_IP_CIDRS, RouteRules, write_route_rules
from .snell_runtime import DEFAULT_RUNTIME_DIR as SNELL_RUNTIME_DIR
from .snell_runtime import server_config_text as snell_server_config_text
from .singbox_runtime import DEFAULT_RUNTIME_DIR, server_config


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
DASHBOARD_SOURCE_PATCH_ROOT = first_existing_path(
    PROJECT_ROOT / "patches/marzban-dashboard/source",
    PACKAGE_ROOT / "assets/source-patches/marzban-dashboard",
)
NODE_APP_ROOT = first_existing_path(PROJECT_ROOT / "linkray/assets/marzban-node-host", PACKAGE_ROOT / "assets/marzban-node-host")


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


def _inbound(tag: str, port_key: str, protocol: str, stream: dict | None, ports: dict[str, int]) -> dict:
    settings: dict = {"clients": []}
    if protocol == "vless":
        settings["decryption"] = "none"
    elif protocol == "shadowsocks":
        settings["network"] = "tcp,udp"
    entry: dict = {"tag": tag, "listen": "0.0.0.0", "port": ports[port_key], "protocol": protocol, "settings": settings}
    if stream is not None:
        entry["streamSettings"] = stream
    return entry


def xray_config(config: LinkRayConfig) -> dict:
    config.validate()
    ports = config.port_map()
    inbounds = [
        _inbound("VLESS TCP TLS",        "vless_tls",             "vless",       tls_stream(config),                              ports),
        _inbound("VLESS TCP REALITY",    "vless_reality",         "vless",       reality_stream(config),                          ports),
        _inbound("VLESS GRPC REALITY",   "vless_grpc_reality",    "vless",       reality_stream(config, network="grpc"),           ports),
        _inbound("Trojan TCP TLS",       "trojan_tls",            "trojan",      tls_stream(config),                              ports),
        _inbound("VMess TCP TLS",        "vmess_tls",             "vmess",       tls_stream(config),                              ports),
        _inbound("Shadowsocks TCP UDP",  "shadowsocks",           "shadowsocks", None,                                            ports),
        _inbound("VLESS WS TLS",         "vless_ws_tls",          "vless",       ws_tls_stream(config, "/vless-ws"),              ports),
        _inbound("VLESS GRPC TLS",       "vless_grpc_tls",        "vless",       grpc_tls_stream(config, config.grpc_service_name), ports),
        _inbound("VLESS XHTTP REALITY",  "vless_xhttp_reality",   "vless",       xhttp_reality_stream(config, "/vless-xhttp"),    ports),
        _inbound("VMess WS TLS",         "vmess_ws_tls",          "vmess",       ws_tls_stream(config, "/vmess-ws"),              ports),
        _inbound("VMess HTTPUpgrade TLS","vmess_httpupgrade_tls", "vmess",       httpupgrade_tls_stream(config, "/vmess-httpupgrade"), ports),
        _inbound("Trojan GRPC TLS",      "trojan_grpc_tls",       "trojan",      grpc_tls_stream(config, "trojan-grpc"),          ports),
    ]
    return {
        "log": {"loglevel": "warning"},
        "inbounds": inbounds,
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


def merge_dicts(a: dict, b: dict) -> dict:
    for key, value in b.items():
        if isinstance(value, dict) and key in a and isinstance(a[key], dict):
            merge_dicts(a[key], value)
        else:
            a[key] = value
    return a


def xray_runtime_config(config: LinkRayConfig) -> dict:
    data = xray_config(config)
    data["api"] = {
        "services": [
            "HandlerService",
            "StatsService",
            "LoggerService",
        ],
        "tag": "API",
    }
    data["stats"] = {}
    forced_policies = {
        "levels": {
            "0": {
                "statsUserUplink": True,
                "statsUserDownlink": True,
            }
        },
        "system": {
            "statsInboundDownlink": False,
            "statsInboundUplink": False,
            "statsOutboundDownlink": True,
            "statsOutboundUplink": True,
        },
    }
    data["policy"] = merge_dicts(data.get("policy", {}), forced_policies)
    data["inbounds"].insert(
        0,
        {
            "listen": "127.0.0.1",
            "port": LINKRAY_XRAY_API_PORT,
            "protocol": "dokodemo-door",
            "settings": {
                "address": "127.0.0.1",
            },
            "tag": "API_INBOUND",
        },
    )
    data.setdefault("routing", {}).setdefault("rules", []).insert(
        0,
        {
            "inboundTag": ["API_INBOUND"],
            "outboundTag": "API",
            "type": "field",
        },
    )
    return data


def master_compose(config: LinkRayConfig) -> str:
    volumes = ["      - /var/lib/marzban:/var/lib/marzban"]
    if config.xray_runtime_mode == "marzban":
        volumes.append("      - /var/lib/marzban/linkray/bin/xray:/usr/local/bin/xray:ro")
    if config.xray_runtime_mode == "linkray":
        volumes.extend(
            [
                "      - /var/lib/marzban/linkray/patches/xray_init.py:/code/app/xray/__init__.py:ro",
                "      - /var/lib/marzban/linkray/patches/0_xray_core.py:/code/app/jobs/0_xray_core.py:ro",
            ]
        )
    volumes.extend(
        [
            "      - /var/lib/marzban/linkray/patches/clash.py:/code/app/subscription/clash.py:ro",
            "      - /var/lib/marzban/linkray/jobs/linkray_singbox_usages.py:/code/app/jobs/linkray_singbox_usages.py:ro",
            "      - /var/lib/marzban/dashboard-patches/index.html:/code/app/dashboard/build/index.html:ro",
            f"      - /var/lib/marzban/dashboard-patches/{DASHBOARD_PATCH_JS}:/code/app/dashboard/build/statics/{DASHBOARD_PATCH_JS}:ro",
            "      - /var/lib/marzban/dashboard-patches/index.original.js:/code/app/dashboard/build/statics/index.a1cce931.js:ro",
        ]
    )
    volume_block = "\n".join(volumes)
    return f"""services:
  linkray:
    image: linkray:latest
    container_name: linkray
    restart: always
    env_file: .env
    network_mode: host
    volumes:
{volume_block}
"""


def linkray_node_service() -> str:
    return """[Unit]
Description=LinkRay Node control service
After=network-online.target linkray-xray.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/linkray-node-app/current
Environment=PYTHONUNBUFFERED=1
Environment=SERVICE_HOST=0.0.0.0
Environment=SERVICE_PORT=62050
Environment=SERVICE_PROTOCOL=rest
Environment=XRAY_API_HOST=0.0.0.0
Environment=XRAY_API_PORT=62051
Environment=XRAY_EXECUTABLE_PATH=/var/lib/marzban/linkray/bin/xray
Environment=XRAY_ASSETS_PATH=/var/lib/marzban/linkray/bin
Environment=SSL_CERT_FILE=/var/lib/marzban-node/ssl_cert.pem
Environment=SSL_KEY_FILE=/var/lib/marzban-node/ssl_key.pem
Environment=SSL_CLIENT_CERT_FILE=/var/lib/marzban-node/ssl_client_cert.pem
Environment=LINKRAY_EXTERNAL_XRAY=true
Environment=LINKRAY_XRAY_RUNTIME_CONFIG=/var/lib/marzban/linkray/xray/runtime.json
Environment=LINKRAY_XRAY_SERVICE=linkray-xray
ExecStart=/opt/linkray-node-app/venv/bin/python /opt/linkray-node-app/current/main.py
Restart=always
RestartSec=3
KillSignal=SIGTERM
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
"""


def nginx_panel(config: LinkRayConfig) -> str:
    return f"""server {{
    listen {config.panel_port} ssl http2;
    listen [::]:{config.panel_port} ssl http2;
    server_name {config.domain};

    ssl_certificate {config.cert_file};
    ssl_certificate_key {config.key_file};

    location = /statics/{DASHBOARD_PATCH_JS} {{
        alias /var/lib/marzban/dashboard-patches/{DASHBOARD_PATCH_JS};
        default_type application/javascript;
        add_header Cache-Control "no-store" always;
    }}

    location = /statics/index.a1cce931.js {{
        alias /var/lib/marzban/dashboard-patches/index.original.js;
        default_type application/javascript;
        add_header Cache-Control "no-store" always;
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
        add_header Cache-Control "no-store" always;
    }}

    location ~ ^/sub/[^/]+/clash-meta/?$ {{
        proxy_pass http://127.0.0.1:61991;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header User-Agent $http_user_agent;
        proxy_set_header Accept $http_accept;
        proxy_set_header Accept-Language $http_accept_language;
        add_header Cache-Control "no-store" always;
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
        add_header Cache-Control "no-store" always;
    }}

    location ~ ^/sub/[^/]+/(shadowrocket|shadowrocket-conf)/?$ {{
        proxy_pass http://127.0.0.1:61994;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header User-Agent $http_user_agent;
        proxy_set_header Accept $http_accept;
        proxy_set_header Accept-Language $http_accept_language;
        add_header Cache-Control "no-store" always;
    }}

    location ~ ^/sub/[^/]+/sing-box/?$ {{
        proxy_pass http://127.0.0.1:61995;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header User-Agent $http_user_agent;
        proxy_set_header Accept $http_accept;
        proxy_set_header Accept-Language $http_accept_language;
        add_header Cache-Control "no-store" always;
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
        add_header Cache-Control "no-store" always;
    }}

    location /api/linkray/ {{
        proxy_pass http://127.0.0.1:61990/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        add_header Cache-Control "no-store" always;
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
        add_header Cache-Control "no-store" always;
    }}
}}
"""


def dotenv_value(value: str) -> str:
    return shlex.quote(value)


def marzban_env(config: LinkRayConfig) -> str:
    items = [
            'UVICORN_HOST = "0.0.0.0"',
            f"UVICORN_PORT = {config.marzban_http_port}",
            f"SUDO_USERNAME = {dotenv_value(config.admin_username)}",
            f"SUDO_PASSWORD = {dotenv_value(config.admin_password)}",
            'SQLALCHEMY_DATABASE_URL = "sqlite:////var/lib/marzban/db.sqlite3"',
            f"XRAY_JSON = {dotenv_value('/var/lib/marzban/xray_config.json')}",
            f"XRAY_SUBSCRIPTION_URL_PREFIX = {dotenv_value(f'https://{config.domain}:{config.panel_port}')}",
            "LINKRAY_SINGBOX_STATS_API = 127.0.0.1:61996",
            "LINKRAY_SINGBOX_SIDECAR_URL = http://127.0.0.1:61995",
            "LINKRAY_SNELL_USAGE_URL = http://127.0.0.1:61997",
            'CUSTOM_TEMPLATES_DIRECTORY = "/var/lib/marzban/templates"',
            'CLASH_SUBSCRIPTION_TEMPLATE = "clash/default.yml"',
            "DOCS = False",
            "",
        ]
    if config.xray_runtime_mode == "linkray":
        items[7:7] = [
            "LINKRAY_EXTERNAL_XRAY = True",
            f"LINKRAY_XRAY_API_PORT = {LINKRAY_XRAY_API_PORT}",
            "LINKRAY_XRAY_RUNTIME_CONFIG = /var/lib/marzban/linkray/xray/runtime.json",
        ]
    return "\n".join(items)


def current_commit() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if completed.returncode != 0:
        return "unknown"
    return completed.stdout.strip() or "unknown"


def render_manifest(config: LinkRayConfig, nodes: Sequence[NodeHost], role: str = "master") -> str:
    ports = config.port_map()
    data = {
        "version": 1,
        "role": role,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "commit": current_commit(),
        "config": {
            "domain": config.domain,
            "panel_port": config.panel_port,
            "marzban_http_port": config.marzban_http_port,
            "xray_runtime_mode": config.xray_runtime_mode,
            "cert_file": config.cert_file,
            "key_file": config.key_file,
            "grpc_service_name": config.grpc_service_name,
            "reality_server_name": config.reality_server_name,
            "reality_dest": config.reality_dest,
            "inbound_ports": ports,
            "snell_inbound_ports": config.snell_port_map(),
        },
        "nodes": [{"name": node.name, "domain": node.domain} for node in nodes],
    }
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def rendered_xray_runtime_mode(path: Path) -> str:
    manifest_path = path / "var/lib/marzban/linkray/linkray-manifest.json"
    if not manifest_path.exists():
        return "marzban"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "marzban"
    config = data.get("config")
    if not isinstance(config, dict):
        return "marzban"
    mode = config.get("xray_runtime_mode")
    return mode if mode in {"marzban", "linkray"} else "marzban"


# Per-inbound host row specification.
# Columns: remark_suffix, port_key, inbound_tag, sni_src, host_src, fingerprint, path
# sni_src/host_src: "N"=node.domain  "R"=reality_server_name  None=NULL
# path: None, a literal string, or "grpc"=config.grpc_service_name
_HOST_SPECS: tuple[tuple, ...] = (
    ("VLESS_TLS_Vision",      "vless_tls",             "VLESS TCP TLS",         "N",  None, "chrome", None),
    ("VLESS_Reality_Vision",  "vless_reality",         "VLESS TCP REALITY",     "R",  None, "chrome", None),
    ("VLESS_Reality_gRPC",    "vless_grpc_reality",    "VLESS GRPC REALITY",    "R",  None, "chrome", None),
    ("Trojan_TLS",            "trojan_tls",            "Trojan TCP TLS",        "N",  None, "chrome", None),
    ("VMess_TLS",             "vmess_tls",             "VMess TCP TLS",         "N",  None, "chrome", None),
    ("Shadowsocks",           "shadowsocks",           "Shadowsocks TCP UDP",   None, None, "none",   None),
    ("VLESS_WS_TLS",          "vless_ws_tls",          "VLESS WS TLS",          "N",  "N",  "chrome", "/vless-ws"),
    ("VLESS_gRPC_TLS",        "vless_grpc_tls",        "VLESS GRPC TLS",        "N",  None, "chrome", "grpc"),
    ("VLESS_XHTTP_Reality",   "vless_xhttp_reality",   "VLESS XHTTP REALITY",   "R",  None, "chrome", "/vless-xhttp"),
    ("VMess_WS_TLS",          "vmess_ws_tls",          "VMess WS TLS",          "N",  "N",  "chrome", "/vmess-ws"),
    ("VMess_HTTPUpgrade_TLS", "vmess_httpupgrade_tls", "VMess HTTPUpgrade TLS", "N",  "N",  "chrome", "/vmess-httpupgrade"),
    ("Trojan_gRPC_TLS",       "trojan_grpc_tls",       "Trojan GRPC TLS",       "N",  None, "chrome", "trojan-grpc"),
)

ACTIVE_INBOUND_TAGS = tuple(spec[2] for spec in _HOST_SPECS)


def default_nodes(config: LinkRayConfig) -> list[NodeHost]:
    return [NodeHost("primary", config.domain)]


def linkray_api_service(nodes: Sequence[NodeHost], config: LinkRayConfig) -> str:
    node_flags = [f"--node {shlex.quote(f'{node.name}={node.domain}')}" for node in nodes]
    inbound_flags = [f"--inbound {shlex.quote(f'{key}={port}')}" for key, port in config.inbound_ports]
    singbox_flags = [
        f"--singbox-inbound {shlex.quote(f'{key}={port}')}" for key, port in config.singbox_inbound_ports
    ]
    snell_flags = [f"--snell-inbound {shlex.quote(f'{key}={port}')}" for key, port in config.snell_inbound_ports]
    flags = " ".join([*node_flags, *inbound_flags, *singbox_flags, *snell_flags])
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


def _marzban_adapter_service(description: str, cmd: str, port: int, marzban_http_port: int) -> str:
    return f"""[Unit]
Description={description}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/linkray {cmd} --listen 127.0.0.1 --port {port} --marzban-url http://127.0.0.1:{marzban_http_port}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""


def linkray_egern_service(config: LinkRayConfig) -> str:
    return _marzban_adapter_service("LinkRay Egern subscription adapter", "egern", 61992, config.marzban_http_port)


def linkray_clash_service(config: LinkRayConfig) -> str:
    return f"""[Unit]
Description=LinkRay Clash/Mihomo subscription adapter
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/linkray clash --listen 127.0.0.1 --port 61991 --marzban-url http://127.0.0.1:{config.marzban_http_port} --server-domain {shlex.quote(config.domain)} --snell-runtime-dir {SNELL_RUNTIME_DIR} --snell-reload-command 'systemctl enable --now linkray-snell@{{instance}}'
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
ExecStart=/usr/local/bin/linkray shadowrocket --listen 127.0.0.1 --port 61994 --marzban-url http://127.0.0.1:{config.marzban_http_port} --server-domain {shlex.quote(config.domain)} --snell-runtime-dir {SNELL_RUNTIME_DIR} --snell-reload-command 'systemctl enable --now linkray-snell@{{instance}}'
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""


def linkray_singbox_service(config: LinkRayConfig) -> str:
    inbound_flags = " ".join(
        f"--singbox-inbound {shlex.quote(f'{key}={port}')}" for key, port in config.singbox_inbound_ports
    )
    if inbound_flags:
        inbound_flags = " " + inbound_flags
    return f"""[Unit]
Description=LinkRay sing-box subscription adapter
After=network-online.target linkray-singbox-runtime.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/linkray sing-box --listen 127.0.0.1 --port 61995 --marzban-url http://127.0.0.1:{config.marzban_http_port} --server-domain {shlex.quote(config.domain)} --runtime-dir {DEFAULT_RUNTIME_DIR}{inbound_flags} --reload-command 'systemctl try-restart linkray-singbox-runtime'
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""


def linkray_singbox_runtime_service() -> str:
    return """[Unit]
Description=LinkRay sing-box advanced protocol runtime
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/sing-box run -c /var/lib/marzban/linkray/singbox/config.json
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""


def linkray_snell_runtime_service() -> str:
    return f"""[Unit]
Description=LinkRay Snell runtime
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/snell-server -c {SNELL_RUNTIME_DIR}/snell-server.conf
Restart=always
RestartSec=3
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
"""


def linkray_snell_user_service() -> str:
    return f"""[Unit]
Description=LinkRay Snell user runtime %i
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/snell-server -c {SNELL_RUNTIME_DIR}/users/%i.conf
Restart=always
RestartSec=3
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
"""


def linkray_snell_usage_service() -> str:
    return f"""[Unit]
Description=LinkRay Snell usage accounting sidecar
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/linkray snell-usage --listen 127.0.0.1 --port 61997 --runtime-dir {SNELL_RUNTIME_DIR}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""


def linkray_xray_service() -> str:
    return """[Unit]
Description=LinkRay Xray-core runtime
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=XRAY_LOCATION_ASSET=/var/lib/marzban/linkray/bin
ExecStartPre=/usr/bin/test -s /var/lib/marzban/linkray/xray/runtime.json
ExecStart=/var/lib/marzban/linkray/bin/xray run -config /var/lib/marzban/linkray/xray/runtime.json
Restart=always
RestartSec=3
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
"""


def linkray_sub_auto_service(config: LinkRayConfig) -> str:
    return f"""[Unit]
Description=LinkRay automatic subscription format router
After=network-online.target linkray-clash.service linkray-egern.service linkray-shadowrocket.service linkray-singbox.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/linkray sub-auto --listen 127.0.0.1 --port 61993 --marzban-url http://127.0.0.1:{config.marzban_http_port} --clash-url http://127.0.0.1:61991 --egern-url http://127.0.0.1:61992 --shadowrocket-url http://127.0.0.1:61994 --singbox-url http://127.0.0.1:61995
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
    occupied_ports = {port: f"primary:{key}" for key, port in ports.items()}
    for node_index, node in enumerate(nodes):
        node.validate()
        address = node.domain if node_index == 0 else config.domain
        for remark_suffix, port_key, inbound_tag, sni_src, host_src, fingerprint, path_src in _HOST_SPECS:
            sni = node.domain if sni_src == "N" else config.reality_server_name if sni_src == "R" else None
            host = node.domain if host_src == "N" else None
            path = config.grpc_service_name if path_src == "grpc" else path_src
            port = relay_port(ports[port_key], node_index)
            if node_index > 0:
                if port in occupied_ports:
                    raise ValueError(f"relay port conflict {port}: {node.name}:{port_key} conflicts with {occupied_ports[port]}")
                occupied_ports[port] = f"{node.name}:{port_key}"
            rows.append((
                f"{node.name}-{remark_suffix}",
                address,
                port,
                inbound_tag,
                sni,
                host,
                "inbound_default",
                "none",
                fingerprint,
                0, 0,
                path,
                0, None, 0, None, 0,
            ))
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


def copy_tree_files(src: Path, dst: Path) -> list[Path]:
    copied: list[Path] = []
    for source in sorted(path for path in src.rglob("*") if path.is_file()):
        target = dst / source.relative_to(src)
        copied.append(copy_file(source, target))
    return copied


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
        write_text(output / "opt/marzban/docker-compose.yml", master_compose(config)),
        write_text(output / "etc/nginx/conf.d/marzban-panel.conf", nginx_panel(config)),
        write_text(output / "etc/systemd/system/linkray-api.service", linkray_api_service(effective_nodes, config)),
        write_text(output / "etc/systemd/system/linkray-clash.service", linkray_clash_service(config)),
        write_text(output / "etc/systemd/system/linkray-egern.service", linkray_egern_service(config)),
        write_text(output / "etc/systemd/system/linkray-shadowrocket.service", linkray_shadowrocket_service(config)),
        write_text(output / "etc/systemd/system/linkray-singbox.service", linkray_singbox_service(config)),
        write_text(output / "etc/systemd/system/linkray-singbox-runtime.service", linkray_singbox_runtime_service()),
        write_text(output / "etc/systemd/system/linkray-snell-runtime.service", linkray_snell_runtime_service()),
        write_text(output / "etc/systemd/system/linkray-snell@.service", linkray_snell_user_service()),
        write_text(output / "etc/systemd/system/linkray-snell-usage.service", linkray_snell_usage_service()),
        write_text(output / "etc/systemd/system/linkray-sub-auto.service", linkray_sub_auto_service(config)),
        write_text(output / "etc/systemd/system/linkray-rules-update.service", linkray_rules_update_service()),
        write_text(output / "etc/systemd/system/linkray-rules-update.timer", linkray_rules_update_timer()),
        write_text(output / "etc/systemd/system/linkray-relay.service", linkray_relay_service(effective_nodes, config)),
        write_text(output / "var/lib/marzban/linkray/hosts.sql", hosts_sql(config, effective_nodes)),
        write_text(output / "var/lib/marzban/linkray/linkray-manifest.json", render_manifest(config, effective_nodes)),
        write_text(
            output / "var/lib/marzban/linkray/xray/runtime.json",
            json.dumps(xray_runtime_config(config), indent=2) + "\n",
        ),
        write_text(output / "var/lib/marzban/linkray/singbox/config.json", json.dumps(server_config(config, []), indent=2) + "\n"),
        write_text(output / "var/lib/marzban/linkray/singbox/users.json", json.dumps({"version": 1, "users": []}, indent=2) + "\n"),
        write_text(output / "var/lib/marzban/linkray/snell/snell-server.conf", snell_server_config_text(config)),
        copy_file(
            DASHBOARD_SOURCE_PATCH_ROOT / "README.md",
            output / "var/lib/marzban/linkray/source-patches/marzban-dashboard/README.md",
        ),
        copy_file(
            DASHBOARD_SOURCE_PATCH_ROOT / "linkray-dashboard.patch",
            output / "var/lib/marzban/linkray/source-patches/marzban-dashboard/linkray-dashboard.patch",
        ),
        output / "var/lib/marzban/linkray/rules/cn-domains.txt",
        output / "var/lib/marzban/linkray/rules/cn-ip-cidrs.txt",
        copy_file(TEMPLATE_ROOT / "marzban/clash/default.yml", output / "var/lib/marzban/templates/clash/default.yml"),
        copy_file(PATCH_ROOT / "marzban-subscription/current/clash.py", output / "var/lib/marzban/linkray/patches/clash.py"),
        copy_file(
            PATCH_ROOT / "marzban-xray/current/xray_init.py",
            output / "var/lib/marzban/linkray/patches/xray_init.py",
        ),
        copy_file(
            PATCH_ROOT / "marzban-xray/current/0_xray_core.py",
            output / "var/lib/marzban/linkray/patches/0_xray_core.py",
        ),
        copy_file(
            PATCH_ROOT / "marzban-jobs/current/linkray_singbox_usages.py",
            output / "var/lib/marzban/linkray/jobs/linkray_singbox_usages.py",
        ),
        copy_file(
            PATCH_ROOT / "marzban-subscription-page/current/index.html",
            output / "var/lib/marzban/templates/subscription/index.html",
        ),
        copy_file(PATCH_ROOT / "marzban-dashboard/current/index.html", output / "var/lib/marzban/dashboard-patches/index.html"),
        copy_file(PATCH_ROOT / "marzban-dashboard/current/index.linkray.js", output / f"var/lib/marzban/dashboard-patches/{DASHBOARD_PATCH_JS}"),
        copy_file(PATCH_ROOT / "marzban-dashboard/current/index.original.js", output / "var/lib/marzban/dashboard-patches/index.original.js"),
    ]
    if config.xray_runtime_mode == "linkray":
        files.append(write_text(output / "etc/systemd/system/linkray-xray.service", linkray_xray_service()))
    return RenderResult(output=output, files=tuple(files))


def render_node(output: Path, config: LinkRayConfig | None = None) -> RenderResult:
    files = [
        *copy_tree_files(NODE_APP_ROOT, output / "opt/linkray-node-app/current"),
        write_text(output / "etc/systemd/system/linkray-node.service", linkray_node_service()),
        write_text(output / "etc/systemd/system/linkray-xray.service", linkray_xray_service()),
    ]
    if config:
        files.extend(
            [
                write_text(output / "etc/systemd/system/linkray-singbox-runtime.service", linkray_singbox_runtime_service()),
                write_text(output / "etc/systemd/system/linkray-snell-runtime.service", linkray_snell_runtime_service()),
                write_text(output / "etc/systemd/system/linkray-snell@.service", linkray_snell_user_service()),
                write_text(output / "etc/systemd/system/linkray-snell-usage.service", linkray_snell_usage_service()),
                write_text(
                    output / "var/lib/marzban/linkray/singbox/config.json",
                    json.dumps(server_config(config, []), indent=2) + "\n",
                ),
                write_text(
                    output / "var/lib/marzban/linkray/singbox/users.json",
                    json.dumps({"version": 1, "users": []}, indent=2) + "\n",
                ),
                write_text(output / "var/lib/marzban/linkray/snell/snell-server.conf", snell_server_config_text(config)),
                write_text(output / "var/lib/marzban/linkray/linkray-manifest.json", render_manifest(config, [NodeHost("node", config.domain)], role="node")),
            ]
        )
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
    manifest_path = path / "var/lib/marzban/linkray/linkray-manifest.json"
    if xray_path.exists() and not manifest_path.exists():
        errors.append(f"{path}: missing var/lib/marzban/linkray/linkray-manifest.json")
    service_paths = [
        path / "etc/systemd/system/linkray-api.service",
        path / "etc/systemd/system/linkray-clash.service",
        path / "etc/systemd/system/linkray-egern.service",
        path / "etc/systemd/system/linkray-shadowrocket.service",
        path / "etc/systemd/system/linkray-singbox.service",
        path / "etc/systemd/system/linkray-singbox-runtime.service",
        path / "etc/systemd/system/linkray-snell-runtime.service",
        path / "etc/systemd/system/linkray-snell@.service",
        path / "etc/systemd/system/linkray-snell-usage.service",
        path / "etc/systemd/system/linkray-sub-auto.service",
        path / "etc/systemd/system/linkray-rules-update.service",
        path / "etc/systemd/system/linkray-rules-update.timer",
    ]
    if rendered_xray_runtime_mode(path) == "linkray":
        service_paths.append(path / "etc/systemd/system/linkray-xray.service")
    if (path / "opt/marzban/docker-compose.yml").exists():
        for service_path in service_paths:
            if not service_path.exists():
                errors.append(f"{path}: missing {service_path.relative_to(path)}")
    if (path / "opt/linkray-node-app/current/main.py").exists():
        node_required = [
            path / "opt/linkray-node-app/current/requirements.txt",
            path / "etc/systemd/system/linkray-node.service",
            path / "etc/systemd/system/linkray-xray.service",
        ]
        for required in node_required:
            if not required.exists():
                errors.append(f"{path}: missing {required.relative_to(path)}")
    clash_patch_path = path / "var/lib/marzban/linkray/patches/clash.py"
    if (path / "opt/marzban/docker-compose.yml").exists() and not clash_patch_path.exists():
        errors.append(f"{path}: missing var/lib/marzban/linkray/patches/clash.py")
    xray_runtime_path = path / "var/lib/marzban/linkray/xray/runtime.json"
    if rendered_xray_runtime_mode(path) == "linkray" and not xray_runtime_path.exists():
        errors.append(f"{path}: missing var/lib/marzban/linkray/xray/runtime.json")
    for patch_name in ["0_xray_core.py", "xray_init.py"]:
        patch_path = path / f"var/lib/marzban/linkray/patches/{patch_name}"
        if rendered_xray_runtime_mode(path) == "linkray" and not patch_path.exists():
            errors.append(f"{path}: missing var/lib/marzban/linkray/patches/{patch_name}")
    singbox_usage_job_path = path / "var/lib/marzban/linkray/jobs/linkray_singbox_usages.py"
    if (path / "opt/marzban/docker-compose.yml").exists() and not singbox_usage_job_path.exists():
        errors.append(f"{path}: missing var/lib/marzban/linkray/jobs/linkray_singbox_usages.py")
    snell_config_path = path / "var/lib/marzban/linkray/snell/snell-server.conf"
    if (path / "opt/marzban/docker-compose.yml").exists() and not snell_config_path.exists():
        errors.append(f"{path}: missing var/lib/marzban/linkray/snell/snell-server.conf")
    required_any = [
        path / "opt/marzban/docker-compose.yml",
        path / "opt/linkray-node-app/current/main.py",
    ]
    if not any(item.exists() for item in required_any):
        errors.append(f"{path}: missing master docker-compose.yml or node app")
    return errors
