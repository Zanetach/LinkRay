from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .config import (
    DEFAULT_PORTS,
    PORT_KEYS,
    SINGBOX_DEFAULT_PORTS,
    SINGBOX_PORT_KEYS,
    SNELL_DEFAULT_PORTS,
    SNELL_PORT_KEYS,
    TLS_FALLBACK_PORT_KEYS,
    NodeHost,
)
from .render import ACTIVE_INBOUND_TAGS

SINGBOX_INBOUND_TAGS = ("Hysteria2", "TUIC", "AnyTLS")
SNELL_INBOUND_TAGS = ("Snell",)


@dataclass(frozen=True)
class PortProbeResult:
    node: str
    domain: str
    runtime: str
    transport: str
    inbound_tag: str
    port: int
    status: str
    latency_ms: int | None
    error: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "node": self.node,
            "domain": self.domain,
            "runtime": self.runtime,
            "transport": self.transport,
            "inbound_tag": self.inbound_tag,
            "port": self.port,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


@dataclass(frozen=True)
class PortSpec:
    key: str
    runtime: str
    transport: str
    inbound_tag: str
    port: int


def _runtime_specs(
    runtime: str,
    keys: Sequence[str],
    tags: Sequence[str],
    defaults: dict[str, int],
    overrides: Sequence[tuple[str, int]] | None = None,
    transports: dict[str, str] | None = None,
) -> list[PortSpec]:
    tag_map = dict(zip(keys, tags))
    ports = dict(defaults)
    if overrides:
        ports.update(dict(overrides))
    transport_map = transports or {}
    public_port = ports.get("vless_tls")
    return [
        PortSpec(
            key=key,
            runtime=runtime,
            transport=transport_map.get(key, "tcp"),
            inbound_tag=tag_map[key],
            port=public_port if runtime == "xray" and key in TLS_FALLBACK_PORT_KEYS and public_port else ports[key],
        )
        for key in keys
    ]


def port_specs(
    inbound_ports: Sequence[tuple[str, int]] | None = None,
    singbox_inbound_ports: Sequence[tuple[str, int]] | None = None,
    snell_inbound_ports: Sequence[tuple[str, int]] | None = None,
) -> list[PortSpec]:
    return [
        *_runtime_specs("xray", PORT_KEYS, ACTIVE_INBOUND_TAGS, DEFAULT_PORTS, inbound_ports),
        *_runtime_specs(
            "sing-box",
            SINGBOX_PORT_KEYS,
            SINGBOX_INBOUND_TAGS,
            SINGBOX_DEFAULT_PORTS,
            singbox_inbound_ports,
            transports={"hysteria2": "udp", "tuic": "udp"},
        ),
        *_runtime_specs("snell", SNELL_PORT_KEYS, SNELL_INBOUND_TAGS, SNELL_DEFAULT_PORTS, snell_inbound_ports),
    ]


def tcp_probe(host: str, port: int, timeout: float) -> tuple[str, int | None, str | None]:
    start = time.monotonic()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
    except OSError as exc:
        return "closed", None, str(exc)
    finally:
        sock.close()
    return "open", max(0, round((time.monotonic() - start) * 1000)), None


def udp_probe(host: str, port: int, timeout: float) -> tuple[str, int | None, str | None]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        sock.send(b"\x00")
    except OSError as exc:
        return "closed", None, str(exc)
    finally:
        sock.close()
    return "open", None, None


def probe_spec(host: str, spec: PortSpec, timeout: float) -> tuple[str, int | None, str | None]:
    if spec.transport == "udp":
        return udp_probe(host, spec.port, timeout=timeout)
    return tcp_probe(host, spec.port, timeout=timeout)


def probe_ports(
    nodes: Sequence[NodeHost],
    timeout: float = 2.0,
    inbound_ports: Sequence[tuple[str, int]] | None = None,
    singbox_inbound_ports: Sequence[tuple[str, int]] | None = None,
    snell_inbound_ports: Sequence[tuple[str, int]] | None = None,
) -> dict[str, object]:
    results: list[PortProbeResult] = []
    specs = port_specs(
        inbound_ports,
        singbox_inbound_ports=singbox_inbound_ports,
        snell_inbound_ports=snell_inbound_ports,
    )
    for node in nodes:
        node.validate()
        for spec in specs:
            status, latency_ms, error = probe_spec(node.domain, spec, timeout=timeout)
            results.append(
                PortProbeResult(
                    node=node.name,
                    domain=node.domain,
                    runtime=spec.runtime,
                    transport=spec.transport,
                    inbound_tag=spec.inbound_tag,
                    port=spec.port,
                    status=status,
                    latency_ms=latency_ms,
                    error=error,
                )
            )

    open_count = sum(1 for item in results if item.status == "open")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "open": open_count,
        "closed": len(results) - open_count,
        "results": [item.to_json() for item in results],
    }


def write_ports_json(
    nodes: Sequence[NodeHost],
    output: Path,
    timeout: float = 2.0,
    inbound_ports: Sequence[tuple[str, int]] | None = None,
    singbox_inbound_ports: Sequence[tuple[str, int]] | None = None,
    snell_inbound_ports: Sequence[tuple[str, int]] | None = None,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    data = probe_ports(
        nodes,
        timeout=timeout,
        inbound_ports=inbound_ports,
        singbox_inbound_ports=singbox_inbound_ports,
        snell_inbound_ports=snell_inbound_ports,
    )
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output
