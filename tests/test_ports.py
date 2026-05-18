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

        with patch("linkray.ports.tcp_probe", side_effect=fake_probe):
            data = probe_ports(
                [
                    NodeHost("edge-a", "edge-a.example.com"),
                    NodeHost("edge-b", "edge-b.example.com"),
                ],
                timeout=0.1,
            )

        self.assertEqual(data["total"], 24)
        self.assertEqual(data["open"], 23)
        self.assertEqual(data["closed"], 1)
        failed = [item for item in data["results"] if item["status"] == "closed"]
        self.assertEqual(failed[0]["node"], "edge-a")
        self.assertEqual(failed[0]["port"], 18081)

    def test_write_ports_json_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "nested/ports.json"
            with patch("linkray.ports.tcp_probe", return_value=("open", 8, None)):
                write_ports_json([NodeHost("edge-a", "edge-a.example.com")], output)

            text = output.read_text()
            self.assertIn('"total": 12', text)
            self.assertIn('"open": 12', text)


if __name__ == "__main__":
    unittest.main()
