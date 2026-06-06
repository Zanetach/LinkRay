from __future__ import annotations

import argparse
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .native import build_stable_native_subscription


PASS_HEADERS = {
    "content-disposition",
    "support-url",
    "profile-title",
    "profile-update-interval",
    "subscription-userinfo",
}


def browser_request(user_agent: str, accept: str) -> bool:
    ua = user_agent.lower()
    return "text/html" in accept.lower() and any(name in ua for name in ("mozilla", "safari", "chrome", "firefox", "edge"))


def choose_suffix(user_agent: str, accept: str) -> tuple[str, dict[str, str]]:
    ua = user_agent.lower()
    if browser_request(user_agent, accept):
        return "", {"Accept": "text/html"}
    if "egern" in ua:
        return "/egern", {"Accept": "text/yaml"}
    if "shadowrocket" in ua:
        return "/shadowrocket", {"Accept": "text/plain"}
    if any(name in ua for name in ("sing-box", "sfa", "sfi", "sfm")):
        return "/sing-box", {"Accept": "application/json"}
    if any(name in ua for name in ("mihomo", "clash", "flclash", "clash.meta", "stash")):
        return "/clash-meta", {"Accept": "text/yaml"}
    return "/native", {"Accept": "text/plain"}


def parse_token(path: str) -> str | None:
    parts = path.strip("/").split("/")
    if len(parts) == 2 and parts[0] == "sub" and parts[1]:
        return parts[1]
    return None


def request_headers(source: Mapping[str, str], extra: Mapping[str, str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name in ("User-Agent", "Accept", "Accept-Language"):
        value = source.get(name)
        if value:
            headers[name] = value
    headers.update(extra)
    return headers


def fetch(url: str, headers: Mapping[str, str]) -> tuple[int, dict[str, str], bytes]:
    req = Request(url, headers=dict(headers))
    with urlopen(req, timeout=15) as response:
        return response.status, dict(response.headers.items()), response.read()


class SubAutoHandler(BaseHTTPRequestHandler):
    marzban_url: str
    egern_url: str
    shadowrocket_url: str
    singbox_url: str

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self.send_bytes(200, {"Content-Type": "text/plain"}, b"ok\n")
            return
        token = parse_token(path)
        if not token:
            self.send_bytes(404, {"Content-Type": "text/plain"}, b"not found\n")
            return
        suffix, extra = choose_suffix(self.headers.get("User-Agent", ""), self.headers.get("Accept", ""))
        if suffix == "/egern":
            url = f"{self.egern_url.rstrip('/')}/sub/{token}/egern"
        elif suffix in {"/shadowrocket", "/shadowrocket-conf"}:
            url = f"{self.shadowrocket_url.rstrip('/')}/sub/{token}/shadowrocket"
            if suffix == "/shadowrocket-conf":
                url = f"{self.shadowrocket_url.rstrip('/')}/sub/{token}/shadowrocket-conf"
        elif suffix == "/sing-box":
            url = f"{self.singbox_url.rstrip('/')}/sub/{token}/sing-box"
        elif suffix == "/native":
            url = f"{self.marzban_url.rstrip('/')}/sub/{token}"
        else:
            url = f"{self.marzban_url.rstrip('/')}/sub/{token}{suffix}"
        try:
            status, headers, body = fetch(url, request_headers(self.headers, extra))
            if suffix == "/native" and status == 200:
                body = build_stable_native_subscription(body)
                headers["Content-Type"] = "text/plain; charset=utf-8"
        except HTTPError as exc:
            self.send_bytes(exc.code, dict(exc.headers.items()), exc.read() or b"upstream error\n")
            return
        except (URLError, TimeoutError) as exc:
            self.send_bytes(502, {"Content-Type": "text/plain"}, f"subscription upstream unavailable: {exc}\n".encode("utf-8"))
            return
        self.send_bytes(status, headers, body)

    def send_bytes(self, status: int, headers: Mapping[str, str], body: bytes) -> None:
        self.send_response(status)
        self.send_header("Cache-Control", "no-store")
        content_type = headers.get("Content-Type") or headers.get("content-type") or "application/octet-stream"
        self.send_header("Content-Type", content_type)
        for name, value in headers.items():
            if name.lower() in PASS_HEADERS:
                self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_sub_auto_server(
    listen: str,
    port: int,
    marzban_url: str,
    egern_url: str,
    shadowrocket_url: str,
    singbox_url: str,
) -> ThreadingHTTPServer:
    class Handler(SubAutoHandler):
        pass

    Handler.marzban_url = marzban_url
    Handler.egern_url = egern_url
    Handler.shadowrocket_url = shadowrocket_url
    Handler.singbox_url = singbox_url
    return ThreadingHTTPServer((listen, port), Handler)


def serve_sub_auto(args: argparse.Namespace) -> int:
    server = make_sub_auto_server(args.listen, args.port, args.marzban_url, args.egern_url, args.shadowrocket_url, args.singbox_url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0
