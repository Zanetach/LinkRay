from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_PORTS = {
    "vless_tls": 18080,
    "vless_reality": 18081,
    "vless_grpc_reality": 18082,
    "trojan_tls": 18083,
    "vmess_tls": 18084,
    "shadowsocks": 18085,
    "vless_ws_tls": 18086,
    "vless_grpc_tls": 18087,
    "vless_xhttp_reality": 18088,
    "vmess_ws_tls": 18089,
    "vmess_httpupgrade_tls": 18090,
    "trojan_grpc_tls": 18091,
}

PORT_KEYS = tuple(DEFAULT_PORTS.keys())


@dataclass(frozen=True)
class LinkRayConfig:
    domain: str
    admin_username: str = "admin"
    admin_password: str = "REPLACE_WITH_ADMIN_PASSWORD"
    cert_file: str = "/var/lib/marzban/certs/linkray/fullchain.cer"
    key_file: str = "/var/lib/marzban/certs/linkray/linkray.key"
    reality_private_key: str = "REPLACE_WITH_REALITY_PRIVATE_KEY"
    reality_short_id: str = "REPLACE_WITH_SHORT_ID"
    reality_server_name: str = "www.microsoft.com"
    reality_dest: str = "www.microsoft.com:443"
    grpc_service_name: str = "grpc"
    panel_port: int = 9443
    marzban_http_port: int = 8000
    inbound_ports: tuple[tuple[str, int], ...] = ()

    def validate(self) -> None:
        if not self.domain or "." not in self.domain:
            raise ValueError("domain must be a fully qualified domain name")
        if not self.admin_username:
            raise ValueError("admin_username is required")
        if self.reality_private_key.startswith("REPLACE_"):
            return
        if len(self.reality_private_key) < 16:
            raise ValueError("reality_private_key is unexpectedly short")
        if len(self.reality_short_id) < 4:
            raise ValueError("reality_short_id is unexpectedly short")
        self.port_map()

    def port_map(self) -> dict[str, int]:
        ports = dict(DEFAULT_PORTS)
        for key, port in self.inbound_ports:
            if key not in DEFAULT_PORTS:
                raise ValueError(f"unknown inbound port key: {key}")
            validate_port(port)
            ports[key] = port
        return ports


def validate_port(port: int) -> None:
    if port < 1 or port > 65535:
        raise ValueError(f"invalid port: {port}")


def parse_inbound_port(value: str) -> tuple[str, int]:
    if "=" not in value:
        raise ValueError("inbound must be formatted as key=port, for example vless_tls=18080")
    key, raw_port = value.split("=", 1)
    key = key.strip()
    if key not in DEFAULT_PORTS:
        allowed = ", ".join(PORT_KEYS)
        raise ValueError(f"unknown inbound key {key!r}; allowed keys: {allowed}")
    try:
        port = int(raw_port.strip())
    except ValueError as exc:
        raise ValueError(f"invalid port for {key}: {raw_port}") from exc
    validate_port(port)
    return key, port


def parse_inbound_ports(values: list[str] | None) -> tuple[tuple[str, int], ...]:
    if not values:
        return ()
    parsed = [parse_inbound_port(value) for value in values]
    seen: set[str] = set()
    duplicates: set[str] = set()
    for key, _ in parsed:
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    if duplicates:
        raise ValueError(f"duplicate inbound port key(s): {', '.join(duplicates)}")
    return tuple(parsed)


@dataclass(frozen=True)
class NodeHost:
    name: str
    domain: str

    def validate(self) -> None:
        if not self.name:
            raise ValueError("node name is required")
        if not self.name.replace("-", "").replace("_", "").isalnum():
            raise ValueError(f"invalid node name: {self.name}")
        if not self.domain or "." not in self.domain:
            raise ValueError(f"invalid node domain: {self.domain}")


def parse_node_host(value: str) -> NodeHost:
    if "=" not in value:
        raise ValueError("node must be formatted as name=domain, for example edge-a=edge-a.example.com")
    name, domain = value.split("=", 1)
    node = NodeHost(name=name.strip(), domain=domain.strip())
    node.validate()
    return node


@dataclass(frozen=True)
class RenderResult:
    output: Path
    files: tuple[Path, ...]
