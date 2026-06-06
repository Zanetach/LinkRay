from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen

from .egern import FOREIGN_DOMAIN_SUFFIXES
from .native import b64decode_text, decode_subscription_links
from .rules import BUILTIN_CN_DOMAIN_SUFFIXES, RouteRules, load_route_rules


TOKEN_RE = re.compile(r"^/sub/([^/]+)/sing-box/?$")
PASS_HEADERS = {
    "content-disposition",
    "support-url",
    "profile-title",
    "profile-update-interval",
    "subscription-userinfo",
}


def first_query_value(query: Mapping[str, list[str]], *names: str) -> str:
    for name in names:
        values = query.get(name)
        if values and values[0]:
            return values[0]
    return ""


def parse_link_netloc(parsed) -> tuple[str, int] | None:
    host = parsed.hostname
    port = parsed.port
    if not host or not port:
        return None
    return host, int(port)


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
    if reality:
        public_key = first_query_value(query, "pbk", "public-key", "public_key")
        short_id = first_query_value(query, "sid", "short-id", "short_id")
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


def build_route_rules(route_rules: RouteRules) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = [
        {"ip_is_private": True, "outbound": "国内站点"},
        {"domain_suffix": ["local"], "outbound": "国内站点"},
        {"domain_suffix": ["lan"], "outbound": "国内站点"},
    ]
    for domain in FOREIGN_DOMAIN_SUFFIXES:
        rules.append({"domain_suffix": [domain], "outbound": "全球代理"})
    compact_cn_domains = sorted(set(BUILTIN_CN_DOMAIN_SUFFIXES) | {"dns.pub", "doh.pub", "alidns.com"})
    for domain in compact_cn_domains:
        rules.append({"domain_suffix": [domain], "outbound": "国内站点"})
    if route_rules.cn_ip_cidrs:
        rules.append({"ip_cidr": route_rules.cn_ip_cidrs, "outbound": "国内站点"})
    return rules


def build_singbox_json(subscription_payload: bytes, route_rules: RouteRules | None = None) -> str:
    outbounds: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in decode_subscription_links(subscription_payload):
        outbound = convert_link(link)
        if not outbound:
            continue
        tag = outbound.get("tag")
        if not isinstance(tag, str) or not tag or tag in seen:
            continue
        seen.add(tag)
        outbounds.append(outbound)

    names = [str(outbound["tag"]) for outbound in outbounds]
    effective_rules = route_rules or load_route_rules()
    data = {
        "log": {"level": "warning"},
        "dns": {
            "servers": [
                {"tag": "local", "address": "223.5.5.5", "detour": "DIRECT"},
                {"tag": "remote", "address": "https://dns.google/dns-query", "detour": "全球代理"},
            ],
            "final": "local",
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
        "route": {
            "rules": build_route_rules(effective_rules),
            "final": "漏网之鱼",
            "auto_detect_interface": True,
        },
        "experimental": {
            "clash_api": {
                "external_controller": "127.0.0.1:9090",
                "default_mode": "rule",
            }
        },
    }
    return json.dumps(data, ensure_ascii=False, indent=2, separators=(",", ": ")) + "\n"


def fetch_upstream(marzban_url: str, token: str, headers: Mapping[str, str]) -> tuple[int, dict[str, str], bytes]:
    url = f"{marzban_url.rstrip('/')}/sub/{token}"
    req = Request(url, headers={k: v for k, v in headers.items() if v})
    with urlopen(req, timeout=15) as response:
        return response.status, dict(response.headers.items()), response.read()


class SingBoxHandler(BaseHTTPRequestHandler):
    marzban_url: str

    def log_message(self, format: str, *args: object) -> None:
        return

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
            body = build_singbox_json(raw).encode("utf-8")
        except HTTPError as exc:
            self.send_bytes(exc.code, dict(exc.headers.items()), exc.read() or b"upstream error\n")
            return
        except (URLError, TimeoutError, ValueError) as exc:
            self.send_bytes(502, {"Content-Type": "text/plain"}, f"sing-box upstream unavailable: {exc}\n".encode("utf-8"))
            return
        headers = {name: value for name, value in upstream_headers.items() if name.lower() in PASS_HEADERS}
        headers["Content-Type"] = "application/json; charset=utf-8"
        self.send_bytes(200, headers, body)

    def send_bytes(self, status: int, headers: Mapping[str, str], body: bytes) -> None:
        self.send_response(status)
        self.send_header("Cache-Control", "no-store")
        for name, value in headers.items():
            if name.lower() not in {"content-length", "transfer-encoding", "connection"}:
                self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_singbox_server(listen: str, port: int, marzban_url: str) -> ThreadingHTTPServer:
    class Handler(SingBoxHandler):
        pass

    Handler.marzban_url = marzban_url
    return ThreadingHTTPServer((listen, port), Handler)


def serve_singbox(args: argparse.Namespace) -> int:
    server = make_singbox_server(args.listen, args.port, args.marzban_url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0
