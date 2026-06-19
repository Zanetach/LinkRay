from __future__ import annotations

import base64
import ipaddress
import json
import socket
from urllib.parse import parse_qs, unquote, urlparse

from .config import DEFAULT_PORTS, RELAY_PORT_OFFSET, relay_port

FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")


def b64decode_text(value: str) -> str:
    clean = value.strip()
    padding = "=" * (-len(clean) % 4)
    return base64.urlsafe_b64decode((clean + padding).encode("ascii")).decode("utf-8")


def decode_subscription_links(payload: bytes) -> list[str]:
    text = payload.decode("utf-8", errors="ignore").strip()
    if "://" not in text:
        text = b64decode_text(text)
    return [line.strip() for line in text.splitlines() if "://" in line]


def encode_subscription_links(links: list[str]) -> bytes:
    text = "\n".join(links).encode("utf-8")
    return base64.b64encode(text)


def native_link_name(link: str) -> str:
    if link.startswith("vmess://"):
        try:
            data = json.loads(b64decode_text(link.removeprefix("vmess://")))
        except (ValueError, UnicodeDecodeError):
            return ""
        return str(data.get("ps") or "")
    return unquote(urlparse(link).fragment or "")


def legacy_marzban_native_link(link: str) -> bool:
    return native_link_name(link).startswith("🚀 Marz ")


def first_query_value(query: dict[str, list[str]], *names: str) -> str:
    for name in names:
        values = query.get(name)
        if values and values[0]:
            return values[0]
    return ""


def parsed_port(parsed) -> int | None:
    try:
        return parsed.port
    except ValueError:
        return None


def is_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def same_parent_domain(left: str, right: str) -> bool:
    left_labels = left.lower().strip(".").split(".")
    right_labels = right.lower().strip(".").split(".")
    if len(left_labels) < 3 or len(right_labels) < 3:
        return False
    return left_labels[-2:] == right_labels[-2:] and left_labels[0] != right_labels[0]


def should_relay_secondary_node(name: str, server: str, master_domain: str) -> bool:
    if not master_domain or not server or server == master_domain or is_ip_address(server):
        return False
    if not same_parent_domain(master_domain, server):
        return False
    target_prefix = server.split(".", 1)[0].lower()
    return name.lower().startswith(f"{target_prefix}-")


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


def rewrite_url_server_to_public_ip(link: str) -> str:
    parsed = urlparse(link)
    host = parsed.hostname
    port = parsed_port(parsed)
    if not host or not port or is_ip_address(host):
        return link
    address = public_ipv4_for_host(host)
    if not address:
        return link
    if "@" not in parsed.netloc:
        return link
    userinfo, _server = parsed.netloc.rsplit("@", 1)
    return parsed._replace(netloc=f"{userinfo}@{address}:{port}").geturl()


def rewrite_vmess_server_to_public_ip(link: str) -> str:
    try:
        data = json.loads(b64decode_text(link.removeprefix("vmess://")))
    except (ValueError, UnicodeDecodeError):
        return link
    host = data.get("add")
    if not isinstance(host, str) or not host or is_ip_address(host):
        return link
    address = public_ipv4_for_host(host)
    if not address:
        return link
    data["add"] = address
    encoded = base64.urlsafe_b64encode(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    return f"vmess://{encoded}"


def rewrite_server_to_public_ip(link: str) -> str:
    if link.startswith(("vless://", "trojan://", "ss://")):
        return rewrite_url_server_to_public_ip(link)
    if link.startswith("vmess://"):
        return rewrite_vmess_server_to_public_ip(link)
    return link


def relay_secondary_url_link(link: str, master_domain: str, *, offset: int = RELAY_PORT_OFFSET) -> str:
    parsed = urlparse(link)
    host = parsed.hostname
    port = parsed_port(parsed)
    name = parsed.fragment or ""
    if not host or not port or not should_relay_secondary_node(name, host, master_domain):
        return link
    if port == DEFAULT_PORTS["vless_tls"]:
        return link
    if "@" not in parsed.netloc:
        return link
    userinfo, _server = parsed.netloc.rsplit("@", 1)
    return parsed._replace(netloc=f"{userinfo}@{master_domain}:{relay_port(port, 1, offset)}").geturl()


def relay_secondary_vmess_link(link: str, master_domain: str, *, offset: int = RELAY_PORT_OFFSET) -> str:
    try:
        data = json.loads(b64decode_text(link.removeprefix("vmess://")))
    except (ValueError, UnicodeDecodeError):
        return link
    host = data.get("add")
    name = data.get("ps") or ""
    try:
        port = int(data.get("port") or 0)
    except (TypeError, ValueError):
        return link
    if not isinstance(host, str) or not should_relay_secondary_node(str(name), host, master_domain):
        return link
    if port == DEFAULT_PORTS["vless_tls"]:
        return link
    data["add"] = master_domain
    data["port"] = str(relay_port(port, 1, offset))
    encoded = base64.urlsafe_b64encode(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    return f"vmess://{encoded}"


def relay_secondary_node_link(link: str, master_domain: str, *, offset: int = RELAY_PORT_OFFSET) -> str:
    if link.startswith(("vless://", "trojan://", "ss://")):
        return relay_secondary_url_link(link, master_domain, offset=offset)
    if link.startswith("vmess://"):
        return relay_secondary_vmess_link(link, master_domain, offset=offset)
    return link


def stable_vless(link: str) -> bool:
    parsed = urlparse(link)
    query = parse_qs(parsed.query)
    network = first_query_value(query, "type") or "tcp"
    security = first_query_value(query, "security")
    if security == "reality":
        return network == "tcp"
    return network in {"tcp", "ws"} and security in {"tls", ""}


def public_stable_vless(link: str) -> bool:
    parsed = urlparse(link)
    query = parse_qs(parsed.query)
    network = first_query_value(query, "type") or "tcp"
    security = first_query_value(query, "security")
    return parsed_port(parsed) == 443 and network in {"tcp", "ws"} and security == "tls"


def stable_trojan(link: str) -> bool:
    parsed = urlparse(link)
    query = parse_qs(parsed.query)
    network = first_query_value(query, "type") or "tcp"
    return network in {"tcp", "ws"}


def public_stable_trojan(link: str) -> bool:
    parsed = urlparse(link)
    query = parse_qs(parsed.query)
    network = first_query_value(query, "type") or "tcp"
    return parsed_port(parsed) == 443 and network in {"tcp", "ws"}


def stable_vmess(link: str) -> bool:
    try:
        data = json.loads(b64decode_text(link.removeprefix("vmess://")))
    except (ValueError, UnicodeDecodeError):
        return False
    return (data.get("net") or "tcp") in {"tcp", "ws"}


def public_stable_vmess(link: str) -> bool:
    try:
        data = json.loads(b64decode_text(link.removeprefix("vmess://")))
    except (ValueError, UnicodeDecodeError):
        return False
    try:
        port = int(data.get("port") or 0)
    except (TypeError, ValueError):
        return False
    return port == 443 and data.get("tls") == "tls" and (data.get("net") or "tcp") in {"tcp", "ws"}


def stable_native_link(link: str) -> bool:
    if link.startswith("vless://"):
        return stable_vless(link)
    if link.startswith("trojan://"):
        return stable_trojan(link)
    if link.startswith("vmess://"):
        return stable_vmess(link)
    if link.startswith("ss://"):
        return True
    return False


def public_stable_native_link(link: str) -> bool:
    if link.startswith("vless://"):
        return public_stable_vless(link)
    if link.startswith("trojan://"):
        return public_stable_trojan(link)
    if link.startswith("vmess://"):
        return public_stable_vmess(link)
    return False


def build_stable_native_subscription(
    payload: bytes,
    *,
    public_only: bool = True,
    resolve_public_hosts: bool = False,
) -> bytes:
    links: list[str] = []
    seen: set[str] = set()
    for link in decode_subscription_links(payload):
        if public_only:
            if not public_stable_native_link(link):
                continue
        elif not stable_native_link(link):
            continue
        if resolve_public_hosts:
            link = rewrite_server_to_public_ip(link)
        name = urlparse(link).fragment or link
        if name in seen:
            continue
        seen.add(name)
        links.append(link)
    return encode_subscription_links(links)
