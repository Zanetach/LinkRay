import http.client
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from linkray.sub_auto import PASS_HEADERS, choose_suffix, make_sub_auto_server, parse_token, upstream_url_for_suffix


class SubAutoTests(unittest.TestCase):
    def test_choose_suffix_routes_known_clients(self):
        self.assertEqual(choose_suffix("Egern/1.0", "*/*")[0], "/egern")
        self.assertEqual(choose_suffix("sing-box", "*/*")[0], "/sing-box")
        self.assertEqual(choose_suffix("FlClash", "*/*")[0], "/clash-meta")
        self.assertEqual(choose_suffix("Shadowrocket/2520 CFNetwork", "*/*")[0], "/shadowrocket")
        self.assertEqual(choose_suffix("Mozilla/5.0", "text/html,*/*")[0], "")
        self.assertEqual(choose_suffix("unknown", "*/*")[0], "/native")

    def test_clash_clients_route_to_linkray_clash_adapter(self):
        self.assertEqual(
            upstream_url_for_suffix(
                "/clash-meta",
                "abc123",
                marzban_url="http://127.0.0.1:8000",
                egern_url="http://127.0.0.1:61992",
                shadowrocket_url="http://127.0.0.1:61994",
                singbox_url="http://127.0.0.1:61995",
                clash_url="http://127.0.0.1:61991",
            ),
            "http://127.0.0.1:61991/sub/abc123/clash-meta",
        )

    def test_parse_token_accepts_only_base_subscription_path(self):
        self.assertEqual(parse_token("/sub/abc"), "abc")
        self.assertEqual(parse_token("/sub/abc/"), "abc")
        self.assertIsNone(parse_token("/sub/abc/egern"))
        self.assertIsNone(parse_token("/api/sub/abc"))

    def test_forwarded_headers_do_not_expose_internal_profile_url(self):
        self.assertNotIn("profile-web-page-url", PASS_HEADERS)

    def test_head_returns_headers_without_body(self):
        body = b"proxies: []\n"

        class UpstreamHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/sub/token/egern":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/yaml")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                return

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
        upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        upstream_thread.start()
        upstream_url = f"http://127.0.0.1:{upstream.server_address[1]}"
        adapter = make_sub_auto_server(
            "127.0.0.1",
            0,
            marzban_url=upstream_url,
            clash_url=upstream_url,
            egern_url=upstream_url,
            shadowrocket_url=upstream_url,
            singbox_url=upstream_url,
        )
        adapter_thread = threading.Thread(target=adapter.serve_forever, daemon=True)
        adapter_thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", adapter.server_address[1], timeout=3)
            conn.request("HEAD", "/sub/token", headers={"User-Agent": "Egern/1.0", "Accept": "*/*"})
            response = conn.getresponse()
            payload = response.read()
            conn.close()

            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Content-Type"), "text/yaml")
            self.assertEqual(response.getheader("Content-Length"), str(len(body)))
            self.assertEqual(payload, b"")
        finally:
            adapter.shutdown()
            adapter.server_close()
            upstream.shutdown()
            upstream.server_close()


if __name__ == "__main__":
    unittest.main()
