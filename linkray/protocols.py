from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ProtocolCapability:
    key: str
    name: str
    runtime: str
    status: str
    transport: str
    security: str
    subscription_formats: tuple[str, ...]
    notes: str


PROTOCOL_CAPABILITIES: tuple[ProtocolCapability, ...] = (
    ProtocolCapability(
        "vless_tls",
        "VLESS TLS Vision",
        "xray",
        "supported",
        "tcp",
        "tls",
        ("native", "clash-meta", "egern", "shadowrocket", "sing-box"),
        "LinkRay panel-managed Xray inbound with user and traffic stats.",
    ),
    ProtocolCapability(
        "vless_reality",
        "VLESS Reality Vision",
        "xray",
        "supported",
        "tcp",
        "reality",
        ("native", "clash-meta", "sing-box"),
        "LinkRay panel-managed Xray inbound with user and traffic stats.",
    ),
    ProtocolCapability(
        "vless_grpc_reality",
        "VLESS Reality gRPC",
        "xray",
        "supported",
        "grpc",
        "reality",
        ("native", "clash-meta", "sing-box"),
        "LinkRay panel-managed Xray inbound with user and traffic stats.",
    ),
    ProtocolCapability(
        "trojan_tls",
        "Trojan TLS",
        "xray",
        "supported",
        "tcp",
        "tls",
        ("native", "clash-meta", "egern", "shadowrocket", "sing-box"),
        "LinkRay panel-managed Xray inbound with user and traffic stats.",
    ),
    ProtocolCapability(
        "vmess_tls",
        "VMess TLS",
        "xray",
        "supported",
        "tcp",
        "tls",
        ("native", "clash-meta", "sing-box"),
        "LinkRay panel-managed Xray inbound with user and traffic stats.",
    ),
    ProtocolCapability(
        "shadowsocks",
        "Shadowsocks",
        "xray",
        "supported",
        "tcp/udp",
        "none",
        ("native", "clash-meta", "egern", "shadowrocket", "sing-box"),
        "LinkRay panel-managed Xray inbound with user and traffic stats.",
    ),
    ProtocolCapability(
        "vless_ws_tls",
        "VLESS WS TLS",
        "xray",
        "supported",
        "websocket",
        "tls",
        ("native", "clash-meta", "egern", "shadowrocket", "sing-box"),
        "LinkRay panel-managed Xray inbound with user and traffic stats.",
    ),
    ProtocolCapability(
        "vless_grpc_tls",
        "VLESS gRPC TLS",
        "xray",
        "supported",
        "grpc",
        "tls",
        ("native", "clash-meta", "sing-box"),
        "LinkRay panel-managed Xray inbound with user and traffic stats.",
    ),
    ProtocolCapability(
        "vless_xhttp_reality",
        "VLESS XHTTP Reality",
        "xray",
        "supported",
        "xhttp",
        "reality",
        ("native", "sing-box"),
        "Xray inbound is rendered; some clients still have unstable XHTTP delay tests.",
    ),
    ProtocolCapability(
        "vmess_ws_tls",
        "VMess WS TLS",
        "xray",
        "supported",
        "websocket",
        "tls",
        ("native", "clash-meta", "egern", "shadowrocket", "sing-box"),
        "LinkRay panel-managed Xray inbound with user and traffic stats.",
    ),
    ProtocolCapability(
        "vmess_httpupgrade_tls",
        "VMess HTTPUpgrade TLS",
        "xray",
        "supported",
        "httpupgrade",
        "tls",
        ("native", "clash-meta", "sing-box"),
        "LinkRay panel-managed Xray inbound with user and traffic stats.",
    ),
    ProtocolCapability(
        "trojan_grpc_tls",
        "Trojan gRPC TLS",
        "xray",
        "supported",
        "grpc",
        "tls",
        ("native", "clash-meta", "sing-box"),
        "LinkRay panel-managed Xray inbound with user and traffic stats.",
    ),
    ProtocolCapability(
        "hysteria2",
        "Hysteria2",
        "sing-box",
        "experimental",
        "udp",
        "tls",
        ("sing-box",),
        "LinkRay-managed sing-box runtime with generated credentials and LinkRay stats sync.",
    ),
    ProtocolCapability(
        "tuic",
        "TUIC",
        "sing-box",
        "experimental",
        "udp",
        "tls",
        ("sing-box",),
        "LinkRay-managed sing-box runtime with generated credentials and LinkRay stats sync.",
    ),
    ProtocolCapability(
        "anytls",
        "AnyTLS",
        "sing-box",
        "experimental",
        "tcp",
        "tls",
        ("sing-box",),
        "LinkRay-managed sing-box runtime with generated credentials and LinkRay stats sync.",
    ),
    ProtocolCapability(
        "snell",
        "Snell",
        "snell",
        "experimental",
        "tcp",
        "psk",
        ("shadowrocket", "clash-meta"),
        "LinkRay-managed Snell runtime with per-user subscription credentials and LinkRay stats sync via port counters.",
    ),
)


def capabilities_by_status() -> dict[str, list[ProtocolCapability]]:
    grouped: dict[str, list[ProtocolCapability]] = defaultdict(list)
    for capability in PROTOCOL_CAPABILITIES:
        grouped[capability.status].append(capability)
    return dict(grouped)


def protocol_capabilities_json() -> str:
    data = {
        "version": 1,
        "protocols": [
            {**asdict(capability), "subscription_formats": list(capability.subscription_formats)}
            for capability in PROTOCOL_CAPABILITIES
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
