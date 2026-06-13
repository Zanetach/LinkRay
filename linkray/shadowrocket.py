from __future__ import annotations

import argparse
import json
import re
from dataclasses import replace
from collections.abc import Mapping
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlparse

from ._http import PASS_HEADERS, AdapterHandler, fetch_subscription_username, fetch_upstream, first_query_value, parse_link_netloc
from .config import LinkRayConfig
from .native import (
    b64decode_text,
    decode_subscription_links,
    encode_subscription_links,
    legacy_marzban_native_link,
    public_ipv4_for_host,
    relay_secondary_node_link,
    rewrite_server_to_public_ip,
    stable_native_link,
)
from .protocol_prefs import DEFAULT_PROTOCOL_PREFS_PATH, ProtocolPreferences, enabled_protocols_for_user, load_protocol_preferences
from .rules import COMPACT_CN_DOMAIN_SUFFIXES, FOREIGN_DOMAIN_SUFFIXES, RouteRules, load_route_rules
from .snell_runtime import DEFAULT_RUNTIME_DIR as SNELL_RUNTIME_DIR
from .snell_runtime import SnellUser, ensure_runtime_user, snell_shadowrocket_line


TOKEN_RE = re.compile(r"^/sub/([^/]+)/(shadowrocket|shadowrocket-conf)/?$")


def conf_token(value: object) -> str:
    return str(value).strip().replace(",", " ").replace("\n", " ")


def option(name: str, value: object | None) -> str | None:
    if value is None or value == "":
        return None
    return f"{name}={conf_token(value)}"


def proxy_name(parsed, host: str) -> str:
    return conf_token(unquote(parsed.fragment) or host)


def proxy_line(name: str, protocol: str, host: str, port: int, options: list[str | None]) -> str:
    clean_options = [item for item in options if item]
    return ",".join([f"{conf_token(name)} = {protocol}", conf_token(host), str(port), *clean_options])


def websocket_options(query: Mapping[str, list[str]], fallback_host: str) -> list[str | None]:
    return [
        "obfs=websocket",
        option("obfs-host", first_query_value(query, "host") or fallback_host),
        option("obfs-uri", first_query_value(query, "path") or "/"),
    ]


def vless_to_shadowrocket(link: str) -> tuple[str, str] | None:
    parsed = urlparse(link)
    host_port = parse_link_netloc(parsed)
    if not host_port or not parsed.username:
        return None
    host, port = host_port
    query = parse_qs(parsed.query)
    network = first_query_value(query, "type") or "tcp"
    security = first_query_value(query, "security") or ""
    if security != "tls" or network not in {"tcp", "ws"}:
        return None
    name = proxy_name(parsed, host)
    options = [
        option("password", unquote(parsed.username)),
        "tls=true",
        option("peer", first_query_value(query, "sni", "servername") or host),
        option("flow", first_query_value(query, "flow")),
        "udp-relay=true",
    ]
    if network == "ws":
        options.extend(websocket_options(query, host))
    return name, proxy_line(name, "vless", host, port, options)


def trojan_to_shadowrocket(link: str) -> tuple[str, str] | None:
    parsed = urlparse(link)
    host_port = parse_link_netloc(parsed)
    if not host_port or not parsed.username:
        return None
    host, port = host_port
    query = parse_qs(parsed.query)
    network = first_query_value(query, "type") or "tcp"
    if network not in {"tcp", "ws"}:
        return None
    name = proxy_name(parsed, host)
    options = [
        option("password", unquote(parsed.username)),
        "tls=true",
        option("peer", first_query_value(query, "sni", "servername") or host),
        option("allowInsecure", "1" if first_query_value(query, "allowInsecure", "skip-cert-verify") in {"1", "true", "True"} else "0"),
        "udp-relay=true",
    ]
    if network == "ws":
        options.extend(websocket_options(query, host))
    return name, proxy_line(name, "trojan", host, port, options)


def vmess_to_shadowrocket(link: str) -> tuple[str, str] | None:
    try:
        data = json.loads(b64decode_text(link.removeprefix("vmess://")))
    except (ValueError, UnicodeDecodeError):
        return None
    host = data.get("add")
    port = data.get("port")
    user_id = data.get("id")
    if not host or not port or not user_id:
        return None
    network = data.get("net") or "tcp"
    if data.get("tls") != "tls" or network not in {"tcp", "ws"}:
        return None
    name = conf_token(data.get("ps") or host)
    options = [
        option("password", user_id),
        option("alterId", data.get("aid") or 0),
        option("method", data.get("scy") or "auto"),
        "tls=true",
        option("peer", data.get("sni") or data.get("host") or host),
        "udp-relay=true",
    ]
    if network == "ws":
        query_like = {"host": [data.get("host") or host], "path": [data.get("path") or "/"]}
        options.extend(websocket_options(query_like, str(host)))
    return name, proxy_line(name, "vmess", str(host), int(port), options)


def parse_shadowsocks_full_userinfo(raw: str) -> tuple[str, str, str, int] | None:
    text = raw.split("#", 1)[0].split("?", 1)[0]
    try:
        decoded = b64decode_text(text)
    except (ValueError, UnicodeDecodeError):
        return None
    if "@" not in decoded or ":" not in decoded:
        return None
    userinfo, server = decoded.rsplit("@", 1)
    if ":" not in userinfo or ":" not in server:
        return None
    method, password = userinfo.split(":", 1)
    host, port = server.rsplit(":", 1)
    try:
        return method, password, host, int(port)
    except ValueError:
        return None


def shadowsocks_to_shadowrocket(link: str) -> tuple[str, str] | None:
    parsed = urlparse(link)
    host_port = parse_link_netloc(parsed)
    method = ""
    password = ""
    if host_port and parsed.username:
        host, port = host_port
        userinfo = parsed.username
        if ":" not in userinfo:
            try:
                userinfo = b64decode_text(userinfo)
            except (ValueError, UnicodeDecodeError):
                return None
        if ":" not in userinfo:
            return None
        method, password = userinfo.split(":", 1)
    else:
        parsed_full = parse_shadowsocks_full_userinfo(link.removeprefix("ss://"))
        if not parsed_full:
            return None
        method, password, host, port = parsed_full
    name = proxy_name(parsed, host)
    return name, proxy_line(
        name,
        "ss",
        host,
        port,
        [
            option("method", unquote(method)),
            option("password", unquote(password)),
            "udp-relay=true",
        ],
    )


def convert_link(link: str) -> tuple[str, str] | None:
    if link.startswith("vless://"):
        return vless_to_shadowrocket(link)
    if link.startswith("trojan://"):
        return trojan_to_shadowrocket(link)
    if link.startswith("vmess://"):
        return vmess_to_shadowrocket(link)
    if link.startswith("ss://"):
        return shadowsocks_to_shadowrocket(link)
    return None


def build_policy_groups(names: list[str]) -> list[str]:
    if not names:
        return [
            "手动切换 = select,DIRECT",
            "自动选择 = select,DIRECT",
            "全球代理 = select,DIRECT",
            "国内站点 = select,DIRECT",
            "漏网之鱼 = select,DIRECT",
        ]
    return [
        "手动切换 = select," + ",".join(names),
        "自动选择 = url-test," + ",".join([*names, "url=https://www.gstatic.com/generate_204", "interval=300", "tolerance=50"]),
        "全球代理 = select," + ",".join(["手动切换", "自动选择", *names]),
        "国内站点 = select,DIRECT,全球代理",
        "漏网之鱼 = select,全球代理,自动选择,手动切换,DIRECT",
    ]


def build_rules(route_rules: RouteRules) -> list[str]:
    lines: list[str] = []
    lines.extend(
        [
            "DOMAIN-SUFFIX,local,国内站点",
            "DOMAIN-SUFFIX,lan,国内站点",
            "IP-CIDR,10.0.0.0/8,国内站点",
            "IP-CIDR,172.16.0.0/12,国内站点",
            "IP-CIDR,192.168.0.0/16,国内站点",
            "IP-CIDR,127.0.0.0/8,国内站点",
            "IP-CIDR,169.254.0.0/16,国内站点",
        ]
    )
    for domain in FOREIGN_DOMAIN_SUFFIXES:
        lines.append(f"DOMAIN-SUFFIX,{domain},全球代理")
    for domain in COMPACT_CN_DOMAIN_SUFFIXES:
        lines.append(f"DOMAIN-SUFFIX,{domain},国内站点")
    lines.append("GEOIP,CN,国内站点")
    lines.append("FINAL,漏网之鱼")
    return lines


def build_shadowrocket_conf(
    subscription_payload: bytes,
    route_rules: RouteRules | None = None,
    config: LinkRayConfig | None = None,
    snell_user: SnellUser | None = None,
    protocol_preferences: ProtocolPreferences | None = None,
    public_only: bool = False,
) -> str:
    names: list[str] = []
    proxy_lines: list[str] = []
    seen: set[str] = set()
    for link in decode_subscription_links(subscription_payload):
        if legacy_marzban_native_link(link):
            continue
        if public_only and not stable_native_link(link):
            continue
        if public_only:
            if config:
                link = relay_secondary_node_link(link, config.domain)
            link = rewrite_server_to_public_ip(link)
        converted = convert_link(link)
        if not converted:
            continue
        name, line = converted
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
        proxy_lines.append(line)
    if config and snell_user and "snell" in enabled_protocols_for_user(protocol_preferences, snell_user.name):
        name = f"{snell_user.name}-Snell"
        if name not in seen:
            snell_config = config
            if public_only:
                address = public_ipv4_for_host(config.domain)
                if address:
                    snell_config = replace(config, domain=address)
            seen.add(name)
            names.append(name)
            proxy_lines.append(snell_shadowrocket_line(snell_config, snell_user))

    effective_rules = route_rules or load_route_rules()
    sections = [
        "[General]",
        "bypass-system = true",
        "ipv6 = false",
        "skip-proxy = 127.0.0.1,localhost,*.local,*.lan",
        "dns-server = 223.5.5.5,119.29.29.29,https://doh.pub/dns-query,https://dns.alidns.com/dns-query",
        "",
        "[Proxy]",
        *proxy_lines,
        "",
        "[Proxy Group]",
        *build_policy_groups(names),
        "",
        "[Rule]",
        *build_rules(effective_rules),
        "",
    ]
    return "\n".join(sections)


def build_shadowrocket_subscription(subscription_payload: bytes, config: LinkRayConfig | None = None) -> bytes:
    links: list[str] = []
    seen: set[str] = set()
    for link in decode_subscription_links(subscription_payload):
        if legacy_marzban_native_link(link):
            continue
        if not stable_native_link(link):
            continue
        if config:
            link = relay_secondary_node_link(link, config.domain)
        link = rewrite_server_to_public_ip(link)
        name = urlparse(link).fragment or link
        if name in seen:
            continue
        seen.add(name)
        links.append(link)
    return encode_subscription_links(links)


class ShadowrocketHandler(AdapterHandler):
    server_domain = ""
    snell_runtime_dir = SNELL_RUNTIME_DIR
    snell_reload_command = ""
    protocol_preferences_path = DEFAULT_PROTOCOL_PREFS_PATH

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
        mode = match.group(2)
        try:
            _, upstream_headers, raw = fetch_upstream(self.marzban_url, token, {"Accept": "text/plain"})
            config = LinkRayConfig(domain=self.server_domain) if self.server_domain else None
            if mode == "shadowrocket":
                body = build_shadowrocket_subscription(raw, config=config)
            else:
                snell_user = None
                protocol_preferences = None
                if self.server_domain:
                    username = fetch_subscription_username(self.marzban_url, token)
                    if not username:
                        raise ValueError("missing Marzban username for Snell runtime user")
                    protocol_preferences = load_protocol_preferences(Path(self.protocol_preferences_path))
                    if "snell" in enabled_protocols_for_user(protocol_preferences, username):
                        snell_user, _ = ensure_runtime_user(
                            token,
                            config,
                            runtime_dir=Path(self.snell_runtime_dir),
                            reload_command=self.snell_reload_command or None,
                            name=username,
                        )
                body = build_shadowrocket_conf(
                    raw,
                    config=config,
                    snell_user=snell_user,
                    protocol_preferences=protocol_preferences,
                    public_only=True,
                ).encode("utf-8")
        except HTTPError as exc:
            self.send_bytes(exc.code, dict(exc.headers.items()), exc.read() or b"upstream error\n")
            return
        except (URLError, TimeoutError, ValueError) as exc:
            self.send_bytes(
                502,
                {"Content-Type": "text/plain"},
                f"shadowrocket upstream unavailable: {exc}\n".encode("utf-8"),
            )
            return
        headers = {name: value for name, value in upstream_headers.items() if name.lower() in PASS_HEADERS}
        headers["Content-Type"] = "text/plain; charset=utf-8"
        self.send_bytes(200, headers, body)

def make_shadowrocket_server(
    listen: str,
    port: int,
    marzban_url: str,
    server_domain: str = "",
    snell_runtime_dir=SNELL_RUNTIME_DIR,
    snell_reload_command: str = "",
    protocol_preferences_path=DEFAULT_PROTOCOL_PREFS_PATH,
) -> ThreadingHTTPServer:
    class Handler(ShadowrocketHandler):
        pass

    Handler.marzban_url = marzban_url
    Handler.server_domain = server_domain
    Handler.snell_runtime_dir = snell_runtime_dir
    Handler.snell_reload_command = snell_reload_command
    Handler.protocol_preferences_path = protocol_preferences_path
    return ThreadingHTTPServer((listen, port), Handler)


def serve_shadowrocket(args: argparse.Namespace) -> int:
    server = make_shadowrocket_server(
        args.listen,
        args.port,
        args.marzban_url,
        server_domain=getattr(args, "server_domain", ""),
        snell_runtime_dir=getattr(args, "snell_runtime_dir", SNELL_RUNTIME_DIR),
        snell_reload_command=getattr(args, "snell_reload_command", ""),
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0
