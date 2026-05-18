from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Sequence

from .config import NodeHost
from .ports import probe_ports


class PortStatusCache:
    def __init__(self, nodes: Sequence[NodeHost], timeout: float = 2.0, ttl: float = 60.0) -> None:
        self.nodes = list(nodes)
        self.timeout = timeout
        self.ttl = ttl
        self._lock = threading.Lock()
        self._data: dict[str, object] | None = None
        self._updated_at = 0.0

    def get(self) -> dict[str, object]:
        with self._lock:
            if self._data is None or time.monotonic() - self._updated_at > self.ttl:
                self._data = probe_ports(self.nodes, timeout=self.timeout)
                self._updated_at = time.monotonic()
            return self._data

    def refresh(self) -> dict[str, object]:
        with self._lock:
            self._data = probe_ports(self.nodes, timeout=self.timeout)
            self._updated_at = time.monotonic()
            return self._data


class LinkRayAPIHandler(BaseHTTPRequestHandler):
    cache: PortStatusCache

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

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json(200, {"status": "ok"})
            return
        if self.path == "/nodes":
            self.send_json(200, self.cache.get())
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path == "/nodes/refresh":
            self.send_json(200, self.cache.refresh())
            return
        self.send_json(404, {"error": "not found"})


def make_server(
    listen: str,
    port: int,
    nodes: Sequence[NodeHost],
    timeout: float = 2.0,
    ttl: float = 60.0,
) -> ThreadingHTTPServer:
    cache = PortStatusCache(nodes=nodes, timeout=timeout, ttl=ttl)

    class Handler(LinkRayAPIHandler):
        pass

    Handler.cache = cache
    return ThreadingHTTPServer((listen, port), Handler)


def serve_api(args: argparse.Namespace) -> int:
    server = make_server(args.listen, args.port, args.nodes, timeout=args.timeout, ttl=args.ttl)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0
