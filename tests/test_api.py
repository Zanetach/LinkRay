import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from linkray.api import make_server
from linkray.config import NodeHost


class ApiTests(unittest.TestCase):
    def start_server(self, ttl=60, protocol_preferences_path=None):
        server = make_server(
            "127.0.0.1",
            0,
            nodes=[NodeHost("edge-a", "edge-a.example.com"), NodeHost("edge-b", "edge-b.example.com")],
            timeout=0.1,
            ttl=ttl,
            protocol_preferences_path=protocol_preferences_path or Path(tempfile.mkdtemp()) / "users.json",
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def get_json(self, url):
        with urlopen(url, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_health_endpoint(self):
        base = self.start_server()

        status, data = self.get_json(f"{base}/health")

        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ok")

    def test_nodes_endpoint_uses_cached_port_status(self):
        calls = []

        def fake_probe(host, port, timeout):
            calls.append((host, port))
            return "open", 7, None

        base = self.start_server(ttl=60)
        with patch("linkray.ports.tcp_probe", side_effect=fake_probe), patch(
            "linkray.ports.udp_probe", side_effect=fake_probe
        ):
            _, first = self.get_json(f"{base}/nodes")
            _, second = self.get_json(f"{base}/nodes")

        self.assertEqual(first["total"], 32)
        self.assertEqual(first["open"], 32)
        self.assertEqual(second["total"], 32)
        self.assertEqual(len(calls), 32)
        self.assertIn("Snell", {item["inbound_tag"] for item in first["results"]})
        self.assertIn("udp", {item["transport"] for item in first["results"]})

    def test_refresh_endpoint_forces_new_probe(self):
        calls = []

        def fake_probe(host, port, timeout):
            calls.append((host, port))
            return "open", 7, None

        base = self.start_server(ttl=60)
        with patch("linkray.ports.tcp_probe", side_effect=fake_probe), patch(
            "linkray.ports.udp_probe", side_effect=fake_probe
        ):
            self.get_json(f"{base}/nodes")
            request = Request(f"{base}/nodes/refresh", method="POST")
            with urlopen(request, timeout=3) as response:
                data = json.loads(response.read().decode("utf-8"))
                status = response.status

        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 32)
        self.assertEqual(len(calls), 64)

    def test_unknown_endpoint_returns_404(self):
        base = self.start_server()

        with self.assertRaises(HTTPError) as error:
            self.get_json(f"{base}/missing")

        self.assertEqual(error.exception.code, 404)

    def test_user_protocol_preferences_can_be_saved_and_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self.start_server(protocol_preferences_path=Path(tmp) / "users.json")
            body = json.dumps({"username": "lichen", "protocols": ["snell", "tuic"]}).encode("utf-8")
            request = Request(
                f"{base}/user-protocols",
                data=body,
                headers={"Content-Type": "application/json", "Authorization": "Bearer test"},
                method="POST",
            )

            with urlopen(request, timeout=3) as response:
                saved = json.loads(response.read().decode("utf-8"))
            _, loaded = self.get_json(f"{base}/user-protocols/lichen")

        self.assertEqual(response.status, 200)
        self.assertEqual(saved["protocols"], ["snell", "tuic"])
        self.assertEqual(loaded["protocols"], ["snell", "tuic"])

    def test_user_protocol_preferences_require_authorization(self):
        base = self.start_server()
        request = Request(
            f"{base}/user-protocols",
            data=b'{"username":"lichen","protocols":["snell"]}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=3)

        self.assertEqual(error.exception.code, 401)


if __name__ == "__main__":
    unittest.main()
