import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from linkray.config import NodeHost
from linkray.ports import probe_ports, write_ports_json


class PortStatusTests(unittest.TestCase):
    def test_probe_ports_returns_one_row_per_node_port(self):
        def fake_probe(host, port, timeout):
            if host == "edge-a.example.com" and port == 18081:
                return "closed", None, "timeout"
            return "open", 12, None

        with patch("linkray.ports.tcp_probe", side_effect=fake_probe), patch(
            "linkray.ports.udp_probe", side_effect=fake_probe
        ):
            data = probe_ports(
                [
                    NodeHost("edge-a", "edge-a.example.com"),
                    NodeHost("edge-b", "edge-b.example.com"),
                ],
                timeout=0.1,
            )

        self.assertEqual(data["total"], 32)
        self.assertEqual(data["open"], 31)
        self.assertEqual(data["closed"], 1)
        self.assertIn("Snell", {item["inbound_tag"] for item in data["results"]})
        self.assertIn("snell", {item["runtime"] for item in data["results"]})
        self.assertIn("udp", {item["transport"] for item in data["results"]})
        failed = [item for item in data["results"] if item["status"] == "closed"]
        self.assertEqual(failed[0]["node"], "edge-a")
        self.assertEqual(failed[0]["port"], 18081)

    def test_probe_ports_accepts_custom_inbound_ports(self):
        seen_ports = []

        def fake_probe(host, port, timeout):
            seen_ports.append(port)
            return "open", 7, None

        with patch("linkray.ports.tcp_probe", side_effect=fake_probe), patch(
            "linkray.ports.udp_probe", side_effect=fake_probe
        ):
            data = probe_ports(
                [NodeHost("edge-a", "edge-a.example.com")],
                timeout=0.1,
                inbound_ports=(("vless_tls", 28080), ("trojan_grpc_tls", 28091)),
                singbox_inbound_ports=(("hysteria2", 29080),),
                snell_inbound_ports=(("snell", 29180),),
            )

        self.assertEqual(data["total"], 16)
        self.assertIn(28080, seen_ports)
        self.assertIn(28091, seen_ports)
        self.assertIn(29080, seen_ports)
        self.assertIn(29180, seen_ports)
        self.assertNotIn(18080, seen_ports)
        self.assertNotIn(19080, seen_ports)
        self.assertNotIn(19180, seen_ports)

    def test_write_ports_json_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "nested/ports.json"
            with patch("linkray.ports.tcp_probe", return_value=("open", 8, None)), patch(
                "linkray.ports.udp_probe", return_value=("open", None, None)
            ):
                write_ports_json([NodeHost("edge-a", "edge-a.example.com")], output)

            text = output.read_text()
            self.assertIn('"total": 16', text)
            self.assertIn('"open": 16', text)
            self.assertIn('"inbound_tag": "Snell"', text)
            self.assertIn('"transport": "udp"', text)


if __name__ == "__main__":
    unittest.main()
