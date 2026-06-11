from __future__ import annotations

from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PASS_HEADERS = {
    "content-disposition",
    "support-url",
    "profile-title",
    "profile-update-interval",
    "subscription-userinfo",
}


def first_query_value(query: Mapping[str, list[str]], *names: str) -> str | None:
    for name in names:
        values = query.get(name)
        if values and values[0]:
            return values[0]
    return None


def parse_link_netloc(parsed) -> tuple[str, int] | None:
    host = parsed.hostname
    port = parsed.port
    if not host or not port:
        return None
    return host, int(port)


def fetch_upstream(marzban_url: str, token: str, headers: Mapping[str, str]) -> tuple[int, dict[str, str], bytes]:
    url = f"{marzban_url.rstrip('/')}/sub/{token}"
    req = Request(url, headers={k: v for k, v in headers.items() if v})
    with urlopen(req, timeout=15) as response:
        return response.status, dict(response.headers.items()), response.read()


class AdapterHandler(BaseHTTPRequestHandler):
    marzban_url: str

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_bytes(self, status: int, headers: Mapping[str, str], body: bytes) -> None:
        self.send_response(status)
        self.send_header("Cache-Control", "no-store")
        for name, value in headers.items():
            if name.lower() not in {"content-length", "transfer-encoding", "connection"}:
                self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
