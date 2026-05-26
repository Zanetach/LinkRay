import base64
import json
import unittest
from unittest.mock import patch

from linkray.egern import build_egern_yaml, convert_link, resolve_server_address


def b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


class EgernTests(unittest.TestCase):
    def test_resolve_server_address_prefers_ipv4_address(self):
        with patch("linkray.egern.socket.getaddrinfo", return_value=[(None, None, None, None, ("203.0.113.10", 0))]):
            self.assertEqual(resolve_server_address("edge.example.com"), "203.0.113.10")

    def test_resolve_server_address_keeps_ip_literals(self):
        with patch("linkray.egern.socket.getaddrinfo") as getaddrinfo:
            self.assertEqual(resolve_server_address("198.51.100.20"), "198.51.100.20")
            getaddrinfo.assert_not_called()

    def test_build_egern_yaml_filters_unsupported_protocols(self):
        vmess = {
            "ps": "vmess-ws",
            "add": "edge.example.com",
            "port": "18089",
            "id": "00000000-0000-0000-0000-000000000000",
            "net": "ws",
            "path": "/vmess-ws",
            "host": "edge.example.com",
            "tls": "tls",
            "scy": "auto",
        }
        links = "\n".join(
            [
                "vless://11111111-1111-1111-1111-111111111111@edge.example.com:18080?security=tls&type=tcp&sni=edge.example.com#vless-tls",
                "vless://11111111-1111-1111-1111-111111111111@edge.example.com:18081?security=reality&type=tcp&sni=www.microsoft.com#vless-reality",
                "trojan://password@edge.example.com:18083?security=tls&type=tcp&sni=edge.example.com#trojan-tls",
                f"vmess://{b64(json.dumps(vmess))}",
                "ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpwYXNzd29yZA@edge.example.com:18085#ss",
            ]
        )
        payload = base64.b64encode(links.encode())

        with patch("linkray.egern.socket.getaddrinfo", return_value=[(None, None, None, None, ("203.0.113.10", 0))]):
            output = build_egern_yaml(payload)

        self.assertIn("proxies:", output)
        self.assertIn('server: "203.0.113.10"', output)
        self.assertIn("- vless:", output)
        self.assertIn("- trojan:", output)
        self.assertIn("- vmess:", output)
        self.assertIn("- shadowsocks:", output)
        self.assertIn("vless-tls", output)
        self.assertIn("tfo: false", output)
        self.assertNotIn("vless-reality", output)
        self.assertNotIn("tfo: true", output)

    def test_convert_link_skips_vmess_httpupgrade(self):
        vmess = {
            "ps": "vmess-httpupgrade",
            "add": "edge.example.com",
            "port": "18090",
            "id": "00000000-0000-0000-0000-000000000000",
            "net": "httpupgrade",
            "path": "/vmess-httpupgrade",
            "tls": "tls",
        }

        self.assertIsNone(convert_link(f"vmess://{b64(json.dumps(vmess))}"))


if __name__ == "__main__":
    unittest.main()
