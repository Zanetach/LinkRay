import http.client
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from linkray._http import AdapterHandler, fetch_subscription_username, fetch_upstream, first_query_value, parse_link_netloc


class FirstQueryValueTests(unittest.TestCase):
    def _q(self, url: str) -> dict:
        return parse_qs(urlparse(url).query)

    def test_returns_first_matching_value(self):
        q = self._q("vless://x@h:1?type=ws&sni=example.com")
        self.assertEqual(first_query_value(q, "sni", "servername"), "example.com")

    def test_tries_names_in_order(self):
        q = self._q("vless://x@h:1?servername=fallback.com")
        self.assertEqual(first_query_value(q, "sni", "servername"), "fallback.com")

    def test_returns_none_when_no_match(self):
        q = self._q("vless://x@h:1?type=tcp")
        self.assertIsNone(first_query_value(q, "sni", "servername"))

    def test_skips_empty_string_values(self):
        q = {"sni": [""], "servername": ["real.com"]}
        self.assertEqual(first_query_value(q, "sni", "servername"), "real.com")

    def test_returns_none_for_empty_query(self):
        self.assertIsNone(first_query_value({}, "sni"))


class ParseLinkNetlocTests(unittest.TestCase):
    def _p(self, url: str):
        return urlparse(url)

    def test_returns_host_and_port(self):
        result = parse_link_netloc(self._p("vless://uuid@edge.example.com:18080"))
        self.assertEqual(result, ("edge.example.com", 18080))

    def test_returns_none_when_port_missing(self):
        result = parse_link_netloc(self._p("vless://uuid@edge.example.com"))
        self.assertIsNone(result)

    def test_returns_none_when_host_missing(self):
        result = parse_link_netloc(self._p("vless://uuid@:18080"))
        self.assertIsNone(result)

    def test_handles_ip_address(self):
        result = parse_link_netloc(self._p("vless://uuid@1.2.3.4:443"))
        self.assertEqual(result, ("1.2.3.4", 443))


class AdapterHandlerTests(unittest.TestCase):
    def test_head_reuses_get_headers_without_body(self):
        body = b"adapter body\n"

        class Handler(AdapterHandler):
            def do_GET(self) -> None:
                self.send_bytes(200, {"Content-Type": "text/plain"}, body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            conn.request("HEAD", "/sub/token/shadowrocket")
            response = conn.getresponse()
            payload = response.read()
            conn.close()

            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Content-Type"), "text/plain")
            self.assertEqual(response.getheader("Content-Length"), str(len(body)))
            self.assertEqual(payload, b"")
        finally:
            server.shutdown()
            server.server_close()


class UpstreamFetchTests(unittest.TestCase):
    def test_fetch_upstream_uses_cold_subscription_timeout_budget(self):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.headers.items.return_value = [("Content-Type", "text/plain")]
        response.__enter__.return_value.read.return_value = b"payload"

        with patch("linkray._http.urlopen", return_value=response) as urlopen:
            status, headers, body = fetch_upstream("http://127.0.0.1:8000", "token", {"Accept": "text/plain"})

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/plain")
        self.assertEqual(body, b"payload")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 45)

    def test_fetch_subscription_username_uses_cold_subscription_timeout_budget(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"username": "sample-user"}'

        with patch("linkray._http.urlopen", return_value=response) as urlopen:
            username = fetch_subscription_username("http://127.0.0.1:8000", "token")

        self.assertEqual(username, "sample-user")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 45)


if __name__ == "__main__":
    unittest.main()
