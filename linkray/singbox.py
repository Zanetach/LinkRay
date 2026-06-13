from __future__ import annotations

import argparse
import ipaddress
import json
import re
import socket
import subprocess
from collections.abc import Mapping
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlparse

from ._http import PASS_HEADERS, AdapterHandler, fetch_subscription_username, fetch_upstream, first_query_value, parse_link_netloc
from .config import LinkRayConfig, parse_singbox_inbound_ports
from .native import b64decode_text, decode_subscription_links
from .protocol_prefs import (
    DEFAULT_PROTOCOL_PREFS_PATH,
    ProtocolPreferences,
    SINGBOX_PROTOCOL_KEYS,
    enabled_protocols_for_user,
    load_protocol_preferences,
)
from .rules import COMPACT_CN_DOMAIN_SUFFIXES, FOREIGN_DOMAIN_SUFFIXES, RouteRules, load_route_rules
from .singbox_runtime import (
    DEFAULT_RUNTIME_DIR,
    SingBoxUser,
    ensure_runtime_user,
    reconcile_runtime_users,
    singbox_user_outbounds,
)


TOKEN_RE = re.compile(r"^/sub/([^/]+)/sing-box/?$")
FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")


def proxy_tag(parsed, host: str) -> str:
    return unquote(parsed.fragment) or host


def tls_config(query: Mapping[str, list[str]], fallback_server_name: str, reality: bool = False) -> dict[str, Any]:
    server_name = first_query_value(query, "sni", "servername") or fallback_server_name
    config: dict[str, Any] = {
        "enabled": True,
        "server_name": server_name,
        "utls": {
            "enabled": True,
            "fingerprint": first_query_value(query, "fp", "fingerprint") or "chrome",
        },
    }
    alpn = first_query_value(query, "alpn")
    if alpn:
        config["alpn"] = [item.strip() for item in alpn.split(",") if item.strip()]
    if reality:
        public_key = first_query_value(query, "pbk", "public-key", "public_key") or ""
        short_id = first_query_value(query, "sid", "short-id", "short_id") or ""
        config["reality"] = {
            "enabled": True,
            "public_key": public_key,
            "short_id": short_id,
        }
    return config


def transport_config(query: Mapping[str, list[str]], network: str, fallback_host: str) -> dict[str, Any] | None:
    if network == "tcp":
        return None
    if network == "ws":
        host = first_query_value(query, "host") or fallback_host
        return {
            "type": "ws",
            "path": first_query_value(query, "path") or "/",
            "headers": {"Host": host},
        }
    if network == "grpc":
        return {
            "type": "grpc",
            "service_name": first_query_value(query, "serviceName", "service_name") or "grpc",
        }
    if network == "httpupgrade":
        host = first_query_value(query, "host") or fallback_host
        return {
            "type": "httpupgrade",
            "host": host,
            "path": first_query_value(query, "path") or "/",
        }
    return None


def vless_to_singbox(link: str) -> dict[str, Any] | None:
    parsed = urlparse(link)
    host_port = parse_link_netloc(parsed)
    if not host_port or not parsed.username:
        return None
    host, port = host_port
    query = parse_qs(parsed.query)
    network = first_query_value(query, "type") or "tcp"
    security = first_query_value(query, "security")
    if network == "xhttp" or network not in {"tcp", "ws", "grpc", "httpupgrade"}:
        return None
    outbound: dict[str, Any] = {
        "type": "vless",
        "tag": proxy_tag(parsed, host),
        "server": host,
        "server_port": port,
        "uuid": unquote(parsed.username),
        "packet_encoding": "xudp",
    }
    flow = first_query_value(query, "flow")
    if flow:
        outbound["flow"] = flow
    transport = transport_config(query, network, host)
    if transport:
        outbound["transport"] = transport
    if security == "tls":
        outbound["tls"] = tls_config(query, host)
        if network == "grpc":
            outbound["tls"].setdefault("alpn", ["h2"])
    elif security == "reality":
        outbound["tls"] = tls_config(query, host, reality=True)
    else:
        return None
    return outbound


def trojan_to_singbox(link: str) -> dict[str, Any] | None:
    parsed = urlparse(link)
    host_port = parse_link_netloc(parsed)
    if not host_port or not parsed.username:
        return None
    host, port = host_port
    query = parse_qs(parsed.query)
    network = first_query_value(query, "type") or "tcp"
    if network == "xhttp" or network not in {"tcp", "ws", "grpc", "httpupgrade"}:
        return None
    outbound: dict[str, Any] = {
        "type": "trojan",
        "tag": proxy_tag(parsed, host),
        "server": host,
        "server_port": port,
        "password": unquote(parsed.username),
        "tls": tls_config(query, host),
    }
    if network == "grpc":
        outbound["tls"].setdefault("alpn", ["h2"])
    transport = transport_config(query, network, host)
    if transport:
        outbound["transport"] = transport
    return outbound


def vmess_to_singbox(link: str) -> dict[str, Any] | None:
    try:
        data = json.loads(b64decode_text(link.removeprefix("vmess://")))
    except (ValueError, UnicodeDecodeError):
        return None
    host = data.get("add")
    port = data.get("port")
    uuid = data.get("id")
    if not host or not port or not uuid:
        return None
    network = data.get("net") or "tcp"
    if network == "xhttp" or network not in {"tcp", "ws", "grpc", "httpupgrade"}:
        return None
    query = {
        "host": [str(data.get("host") or host)],
        "path": [str(data.get("path") or "/")],
        "sni": [str(data.get("sni") or data.get("host") or host)],
        "serviceName": [str(data.get("path") or data.get("serviceName") or "grpc")],
    }
    outbound: dict[str, Any] = {
        "type": "vmess",
        "tag": str(data.get("ps") or host),
        "server": str(host),
        "server_port": int(port),
        "uuid": str(uuid),
        "security": str(data.get("scy") or "auto"),
        "alter_id": int(data.get("aid") or 0),
        "packet_encoding": "xudp",
    }
    transport = transport_config(query, str(network), str(host))
    if transport:
        outbound["transport"] = transport
    if data.get("tls") == "tls":
        outbound["tls"] = tls_config(query, str(host))
        if str(network) == "grpc":
            outbound["tls"].setdefault("alpn", ["h2"])
    return outbound


def parse_shadowsocks_userinfo(raw: str) -> tuple[str, str] | None:
    userinfo = raw
    if ":" not in userinfo:
        try:
            userinfo = b64decode_text(userinfo)
        except (ValueError, UnicodeDecodeError):
            return None
    if ":" not in userinfo:
        return None
    method, password = userinfo.split(":", 1)
    return unquote(method), unquote(password)


def shadowsocks_to_singbox(link: str) -> dict[str, Any] | None:
    parsed = urlparse(link)
    host_port = parse_link_netloc(parsed)
    if host_port and parsed.username:
        host, port = host_port
        parsed_userinfo = parse_shadowsocks_userinfo(parsed.username)
    else:
        text = link.removeprefix("ss://").split("#", 1)[0].split("?", 1)[0]
        try:
            decoded = b64decode_text(text)
        except (ValueError, UnicodeDecodeError):
            return None
        if "@" not in decoded:
            return None
        userinfo, server = decoded.rsplit("@", 1)
        if ":" not in server:
            return None
        host, raw_port = server.rsplit(":", 1)
        try:
            port = int(raw_port)
        except ValueError:
            return None
        parsed_userinfo = parse_shadowsocks_userinfo(userinfo)
    if not parsed_userinfo:
        return None
    method, password = parsed_userinfo
    return {
        "type": "shadowsocks",
        "tag": proxy_tag(parsed, host),
        "server": host,
        "server_port": port,
        "method": method,
        "password": password,
    }


def convert_link(link: str) -> dict[str, Any] | None:
    if link.startswith("vless://"):
        return vless_to_singbox(link)
    if link.startswith("trojan://"):
        return trojan_to_singbox(link)
    if link.startswith("vmess://"):
        return vmess_to_singbox(link)
    if link.startswith("ss://"):
        return shadowsocks_to_singbox(link)
    return None


def is_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def public_ipv4_for_host(host: str) -> str | None:
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return None
    for info in infos:
        address = info[4][0]
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            continue
        if parsed.version == 4 and parsed not in FAKE_IP_NETWORK:
            return address
    return None


def resolve_public_server(outbound: dict[str, Any]) -> dict[str, Any]:
    server = outbound.get("server")
    if not isinstance(server, str) or not server or is_ip_address(server):
        return outbound
    address = public_ipv4_for_host(server)
    if not address:
        return outbound
    outbound["server"] = address
    return outbound


def advanced_domain_label(domain: str) -> str:
    label = domain.split(".", 1)[0]
    clean = re.sub(r"[^A-Za-z0-9_-]+", "-", label).strip("-")
    return clean or "node"


def label_advanced_outbound(outbound: dict[str, Any], domain: str) -> dict[str, Any]:
    labeled = dict(outbound)
    labeled["tag"] = f"{advanced_domain_label(domain)}-{outbound['tag']}"
    return labeled


def run_sync_command(command: str) -> None:
    if not command:
        return
    try:
        subprocess.run(command, shell=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return


def public_stable_outbound(outbound: dict[str, Any]) -> bool:
    proxy_type = outbound.get("type")
    transport = outbound.get("transport") or {}
    network = transport.get("type", "tcp") if isinstance(transport, dict) else "tcp"
    port = outbound.get("server_port")
    tls = outbound.get("tls")
    if proxy_type == "vless":
        if not isinstance(tls, dict) or tls.get("reality"):
            return False
        return port == 443 and network in {"tcp", "ws"}
    if proxy_type == "vmess":
        if not isinstance(tls, dict):
            return False
        return port == 443 and network in {"ws", "httpupgrade"}
    if proxy_type == "trojan":
        if not isinstance(tls, dict):
            return False
        return port == 443 and network in {"tcp", "ws"}
    return False


def clean_rules_base_url(rules_base_url: str | None) -> str:
    return (rules_base_url or "").rstrip("/")


def metacubex_rule_sets(rules_base_url: str) -> list[dict[str, Any]]:
    return [
        {
            "tag": "linkray-geosite-cn",
            "type": "remote",
            "format": "binary",
            "url": f"{rules_base_url}/sing-box/geosite-cn.srs",
            "download_detour": "DIRECT",
        },
        {
            "tag": "linkray-geoip-cn",
            "type": "remote",
            "format": "binary",
            "url": f"{rules_base_url}/sing-box/geoip-cn.srs",
            "download_detour": "DIRECT",
        },
    ]


def build_group_outbounds(names: list[str]) -> list[dict[str, Any]]:
    if not names:
        return [
            {"type": "selector", "tag": "手动切换", "outbounds": ["DIRECT"]},
            {"type": "selector", "tag": "自动选择", "outbounds": ["DIRECT"]},
            {"type": "selector", "tag": "全球代理", "outbounds": ["DIRECT"]},
            {"type": "selector", "tag": "国内站点", "outbounds": ["DIRECT"]},
            {"type": "selector", "tag": "漏网之鱼", "outbounds": ["DIRECT"]},
        ]
    return [
        {"type": "selector", "tag": "手动切换", "outbounds": names, "default": names[0]},
        {
            "type": "urltest",
            "tag": "自动选择",
            "outbounds": names,
            "url": "https://www.gstatic.com/generate_204",
            "interval": "5m",
            "tolerance": 50,
        },
        {"type": "selector", "tag": "全球代理", "outbounds": ["手动切换", "自动选择", *names], "default": "自动选择"},
        {"type": "selector", "tag": "国内站点", "outbounds": ["DIRECT", "全球代理"], "default": "DIRECT"},
        {"type": "selector", "tag": "漏网之鱼", "outbounds": ["全球代理", "自动选择", "手动切换", "DIRECT"], "default": "全球代理"},
    ]


def build_route_rules(route_rules: RouteRules, use_rule_sets: bool = False) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = [
        {"ip_is_private": True, "outbound": "国内站点"},
        {"domain_suffix": ["local"], "outbound": "国内站点"},
        {"domain_suffix": ["lan"], "outbound": "国内站点"},
    ]
    for domain in FOREIGN_DOMAIN_SUFFIXES:
        rules.append({"domain_suffix": [domain], "outbound": "全球代理"})
    for domain in COMPACT_CN_DOMAIN_SUFFIXES:
        rules.append({"domain_suffix": [domain], "outbound": "国内站点"})
    if route_rules.cn_ip_cidrs:
        rules.append({"ip_cidr": route_rules.cn_ip_cidrs, "outbound": "国内站点"})
    if use_rule_sets:
        rules.append({"rule_set": ["linkray-geosite-cn"], "outbound": "国内站点"})
        rules.append({"rule_set": ["linkray-geoip-cn"], "outbound": "国内站点"})
    return rules


def build_singbox_json(
    subscription_payload: bytes,
    route_rules: RouteRules | None = None,
    config: LinkRayConfig | None = None,
    advanced_configs: list[LinkRayConfig] | None = None,
    advanced_user: SingBoxUser | None = None,
    protocol_preferences: ProtocolPreferences | None = None,
    rules_base_url: str | None = None,
    public_only: bool = False,
) -> str:
    outbounds: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in decode_subscription_links(subscription_payload):
        outbound = convert_link(link)
        if not outbound:
            continue
        if public_only and not public_stable_outbound(outbound):
            continue
        if public_only:
            outbound = resolve_public_server(outbound)
        tag = outbound.get("tag")
        if not isinstance(tag, str) or not tag or tag in seen:
            continue
        seen.add(tag)
        outbounds.append(outbound)
    configs = advanced_configs if advanced_configs is not None else ([config] if config else [])
    if configs and advanced_user:
        enabled = enabled_protocols_for_user(protocol_preferences, advanced_user.name)
        tag_keys = {"Hysteria2": "hysteria2", "TUIC": "tuic", "AnyTLS": "anytls"}
        multi_domain = len(configs) > 1
        for advanced_config in configs:
            for outbound in singbox_user_outbounds(advanced_config, advanced_user):
                raw_tag = outbound["tag"]
                if tag_keys.get(str(raw_tag)) not in enabled:
                    continue
                if multi_domain:
                    outbound = label_advanced_outbound(outbound, advanced_config.domain)
                if public_only:
                    outbound = resolve_public_server(outbound)
                tag = outbound["tag"]
                if tag not in seen:
                    seen.add(tag)
                    outbounds.append(outbound)

    names = [str(outbound["tag"]) for outbound in outbounds]
    effective_rules = route_rules or load_route_rules()
    clean_base = clean_rules_base_url(rules_base_url)
    route: dict[str, Any] = {
        "rules": build_route_rules(effective_rules, use_rule_sets=bool(clean_base)),
        "final": "漏网之鱼",
    }
    if not public_only:
        route["auto_detect_interface"] = True
    data = {
        "log": {"level": "warning"},
        "dns": {
            "servers": [
                {"tag": "local", "address": "223.5.5.5", "detour": "DIRECT"},
                {"tag": "remote", "address": "https://dns.google/dns-query", "detour": "全球代理"},
            ],
            "rules": [
                {
                    "domain_suffix": list(COMPACT_CN_DOMAIN_SUFFIXES),
                    "server": "local",
                },
                {
                    "ip_cidr": ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
                    "server": "local",
                },
            ],
            "final": "remote",
        },
        "inbounds": [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "127.0.0.1",
                "listen_port": 2080,
            }
        ],
        "outbounds": [
            *outbounds,
            {"type": "direct", "tag": "DIRECT"},
            {"type": "block", "tag": "REJECT"},
            *build_group_outbounds(names),
        ],
        "route": route,
        "experimental": {
            "clash_api": {
                "external_controller": "127.0.0.1:9090",
                "default_mode": "rule",
            }
        },
    }
    if clean_base:
        data["route"]["rule_set"] = metacubex_rule_sets(clean_base)
    return json.dumps(data, ensure_ascii=False, indent=2, separators=(",", ": ")) + "\n"


class SingBoxHandler(AdapterHandler):
    server_domain = ""
    advanced_domains = ()
    runtime_dir = DEFAULT_RUNTIME_DIR
    reload_command = ""
    sync_command = ""
    singbox_inbound_ports = ()
    protocol_preferences_path = DEFAULT_PROTOCOL_PREFS_PATH
    rules_base_url = ""

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self.send_bytes(200, {"Content-Type": "text/plain"}, b"ok\n")
            return
        match = TOKEN_RE.match(path)
        if not match:
            self.send_bytes(404, {"Content-Type": "text/plain"}, b"not found\n")
            return
        token = match.group(1)
        try:
            _, upstream_headers, raw = fetch_upstream(self.marzban_url, token, {"Accept": "text/plain"})
            config = None
            advanced_configs = None
            advanced_user = None
            protocol_preferences = None
            if self.server_domain:
                config = LinkRayConfig(domain=self.server_domain, singbox_inbound_ports=self.singbox_inbound_ports)
                domains = list(dict.fromkeys([self.server_domain, *self.advanced_domains]))
                advanced_configs = [
                    LinkRayConfig(domain=domain, singbox_inbound_ports=self.singbox_inbound_ports)
                    for domain in domains
                ]
                username = fetch_subscription_username(self.marzban_url, token)
                if not username:
                    raise ValueError("missing Marzban username for sing-box runtime user")
                protocol_preferences = load_protocol_preferences(Path(self.protocol_preferences_path))
                enabled = enabled_protocols_for_user(protocol_preferences, username)
                if enabled.intersection(SINGBOX_PROTOCOL_KEYS):
                    advanced_user, changed = ensure_runtime_user(
                        token,
                        config,
                        runtime_dir=Path(self.runtime_dir),
                        reload_command=self.reload_command or None,
                        name=username,
                    )
                    if changed:
                        run_sync_command(self.sync_command)
            body = build_singbox_json(
                raw,
                config=config,
                advanced_configs=advanced_configs,
                advanced_user=advanced_user,
                protocol_preferences=protocol_preferences,
                rules_base_url=self.rules_base_url,
                public_only=True,
            ).encode("utf-8")
        except HTTPError as exc:
            self.send_bytes(exc.code, dict(exc.headers.items()), exc.read() or b"upstream error\n")
            return
        except (URLError, TimeoutError, ValueError) as exc:
            self.send_bytes(502, {"Content-Type": "text/plain"}, f"sing-box upstream unavailable: {exc}\n".encode("utf-8"))
            return
        headers = {name: value for name, value in upstream_headers.items() if name.lower() in PASS_HEADERS}
        headers["Content-Type"] = "application/json; charset=utf-8"
        self.send_bytes(200, headers, body)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/runtime/reconcile":
            self.send_bytes(404, {"Content-Type": "text/plain"}, b"not found\n")
            return
        if not self.server_domain:
            self.send_bytes(503, {"Content-Type": "text/plain"}, b"sing-box runtime is not enabled\n")
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            usernames = payload.get("active_usernames")
            if not isinstance(usernames, list) or not all(isinstance(item, str) for item in usernames):
                raise ValueError("active_usernames must be a string list")
            config = LinkRayConfig(domain=self.server_domain, singbox_inbound_ports=self.singbox_inbound_ports)
            changed = reconcile_runtime_users(
                set(usernames),
                config,
                runtime_dir=Path(self.runtime_dir),
                reload_command=self.reload_command or None,
            )
            if changed and self.sync_command:
                run_sync_command(self.sync_command)
            remaining = len([name for name in usernames if name])
            body = json.dumps({"ok": True, "changed": changed, "remaining": remaining}).encode("utf-8")
            self.send_bytes(200, {"Content-Type": "application/json; charset=utf-8"}, body)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.send_bytes(400, {"Content-Type": "text/plain"}, f"invalid reconcile request: {exc}\n".encode("utf-8"))

def make_singbox_server(
    listen: str,
    port: int,
    marzban_url: str,
    server_domain: str = "",
    advanced_domains=(),
    runtime_dir=DEFAULT_RUNTIME_DIR,
    reload_command: str = "",
    sync_command: str = "",
    singbox_inbound_ports=(),
    protocol_preferences_path=DEFAULT_PROTOCOL_PREFS_PATH,
    rules_base_url: str = "",
) -> ThreadingHTTPServer:
    class Handler(SingBoxHandler):
        pass

    Handler.marzban_url = marzban_url
    Handler.server_domain = server_domain
    Handler.advanced_domains = tuple(advanced_domains or ())
    Handler.runtime_dir = runtime_dir
    Handler.reload_command = reload_command
    Handler.sync_command = sync_command
    Handler.singbox_inbound_ports = singbox_inbound_ports
    Handler.protocol_preferences_path = protocol_preferences_path
    Handler.rules_base_url = rules_base_url
    return ThreadingHTTPServer((listen, port), Handler)


def serve_singbox(args: argparse.Namespace) -> int:
    server = make_singbox_server(
        args.listen,
        args.port,
        args.marzban_url,
        server_domain=getattr(args, "server_domain", ""),
        advanced_domains=getattr(args, "advanced_domain", None),
        runtime_dir=getattr(args, "runtime_dir", DEFAULT_RUNTIME_DIR),
        reload_command=getattr(args, "reload_command", ""),
        sync_command=getattr(args, "sync_command", ""),
        singbox_inbound_ports=parse_singbox_inbound_ports(getattr(args, "singbox_inbound", None)),
        rules_base_url=getattr(args, "rules_base_url", ""),
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0
