from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass
from typing import Sequence

from .config import DEFAULT_PORTS, PORT_KEYS, relay_port, validate_port
from .render import ACTIVE_INBOUND_TAGS


LOGGER = logging.getLogger("linkray.relay")


@dataclass(frozen=True)
class RelayNode:
    name: str
    domain: str
    port_offset: int = 100


@dataclass(frozen=True)
class RelaySpec:
    node: str
    domain: str
    inbound_tag: str
    listen_port: int
    target_port: int


def parse_relay_node(value: str) -> RelayNode:
    if "=" not in value:
        raise ValueError("relay node must be formatted as name=domain[:offset]")
    name, target = value.split("=", 1)
    name = name.strip()
    target = target.strip()
    if not name:
        raise ValueError("relay node name is required")
    if ":" in target:
        domain, raw_offset = target.rsplit(":", 1)
        try:
            offset = int(raw_offset)
        except ValueError as exc:
            raise ValueError(f"invalid relay port offset: {raw_offset}") from exc
    else:
        domain = target
        offset = 100
    domain = domain.strip()
    if not domain or "." not in domain:
        raise ValueError(f"invalid relay target domain: {domain}")
    if offset < 1:
        raise ValueError("relay port offset must be positive")
    return RelayNode(name=name, domain=domain, port_offset=offset)


def relay_specs(
    nodes: Sequence[RelayNode],
    inbound_ports: Sequence[tuple[str, int]] | None = None,
) -> list[RelaySpec]:
    tags = dict(zip(PORT_KEYS, ACTIVE_INBOUND_TAGS))
    ports = dict(DEFAULT_PORTS)
    if inbound_ports:
        ports.update(dict(inbound_ports))

    specs: list[RelaySpec] = []
    for node_index, node in enumerate(nodes, start=1):
        for key in PORT_KEYS:
            target_port = ports[key]
            listen_port = relay_port(target_port, node_index, node.port_offset)
            specs.append(
                RelaySpec(
                    node=node.name,
                    domain=node.domain,
                    inbound_tag=tags[key],
                    listen_port=listen_port,
                    target_port=target_port,
                )
            )
    return specs


async def close_writer(writer: asyncio.StreamWriter) -> None:
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError, asyncio.CancelledError):
        pass
    finally:
        await close_writer(writer)


async def handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    target_host: str,
    target_port: int,
    timeout: float,
) -> None:
    try:
        upstream_reader, upstream_writer = await asyncio.wait_for(
            asyncio.open_connection(target_host, target_port),
            timeout=timeout,
        )
    except (OSError, asyncio.TimeoutError):
        await close_writer(writer)
        return

    await asyncio.gather(
        pipe(reader, upstream_writer),
        pipe(upstream_reader, writer),
    )


async def run_relay(
    listen: str,
    specs: Sequence[RelaySpec],
    timeout: float,
) -> None:
    servers: list[asyncio.AbstractServer] = []
    for spec in specs:
        validate_port(spec.listen_port)
        server = await asyncio.start_server(
            lambda reader, writer, item=spec: handle_client(reader, writer, item.domain, item.target_port, timeout),
            listen,
            spec.listen_port,
        )
        servers.append(server)
        LOGGER.info(
            "relay %s %s listen=%s target=%s:%s",
            spec.node,
            spec.inbound_tag,
            spec.listen_port,
            spec.domain,
            spec.target_port,
        )

    if not servers:
        await asyncio.Event().wait()
        return

    await asyncio.gather(*(server.serve_forever() for server in servers))


def serve_relay(args: argparse.Namespace) -> int:
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    nodes = [parse_relay_node(value) for value in (args.node or [])]
    specs = relay_specs(nodes, inbound_ports=args.inbound_ports)
    try:
        asyncio.run(run_relay(args.listen, specs, timeout=args.timeout))
    except KeyboardInterrupt:
        return 130
    return 0
