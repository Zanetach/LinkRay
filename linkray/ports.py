from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .config import DEFAULT_PORTS, PORT_KEYS, NodeHost
from .render import ACTIVE_INBOUND_TAGS


@dataclass(frozen=True)
class PortProbeResult:
    node: str
    domain: str
    inbound_tag: str
    port: int
    status: str
    latency_ms: int | None
    error: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "node": self.node,
            "domain": self.domain,
            "inbound_tag": self.inbound_tag,
            "port": self.port,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


@dataclass(frozen=True)
class PortSpec:
    key: str
    inbound_tag: str
    port: int


def port_specs(inbound_ports: Sequence[tuple[str, int]] | None = None) -> list[PortSpec]:
    tags = dict(zip(PORT_KEYS, ACTIVE_INBOUND_TAGS))
    ports = dict(DEFAULT_PORTS)
    if inbound_ports:
        ports.update(dict(inbound_ports))
    return [PortSpec(key=key, inbound_tag=tags[key], port=ports[key]) for key in PORT_KEYS]


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


def probe_ports(
    nodes: Sequence[NodeHost],
    timeout: float = 2.0,
    inbound_ports: Sequence[tuple[str, int]] | None = None,
) -> dict[str, object]:
    results: list[PortProbeResult] = []
    specs = port_specs(inbound_ports)
    for node in nodes:
        node.validate()
        for spec in specs:
            status, latency_ms, error = tcp_probe(node.domain, spec.port, timeout=timeout)
            results.append(
                PortProbeResult(
                    node=node.name,
                    domain=node.domain,
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
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    data = probe_ports(nodes, timeout=timeout, inbound_ports=inbound_ports)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output
