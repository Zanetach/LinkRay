from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, urlparse


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


def first_query_value(query: dict[str, list[str]], *names: str) -> str:
    for name in names:
        values = query.get(name)
        if values and values[0]:
            return values[0]
    return ""


def stable_vless(link: str) -> bool:
    parsed = urlparse(link)
    query = parse_qs(parsed.query)
    network = first_query_value(query, "type") or "tcp"
    security = first_query_value(query, "security")
    if security == "reality":
        return False
    return network in {"tcp", "ws"} and security in {"tls", ""}


def stable_trojan(link: str) -> bool:
    parsed = urlparse(link)
    query = parse_qs(parsed.query)
    network = first_query_value(query, "type") or "tcp"
    return network in {"tcp", "ws"}


def stable_vmess(link: str) -> bool:
    try:
        data = json.loads(b64decode_text(link.removeprefix("vmess://")))
    except (ValueError, UnicodeDecodeError):
        return False
    return (data.get("net") or "tcp") in {"tcp", "ws"}


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


def build_stable_native_subscription(payload: bytes) -> bytes:
    links: list[str] = []
    seen: set[str] = set()
    for link in decode_subscription_links(payload):
        if not stable_native_link(link):
            continue
        name = urlparse(link).fragment or link
        if name in seen:
            continue
        seen.add(name)
        links.append(link)
    return encode_subscription_links(links)
