from __future__ import annotations

import argparse
import ipaddress
import json
import re
import socket
from collections.abc import Mapping
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlparse

from ._http import PASS_HEADERS, AdapterHandler, fetch_upstream, first_query_value, parse_link_netloc
from .config import LinkRayConfig
from .native import b64decode_text, decode_subscription_links
from .protocol_prefs import DEFAULT_PROTOCOL_PREFS_PATH, ProtocolPreferences
from .rules import COMPACT_CN_DOMAIN_SUFFIXES, FOREIGN_DOMAIN_SUFFIXES, RouteRules, load_route_rules
from .snell_runtime import DEFAULT_RUNTIME_DIR as SNELL_RUNTIME_DIR
from .snell_runtime import SnellUser


TOKEN_RE = re.compile(r"^/sub/([^/]+)/clash-meta/?$")
RELAY_PORT_OFFSET = 100
FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")


def yaml_scalar(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if (
        text
        and text.lower() not in {"true", "false", "null", "yes", "no", "on", "off"}
        and "\n" not in text
        and ": " not in text
        and not text.startswith(("*", "&", "!", "- ", "? ", "{", "}", "[", "]", ",", "#", "|", ">", "@", "`", "\"", "'"))
    ):
        return text
    return json.dumps(text, ensure_ascii=False)


def yaml_lines(value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.extend(yaml_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {yaml_scalar(item)}")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                entries = list(item.items())
                if not entries:
                    lines.append(f"{prefix}- {{}}")
                    continue
                first_key, first_value = entries[0]
                if isinstance(first_value, (dict, list)):
                    lines.append(f"{prefix}- {first_key}:")
                    lines.extend(yaml_lines(first_value, indent + 4))
                else:
                    lines.append(f"{prefix}- {first_key}: {yaml_scalar(first_value)}")
                for key, child in entries[1:]:
                    if isinstance(child, (dict, list)):
                        lines.append(f"{prefix}  {key}:")
                        lines.extend(yaml_lines(child, indent + 4))
                    else:
                        lines.append(f"{prefix}  {key}: {yaml_scalar(child)}")
            else:
                lines.append(f"{prefix}- {yaml_scalar(item)}")
        return lines
    return [f"{prefix}{yaml_scalar(value)}"]


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


def proxy_server_domains(proxies: list[dict[str, Any]], config: LinkRayConfig | None = None) -> list[str]:
    domains: list[str] = []
    if config and config.domain and not is_ip_address(config.domain):
        domains.append(config.domain)
    for proxy in proxies:
        server = proxy.get("server")
        if isinstance(server, str) and server and not is_ip_address(server):
            domains.append(server)
    return sorted(set(domains))


def proxy_server_hosts(domains: list[str]) -> dict[str, str]:
    hosts: dict[str, str] = {}
    for domain in domains:
        address = public_ipv4_for_host(domain)
        if address:
            hosts[domain] = address
    return hosts


def proxy_server_ip_exclusions(proxies: list[dict[str, Any]], host_map: Mapping[str, str]) -> list[str]:
    addresses: set[str] = set(host_map.values())
    for proxy in proxies:
        server = proxy.get("server")
        if isinstance(server, str) and is_ip_address(server):
            addresses.add(server)
    return [f"{address}/32" for address in sorted(addresses)]


def proxy_name(parsed, host: str) -> str:
    return unquote(parsed.fragment) or host


def tls_common(query: Mapping[str, list[str]], fallback_server_name: str) -> dict[str, Any]:
    server_name = first_query_value(query, "sni", "servername") or fallback_server_name
    common: dict[str, Any] = {
        "tls": True,
        "servername": server_name,
        "skip-cert-verify": first_query_value(query, "allowInsecure", "skip-cert-verify") in {"1", "true", "True"},
        "client-fingerprint": first_query_value(query, "fp", "fingerprint") or "chrome",
    }
    alpn = first_query_value(query, "alpn")
    if alpn:
        common["alpn"] = [item.strip() for item in alpn.split(",") if item.strip()]
    return common


def transport_options(query: Mapping[str, list[str]], network: str, fallback_host: str) -> dict[str, Any] | None:
    if network == "tcp":
        return None
    if network == "ws":
        return {
            "network": "ws",
            "ws-opts": {
                "path": first_query_value(query, "path") or "/",
                "headers": {"Host": first_query_value(query, "host") or fallback_host},
            },
        }
    if network == "grpc":
        return {
            "network": "grpc",
            "grpc-opts": {
                "grpc-service-name": first_query_value(query, "serviceName", "service_name") or "grpc",
            },
        }
    if network == "httpupgrade":
        return {
            "network": "ws",
            "ws-opts": {
                "path": first_query_value(query, "path") or "/",
                "headers": {"Host": first_query_value(query, "host") or fallback_host},
                "v2ray-http-upgrade": True,
            },
        }
    if network == "xhttp":
        return {
            "network": "xhttp",
            "xhttp-opts": {
                "path": first_query_value(query, "path") or "/",
                "host": first_query_value(query, "host") or fallback_host,
            },
        }
    return None


def same_parent_domain(left: str, right: str) -> bool:
    left_labels = left.lower().strip(".").split(".")
    right_labels = right.lower().strip(".").split(".")
    if len(left_labels) < 3 or len(right_labels) < 3:
        return False
    return left_labels[-2:] == right_labels[-2:] and left_labels[0] != right_labels[0]


def normalize_relayed_tls_proxy(proxy: dict[str, Any]) -> dict[str, Any]:
    if proxy.get("reality-opts") or proxy.get("tls") is not True:
        return proxy
    server = proxy.get("server")
    servername = proxy.get("servername")
    port = proxy.get("port")
    name = proxy.get("name")
    if not isinstance(server, str) or not isinstance(servername, str):
        return proxy
    if not isinstance(port, int) or port <= RELAY_PORT_OFFSET:
        return proxy
    if not isinstance(name, str):
        return proxy
    if not same_parent_domain(server, servername):
        return proxy
    target_prefix = servername.split(".", 1)[0].lower()
    if not name.lower().startswith(f"{target_prefix}-"):
        return proxy
    proxy["server"] = servername
    proxy["port"] = port - RELAY_PORT_OFFSET
    return proxy


def relay_secondary_node_proxy(proxy: dict[str, Any], config: LinkRayConfig | None) -> dict[str, Any]:
    if not config or not config.domain:
        return proxy
    server = proxy.get("server")
    port = proxy.get("port")
    name = proxy.get("name")
    if not isinstance(server, str) or not isinstance(port, int) or not isinstance(name, str):
        return proxy
    if server == config.domain or is_ip_address(server):
        return proxy
    if not same_parent_domain(config.domain, server):
        return proxy
    target_prefix = server.split(".", 1)[0].lower()
    if not name.lower().startswith(f"{target_prefix}-"):
        return proxy
    proxy = dict(proxy)
    proxy["server"] = config.domain
    proxy["port"] = port + RELAY_PORT_OFFSET
    return proxy


def vless_to_clash(link: str) -> dict[str, Any] | None:
    parsed = urlparse(link)
    host_port = parse_link_netloc(parsed)
    if not host_port or not parsed.username:
        return None
    host, port = host_port
    query = parse_qs(parsed.query)
    network = first_query_value(query, "type") or "tcp"
    security = first_query_value(query, "security") or ""
    if network not in {"tcp", "ws", "grpc", "httpupgrade", "xhttp"}:
        return None
    if security not in {"tls", "reality"}:
        return None
    proxy: dict[str, Any] = {
        "name": proxy_name(parsed, host),
        "type": "vless",
        "server": host,
        "port": port,
        "uuid": unquote(parsed.username),
        "udp": True,
    }
    proxy.update(tls_common(query, host))
    if network == "grpc" and security == "tls":
        proxy.setdefault("alpn", ["h2"])
    if network == "xhttp":
        proxy.setdefault("alpn", ["h2"])
    flow = first_query_value(query, "flow")
    if flow:
        proxy["flow"] = flow
    if security == "reality":
        proxy["reality-opts"] = {
            "public-key": first_query_value(query, "pbk", "public-key", "public_key") or "",
            "short-id": first_query_value(query, "sid", "short-id", "short_id") or "",
        }
    transport = transport_options(query, network, host)
    if transport:
        proxy.update(transport)
    return proxy


def trojan_to_clash(link: str) -> dict[str, Any] | None:
    parsed = urlparse(link)
    host_port = parse_link_netloc(parsed)
    if not host_port or not parsed.username:
        return None
    host, port = host_port
    query = parse_qs(parsed.query)
    network = first_query_value(query, "type") or "tcp"
    if network == "xhttp" or network not in {"tcp", "ws", "grpc", "httpupgrade"}:
        return None
    proxy: dict[str, Any] = {
        "name": proxy_name(parsed, host),
        "type": "trojan",
        "server": host,
        "port": port,
        "password": unquote(parsed.username),
        "udp": True,
    }
    proxy.update(tls_common(query, host))
    if "servername" in proxy:
        proxy["sni"] = proxy.pop("servername")
    if network == "grpc":
        proxy.setdefault("alpn", ["h2"])
    transport = transport_options(query, network, host)
    if transport:
        proxy.update(transport)
    return proxy


def vmess_to_clash(link: str) -> dict[str, Any] | None:
    try:
        data = json.loads(b64decode_text(link.removeprefix("vmess://")))
    except (ValueError, UnicodeDecodeError):
        return None
    host = data.get("add")
    port = data.get("port")
    uuid = data.get("id")
    if not host or not port or not uuid:
        return None
    network = str(data.get("net") or "tcp")
    if network == "xhttp" or network not in {"tcp", "ws", "grpc", "httpupgrade"}:
        return None
    proxy: dict[str, Any] = {
        "name": str(data.get("ps") or host),
        "type": "vmess",
        "server": str(host),
        "port": int(port),
        "uuid": str(uuid),
        "alterId": int(data.get("aid") or 0),
        "cipher": str(data.get("scy") or "auto"),
        "udp": True,
    }
    if data.get("tls") == "tls":
        proxy["tls"] = True
        proxy["servername"] = str(data.get("sni") or data.get("host") or host)
        proxy["skip-cert-verify"] = False
        if network == "grpc":
            proxy["alpn"] = ["h2"]
    query_like = {
        "host": [str(data.get("host") or host)],
        "path": [str(data.get("path") or "/")],
        "serviceName": [str(data.get("path") or data.get("serviceName") or "grpc")],
    }
    transport = transport_options(query_like, network, str(host))
    if transport:
        proxy.update(transport)
    return proxy


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


def shadowsocks_to_clash(link: str) -> dict[str, Any] | None:
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
        "name": proxy_name(parsed, host),
        "type": "ss",
        "server": host,
        "port": port,
        "cipher": method,
        "password": password,
        "udp": True,
    }


def convert_link(link: str) -> dict[str, Any] | None:
    if link.startswith("vless://"):
        return vless_to_clash(link)
    if link.startswith("trojan://"):
        return trojan_to_clash(link)
    if link.startswith("vmess://"):
        return vmess_to_clash(link)
    if link.startswith("ss://"):
        return shadowsocks_to_clash(link)
    return None


def public_stable_proxy(proxy: dict[str, Any]) -> bool:
    proxy_type = proxy.get("type")
    return proxy_type in {"vless", "trojan", "vmess", "ss"}


def legacy_marzban_proxy(proxy: dict[str, Any]) -> bool:
    name = proxy.get("name")
    return isinstance(name, str) and name.startswith("🚀 Marz ")


def clean_rules_base_url(rules_base_url: str | None) -> str:
    return (rules_base_url or "").rstrip("/")


def metacubex_geox_url(rules_base_url: str) -> dict[str, str]:
    return {
        "geoip": f"{rules_base_url}/geoip.dat",
        "geosite": f"{rules_base_url}/geosite.dat",
        "mmdb": f"{rules_base_url}/country.mmdb",
        "asn": f"{rules_base_url}/GeoLite2-ASN.mmdb",
    }


def metacubex_rule_providers(rules_base_url: str) -> dict[str, dict[str, Any]]:
    return {
        "linkray-cn-domain": {
            "type": "http",
            "behavior": "domain",
            "format": "mrs",
            "url": f"{rules_base_url}/mihomo/geosite-cn.mrs",
            "path": "./ruleset/linkray-geosite-cn.mrs",
            "interval": 86400,
            "proxy": "DIRECT",
        },
        "linkray-cn-ip": {
            "type": "http",
            "behavior": "ipcidr",
            "format": "mrs",
            "url": f"{rules_base_url}/mihomo/geoip-cn.mrs",
            "path": "./ruleset/linkray-geoip-cn.mrs",
            "interval": 86400,
            "proxy": "DIRECT",
        },
    }


DEFAULT_URL_TEST_URL = "https://cp.cloudflare.com/generate_204"


def health_check_url_from_rules_base(rules_base_url: str) -> str:
    return DEFAULT_URL_TEST_URL


def build_proxy_groups(names: list[str], url_test_url: str = DEFAULT_URL_TEST_URL) -> list[dict[str, Any]]:
    default = names[0] if names else "DIRECT"
    selector = names if names else ["DIRECT"]
    return [
        {"name": "手动切换", "type": "select", "proxies": selector},
        {
            "name": "自动选择",
            "type": "url-test",
            "proxies": selector,
            "url": url_test_url,
            "interval": 300,
            "tolerance": 50,
        },
        {"name": "全球代理", "type": "select", "proxies": ["手动切换", "自动选择", *selector]},
        {"name": "Google", "type": "select", "proxies": ["全球代理", "自动选择", "手动切换", *selector]},
        {"name": "YouTube", "type": "select", "proxies": ["全球代理", "自动选择", "手动切换", *selector]},
        {"name": "Telegram", "type": "select", "proxies": ["全球代理", "自动选择", "手动切换", *selector]},
        {"name": "Facebook", "type": "select", "proxies": ["全球代理", "自动选择", "手动切换", *selector]},
        {"name": "X", "type": "select", "proxies": ["全球代理", "自动选择", "手动切换", *selector]},
        {"name": "TikTok", "type": "select", "proxies": ["全球代理", "自动选择", "手动切换", *selector]},
        {"name": "OpenAI", "type": "select", "proxies": ["全球代理", "自动选择", "手动切换", *selector]},
        {"name": "ClaudeAI", "type": "select", "proxies": ["全球代理", "自动选择", "手动切换", *selector]},
        {"name": "国内站点", "type": "select", "proxies": ["DIRECT", "全球代理", default]},
        {"name": "本地直连", "type": "select", "proxies": ["DIRECT", "全球代理"]},
        {"name": "漏网之鱼", "type": "select", "proxies": ["全球代理", "自动选择", "手动切换", "DIRECT", *selector]},
    ]


def build_rules(route_rules: RouteRules, use_rule_sets: bool = False) -> list[str]:
    rules = [
        "DOMAIN-SUFFIX,google.com,Google",
        "DOMAIN-SUFFIX,gstatic.com,Google",
        "DOMAIN-SUFFIX,youtube.com,YouTube",
        "DOMAIN-SUFFIX,ytimg.com,YouTube",
        "DOMAIN-SUFFIX,telegram.org,Telegram",
        "DOMAIN-SUFFIX,t.me,Telegram",
        "DOMAIN-SUFFIX,facebook.com,Facebook",
        "DOMAIN-SUFFIX,fbcdn.net,Facebook",
        "DOMAIN-SUFFIX,x.com,X",
        "DOMAIN-SUFFIX,twitter.com,X",
        "DOMAIN-SUFFIX,tiktok.com,TikTok",
        "DOMAIN-KEYWORD,tiktok,TikTok",
        "DOMAIN-SUFFIX,openai.com,OpenAI",
        "DOMAIN-SUFFIX,chatgpt.com,OpenAI",
        "DOMAIN-SUFFIX,anthropic.com,ClaudeAI",
        "DOMAIN-SUFFIX,claude.ai,ClaudeAI",
        "DOMAIN-SUFFIX,local,本地直连",
        "DOMAIN-SUFFIX,lan,本地直连",
        "IP-CIDR,10.0.0.0/8,本地直连",
        "IP-CIDR,172.16.0.0/12,本地直连",
        "IP-CIDR,192.168.0.0/16,本地直连",
        "IP-CIDR,127.0.0.0/8,本地直连",
        "IP-CIDR,169.254.0.0/16,本地直连",
    ]
    for domain in FOREIGN_DOMAIN_SUFFIXES:
        rules.append(f"DOMAIN-SUFFIX,{domain},全球代理")
    for domain in COMPACT_CN_DOMAIN_SUFFIXES:
        rules.append(f"DOMAIN-SUFFIX,{domain},国内站点")
    for cidr in route_rules.cn_ip_cidrs:
        rules.append(f"IP-CIDR,{cidr},国内站点")
    if use_rule_sets:
        rules.append("RULE-SET,linkray-cn-domain,国内站点")
        rules.append("RULE-SET,linkray-cn-ip,国内站点")
    rules.append("GEOIP,CN,国内站点")
    rules.append("MATCH,漏网之鱼")
    return rules


def build_clash_meta_yaml(
    subscription_payload: bytes,
    route_rules: RouteRules | None = None,
    config: LinkRayConfig | None = None,
    snell_user: SnellUser | None = None,
    protocol_preferences: ProtocolPreferences | None = None,
    rules_base_url: str | None = None,
    public_only: bool = False,
) -> str:
    proxies: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in decode_subscription_links(subscription_payload):
        proxy = convert_link(link)
        if not proxy:
            continue
        proxy = normalize_relayed_tls_proxy(proxy)
        if legacy_marzban_proxy(proxy):
            continue
        if public_only and not public_stable_proxy(proxy):
            continue
        if public_only:
            proxy = relay_secondary_node_proxy(proxy, config)
        name = proxy.get("name")
        if not isinstance(name, str) or not name or name in seen:
            continue
        seen.add(name)
        proxies.append(proxy)
    names = [str(proxy["name"]) for proxy in proxies]
    effective_rules = route_rules or load_route_rules()
    clean_base = clean_rules_base_url(rules_base_url)
    url_test_url = health_check_url_from_rules_base(clean_base) if clean_base else DEFAULT_URL_TEST_URL
    server_domains = proxy_server_domains(proxies, config)
    host_map = proxy_server_hosts(server_domains)
    if public_only and host_map:
        for proxy in proxies:
            server = proxy.get("server")
            if isinstance(server, str) and server in host_map:
                proxy["server"] = host_map[server]
    data = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "warning",
        "ipv6": False,
        "tcp-concurrent": True,
        "unified-delay": True,
        "profile": {"store-selected": True, "store-fake-ip": False},
        "dns": {
            "enable": True,
            "listen": "127.0.0.1:1053",
            "ipv6": False,
            "enhanced-mode": "fake-ip",
            "fake-ip-filter": [
                "*.lan",
                "*.local",
                "*.localhost",
                "localhost.ptlogin2.qq.com",
                "dns.google",
                "time.*.com",
                "ntp.*.com",
                *server_domains,
            ],
            "default-nameserver": ["223.5.5.5", "119.29.29.29"],
            "nameserver": ["https://doh.pub/dns-query", "https://dns.alidns.com/dns-query"],
            "direct-nameserver": [
                "https://doh.pub/dns-query",
                "https://dns.alidns.com/dns-query",
                "223.5.5.5",
                "119.29.29.29",
            ],
            "proxy-server-nameserver": ["223.5.5.5", "119.29.29.29"],
            "nameserver-policy": {domain: "223.5.5.5" for domain in server_domains},
            "respect-rules": True,
        },
        "proxies": proxies,
        "proxy-groups": build_proxy_groups(names, url_test_url=url_test_url),
        "rules": build_rules(effective_rules, use_rule_sets=bool(clean_base)),
    }
    if host_map:
        data["hosts"] = host_map
    route_exclusions = proxy_server_ip_exclusions(proxies, host_map) if public_only else []
    if route_exclusions:
        data["tun"] = {"route-exclude-address": route_exclusions}
    if clean_base:
        data["geox-url"] = metacubex_geox_url(clean_base)
        data["rule-providers"] = metacubex_rule_providers(clean_base)
    return "\n".join(yaml_lines(data)) + "\n"


class ClashHandler(AdapterHandler):
    server_domain = ""
    snell_runtime_dir = SNELL_RUNTIME_DIR
    snell_reload_command = ""
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
            config = LinkRayConfig(domain=self.server_domain) if self.server_domain else None
            body = build_clash_meta_yaml(
                raw,
                config=config,
                rules_base_url=self.rules_base_url,
                public_only=True,
            ).encode("utf-8")
        except HTTPError as exc:
            self.send_bytes(exc.code, dict(exc.headers.items()), exc.read() or b"upstream error\n")
            return
        except (URLError, TimeoutError, ValueError) as exc:
            self.send_bytes(502, {"Content-Type": "text/plain"}, f"clash upstream unavailable: {exc}\n".encode("utf-8"))
            return
        headers = {name: value for name, value in upstream_headers.items() if name.lower() in PASS_HEADERS}
        headers["Content-Type"] = "text/yaml; charset=utf-8"
        self.send_bytes(200, headers, body)


def make_clash_server(
    listen: str,
    port: int,
    marzban_url: str,
    server_domain: str = "",
    snell_runtime_dir=SNELL_RUNTIME_DIR,
    snell_reload_command: str = "",
    protocol_preferences_path=DEFAULT_PROTOCOL_PREFS_PATH,
    rules_base_url: str = "",
) -> ThreadingHTTPServer:
    class Handler(ClashHandler):
        pass

    Handler.marzban_url = marzban_url
    Handler.server_domain = server_domain
    Handler.snell_runtime_dir = snell_runtime_dir
    Handler.snell_reload_command = snell_reload_command
    Handler.protocol_preferences_path = protocol_preferences_path
    Handler.rules_base_url = rules_base_url
    return ThreadingHTTPServer((listen, port), Handler)


def serve_clash(args: argparse.Namespace) -> int:
    server = make_clash_server(
        args.listen,
        args.port,
        args.marzban_url,
        server_domain=getattr(args, "server_domain", ""),
        snell_runtime_dir=getattr(args, "snell_runtime_dir", SNELL_RUNTIME_DIR),
        snell_reload_command=getattr(args, "snell_reload_command", ""),
        rules_base_url=getattr(args, "rules_base_url", ""),
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0
