from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import re
import socket
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen

from .rules import RouteRules, load_route_rules


TOKEN_RE = re.compile(r"^/sub/([^/]+)/egern/?$")
PASS_HEADERS = {
    "content-disposition",
    "profile-web-page-url",
    "support-url",
    "profile-title",
    "profile-update-interval",
    "subscription-userinfo",
}


def b64decode_text(value: str) -> str:
    clean = value.strip()
    padding = "=" * (-len(clean) % 4)
    return base64.urlsafe_b64decode((clean + padding).encode("ascii")).decode("utf-8")


def decode_subscription_links(payload: bytes) -> list[str]:
    text = payload.decode("utf-8", errors="ignore").strip()
    if "://" not in text:
        text = b64decode_text(text)
    return [line.strip() for line in text.splitlines() if "://" in line]


def yaml_scalar(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def yaml_lines(value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, list):
        lines: list[str] = []
        for item in value:
            if isinstance(item, dict) and len(item) == 1:
                key, child = next(iter(item.items()))
                lines.append(f"{prefix}- {key}:")
                lines.extend(yaml_lines(child, indent + 4))
            else:
                lines.append(f"{prefix}- {yaml_scalar(item)}")
        return lines
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.extend(yaml_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {yaml_scalar(item)}")
        return lines
    return [f"{prefix}{yaml_scalar(value)}"]


FOREIGN_DOMAIN_SUFFIXES = (
    "dns.google",
    "cloudflare-dns.com",
    "telegram.org",
    "t.me",
    "youtube.com",
    "youtu.be",
    "googlevideo.com",
    "tiktok.com",
    "tiktokv.com",
    "tiktokcdn.com",
    "facebook.com",
    "fb.com",
    "fbcdn.net",
    "instagram.com",
    "whatsapp.com",
    "x.com",
    "twitter.com",
    "t.co",
    "google.com",
    "gstatic.com",
    "googleapis.com",
    "googleusercontent.com",
    "openai.com",
    "chatgpt.com",
    "oaistatic.com",
    "oaiusercontent.com",
    "anthropic.com",
    "claude.ai",
    "github.com",
    "githubusercontent.com",
)


def dump_egern_yaml(
    proxies: list[dict[str, dict[str, Any]]],
    policy_groups: list[dict[str, dict[str, Any]]] | None = None,
    rules: list[dict[str, dict[str, Any]]] | None = None,
) -> str:
    data: dict[str, Any] = {"proxies": proxies}
    if policy_groups is not None:
        data["policy_groups"] = policy_groups
    if rules is not None:
        data["rules"] = rules
    return "\n".join(yaml_lines(data)) + "\n"


def first_query_value(query: Mapping[str, list[str]], *names: str) -> str | None:
    for name in names:
        values = query.get(name)
        if values and values[0]:
            return values[0]
    return None


def resolve_server_address(host: str) -> str:
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    try:
        for item in socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM):
            address = item[4][0]
            if address:
                return address
    except OSError:
        return host
    return host


def base_proxy(name: str, host: str, port: int) -> dict[str, Any]:
    return {
        "name": name,
        "server": resolve_server_address(host),
        "port": port,
        "tfo": False,
        "udp_relay": True,
    }


def tls_transport(query: Mapping[str, list[str]], fallback_sni: str) -> dict[str, Any]:
    sni = first_query_value(query, "sni", "servername") or fallback_sni
    return {
        "tls": {
            "sni": sni,
            "skip_tls_verify": first_query_value(query, "allowInsecure", "skip-cert-verify") in {"1", "true", "True"},
        }
    }


def ws_transport(query: Mapping[str, list[str]], fallback_host: str) -> dict[str, Any]:
    host = first_query_value(query, "host") or fallback_host
    path = first_query_value(query, "path") or "/"
    key = "wss" if first_query_value(query, "security") == "tls" else "ws"
    payload: dict[str, Any] = {"path": path, "headers": {"Host": host}}
    if key == "wss":
        payload["sni"] = first_query_value(query, "sni", "servername") or host
        payload["skip_tls_verify"] = False
    return {key: payload}


def parse_link_netloc(parsed) -> tuple[str, int] | None:
    host = parsed.hostname
    port = parsed.port
    if not host or not port:
        return None
    return host, int(port)


def vless_to_egern(link: str) -> dict[str, dict[str, Any]] | None:
    parsed = urlparse(link)
    host_port = parse_link_netloc(parsed)
    if not host_port or not parsed.username:
        return None
    host, port = host_port
    query = parse_qs(parsed.query)
    network = first_query_value(query, "type") or "tcp"
    security = first_query_value(query, "security") or ""
    if security == "reality" or network in {"grpc", "xhttp", "httpupgrade", "h2"}:
        return None
    item = base_proxy(unquote(parsed.fragment) or host, host, port)
    item["user_id"] = unquote(parsed.username)
    flow = first_query_value(query, "flow")
    if flow:
        item["flow"] = flow
    if network == "ws":
        item["transport"] = ws_transport(query, host)
    elif network == "tcp" and security == "tls":
        item["transport"] = tls_transport(query, host)
    else:
        return None
    return {"vless": item}


def trojan_to_egern(link: str) -> dict[str, dict[str, Any]] | None:
    parsed = urlparse(link)
    host_port = parse_link_netloc(parsed)
    if not host_port or not parsed.username:
        return None
    host, port = host_port
    query = parse_qs(parsed.query)
    network = first_query_value(query, "type") or "tcp"
    if network not in {"tcp", "ws"}:
        return None
    item = base_proxy(unquote(parsed.fragment) or host, host, port)
    item["password"] = unquote(parsed.username)
    item["sni"] = first_query_value(query, "sni", "servername") or host
    item["skip_tls_verify"] = first_query_value(query, "allowInsecure", "skip-cert-verify") in {"1", "true", "True"}
    if network == "ws":
        item["websocket"] = {
            "path": first_query_value(query, "path") or "/",
            "host": first_query_value(query, "host") or host,
        }
    return {"trojan": item}


def vmess_to_egern(link: str) -> dict[str, dict[str, Any]] | None:
    raw = link.removeprefix("vmess://")
    try:
        data = json.loads(b64decode_text(raw))
    except (ValueError, UnicodeDecodeError):
        return None
    host = data.get("add")
    port = data.get("port")
    user_id = data.get("id")
    if not host or not port or not user_id:
        return None
    network = data.get("net") or "tcp"
    if network in {"grpc", "httpupgrade", "h2"}:
        return None
    item = base_proxy(data.get("ps") or host, host, int(port))
    item["user_id"] = str(user_id)
    item["security"] = data.get("scy") or "auto"
    item["legacy"] = False
    if network == "ws":
        key = "wss" if data.get("tls") == "tls" else "ws"
        payload: dict[str, Any] = {
            "path": data.get("path") or "/",
            "headers": {"Host": data.get("host") or host},
        }
        if key == "wss":
            payload["sni"] = data.get("sni") or data.get("host") or host
            payload["skip_tls_verify"] = False
        item["transport"] = {key: payload}
    elif network == "tcp" and data.get("tls") == "tls":
        item["transport"] = {"tls": {"sni": data.get("sni") or data.get("host") or host, "skip_tls_verify": False}}
    else:
        return None
    return {"vmess": item}


def shadowsocks_to_egern(link: str) -> dict[str, dict[str, Any]] | None:
    parsed = urlparse(link)
    host_port = parse_link_netloc(parsed)
    if not host_port:
        return None
    host, port = host_port
    userinfo = parsed.username or ""
    if ":" not in userinfo:
        try:
            userinfo = b64decode_text(userinfo)
        except (ValueError, UnicodeDecodeError):
            return None
    method, password = userinfo.split(":", 1)
    item = base_proxy(unquote(parsed.fragment) or host, host, port)
    item["method"] = unquote(method)
    item["password"] = unquote(password)
    return {"shadowsocks": item}


def convert_link(link: str) -> dict[str, dict[str, Any]] | None:
    if link.startswith("vless://"):
        return vless_to_egern(link)
    if link.startswith("trojan://"):
        return trojan_to_egern(link)
    if link.startswith("vmess://"):
        return vmess_to_egern(link)
    if link.startswith("ss://"):
        return shadowsocks_to_egern(link)
    return None


def proxy_payload(proxy: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if not proxy:
        return None
    return next(iter(proxy.values()))


def proxy_names(proxies: list[dict[str, dict[str, Any]]]) -> list[str]:
    names: list[str] = []
    for proxy in proxies:
        item = proxy_payload(proxy)
        if item and item.get("name"):
            names.append(str(item["name"]))
    return names


def build_policy_groups(proxies: list[dict[str, dict[str, Any]]]) -> list[dict[str, dict[str, Any]]]:
    names = proxy_names(proxies)
    if not names:
        return []
    return [
        {"select": {"name": "手动切换", "policies": names}},
        {
            "url_test": {
                "name": "自动选择",
                "policies": names,
                "url": "https://www.gstatic.com/generate_204",
                "interval": 300,
            }
        },
        {"select": {"name": "全球代理", "policies": ["手动切换", "自动选择", *names]}},
        {"select": {"name": "国内站点", "policies": ["DIRECT", "全球代理"]}},
        {"select": {"name": "漏网之鱼", "policies": ["全球代理", "自动选择", "手动切换", "DIRECT"]}},
    ]


def build_route_rules(route_rules: RouteRules) -> list[dict[str, dict[str, Any]]]:
    rules: list[dict[str, dict[str, Any]]] = []
    for domain in FOREIGN_DOMAIN_SUFFIXES:
        rules.append({"domain_suffix": {"match": domain, "policy": "全球代理"}})
    for domain in route_rules.cn_domain_suffixes:
        rules.append({"domain_suffix": {"match": domain, "policy": "国内站点"}})
    for cidr in route_rules.cn_ip_cidrs:
        rules.append({"ip_cidr": {"match": cidr, "policy": "国内站点"}})
    rules.append({"final": {"policy": "漏网之鱼"}})
    return rules


def apply_prev_hops(proxies: list[dict[str, dict[str, Any]]]) -> None:
    primary = proxy_payload(proxies[0]) if proxies else None
    if not primary:
        return
    primary_name = primary.get("name")
    primary_server = primary.get("server")
    if not primary_name or not primary_server:
        return
    for proxy in proxies[1:]:
        item = proxy_payload(proxy)
        if not item:
            continue
        if item.get("server") != primary_server and "prev_hop" not in item:
            item["prev_hop"] = primary_name


def build_egern_yaml(subscription_payload: bytes, route_rules: RouteRules | None = None) -> str:
    proxies = []
    seen = set()
    for link in decode_subscription_links(subscription_payload):
        converted = convert_link(link)
        if not converted:
            continue
        name = next(iter(converted.values())).get("name")
        if name in seen:
            continue
        seen.add(name)
        proxies.append(converted)
    apply_prev_hops(proxies)
    effective_rules = route_rules or load_route_rules()
    return dump_egern_yaml(
        proxies,
        policy_groups=build_policy_groups(proxies),
        rules=build_route_rules(effective_rules),
    )


def fetch_upstream(marzban_url: str, token: str, headers: Mapping[str, str]) -> tuple[int, dict[str, str], bytes]:
    url = f"{marzban_url.rstrip('/')}/sub/{token}"
    req = Request(url, headers={k: v for k, v in headers.items() if v})
    with urlopen(req, timeout=15) as response:
        return response.status, dict(response.headers.items()), response.read()


class EgernHandler(BaseHTTPRequestHandler):
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
            body = build_egern_yaml(raw).encode("utf-8")
        except HTTPError as exc:
            self.send_bytes(exc.code, dict(exc.headers.items()), exc.read() or b"upstream error\n")
            return
        except (URLError, TimeoutError, ValueError) as exc:
            self.send_bytes(502, {"Content-Type": "text/plain"}, f"egern upstream unavailable: {exc}\n".encode("utf-8"))
            return
        headers = {name: value for name, value in upstream_headers.items() if name.lower() in PASS_HEADERS}
        headers["Content-Type"] = "text/yaml; charset=utf-8"
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


def make_egern_server(listen: str, port: int, marzban_url: str) -> ThreadingHTTPServer:
    class Handler(EgernHandler):
        pass

    Handler.marzban_url = marzban_url
    return ThreadingHTTPServer((listen, port), Handler)


def serve_egern(args: argparse.Namespace) -> int:
    server = make_egern_server(args.listen, args.port, args.marzban_url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0
