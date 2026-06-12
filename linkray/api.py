from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Sequence
from urllib.parse import unquote, urlparse

from .config import NodeHost
from .ports import probe_ports
from .protocol_prefs import (
    DEFAULT_PROTOCOL_PREFS_PATH,
    enabled_protocols_for_user,
    load_protocol_preferences,
    set_user_protocols,
)


class PortStatusCache:
    def __init__(
        self,
        nodes: Sequence[NodeHost],
        timeout: float = 2.0,
        ttl: float = 60.0,
        inbound_ports: Sequence[tuple[str, int]] | None = None,
        singbox_inbound_ports: Sequence[tuple[str, int]] | None = None,
        snell_inbound_ports: Sequence[tuple[str, int]] | None = None,
    ) -> None:
        self.nodes = list(nodes)
        self.timeout = timeout
        self.ttl = ttl
        self.inbound_ports = tuple(inbound_ports or ())
        self.singbox_inbound_ports = tuple(singbox_inbound_ports or ())
        self.snell_inbound_ports = tuple(snell_inbound_ports or ())
        self._lock = threading.Lock()
        self._data: dict[str, object] | None = None
        self._updated_at = 0.0

    def get(self) -> dict[str, object]:
        with self._lock:
            if self._data is None or time.monotonic() - self._updated_at > self.ttl:
                self._data = probe_ports(
                    self.nodes,
                    timeout=self.timeout,
                    inbound_ports=self.inbound_ports,
                    singbox_inbound_ports=self.singbox_inbound_ports,
                    snell_inbound_ports=self.snell_inbound_ports,
                )
                self._updated_at = time.monotonic()
            return self._data

    def refresh(self) -> dict[str, object]:
        with self._lock:
            self._data = probe_ports(
                self.nodes,
                timeout=self.timeout,
                inbound_ports=self.inbound_ports,
                singbox_inbound_ports=self.singbox_inbound_ports,
                snell_inbound_ports=self.snell_inbound_ports,
            )
            self._updated_at = time.monotonic()
            return self._data


class LinkRayAPIHandler(BaseHTTPRequestHandler):
    cache: PortStatusCache
    protocol_preferences_path: Path

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_json(self, status: int, data: dict[str, object]) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def read_json_body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        data = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self.send_json(200, {"status": "ok"})
            return
        if path == "/nodes":
            self.send_json(200, self.cache.get())
            return
        if path.startswith("/user-protocols/"):
            username = unquote(path.removeprefix("/user-protocols/")).strip()
            if not username:
                self.send_json(400, {"error": "username is required"})
                return
            prefs = load_protocol_preferences(self.protocol_preferences_path)
            self.send_json(200, {"username": username, "protocols": sorted(enabled_protocols_for_user(prefs, username))})
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/nodes/refresh":
            self.send_json(200, self.cache.refresh())
            return
        if path == "/user-protocols":
            if not self.headers.get("Authorization"):
                self.send_json(401, {"error": "authorization required"})
                return
            try:
                payload = self.read_json_body()
                username = str(payload.get("username") or "").strip()
                protocols = payload.get("protocols") or []
                if not isinstance(protocols, list):
                    raise ValueError("protocols must be a list")
                prefs = set_user_protocols(self.protocol_preferences_path, username, protocols)
                self.send_json(200, {"username": username, "protocols": sorted(enabled_protocols_for_user(prefs, username))})
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                self.send_json(400, {"error": str(exc)})
            return
        self.send_json(404, {"error": "not found"})


def make_server(
    listen: str,
    port: int,
    nodes: Sequence[NodeHost],
    timeout: float = 2.0,
    ttl: float = 60.0,
    inbound_ports: Sequence[tuple[str, int]] | None = None,
    singbox_inbound_ports: Sequence[tuple[str, int]] | None = None,
    snell_inbound_ports: Sequence[tuple[str, int]] | None = None,
    protocol_preferences_path: Path = DEFAULT_PROTOCOL_PREFS_PATH,
) -> ThreadingHTTPServer:
    cache = PortStatusCache(
        nodes=nodes,
        timeout=timeout,
        ttl=ttl,
        inbound_ports=inbound_ports,
        singbox_inbound_ports=singbox_inbound_ports,
        snell_inbound_ports=snell_inbound_ports,
    )

    class Handler(LinkRayAPIHandler):
        pass

    Handler.cache = cache
    Handler.protocol_preferences_path = protocol_preferences_path
    return ThreadingHTTPServer((listen, port), Handler)


def serve_api(args: argparse.Namespace) -> int:
    server = make_server(
        args.listen,
        args.port,
        args.nodes,
        timeout=args.timeout,
        ttl=args.ttl,
        inbound_ports=args.inbound_ports,
        singbox_inbound_ports=args.singbox_inbound_ports,
        snell_inbound_ports=args.snell_inbound_ports,
        protocol_preferences_path=args.protocol_preferences_path,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0
