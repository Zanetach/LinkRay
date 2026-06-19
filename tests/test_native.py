import base64
import json
import unittest
from unittest.mock import patch

from linkray.native import build_stable_native_subscription, decode_subscription_links, relay_secondary_node_link


def b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def b64decode_vmess(link: str) -> str:
    return base64.urlsafe_b64decode(link.removeprefix("vmess://") + "==").decode()


class NativeSubscriptionTests(unittest.TestCase):
    def test_build_stable_native_subscription_filters_to_public_443_defaults(self):
        vmess_ws = {
            "ps": "vmess-ws",
            "add": "edge.example.com",
            "port": "18089",
            "id": "00000000-0000-0000-0000-000000000000",
            "net": "ws",
            "tls": "tls",
        }
        vmess_grpc = {
            "ps": "vmess-grpc",
            "add": "edge.example.com",
            "port": "18090",
            "id": "00000000-0000-0000-0000-000000000000",
            "net": "grpc",
            "tls": "tls",
        }
        links = "\n".join(
            [
                "vless://11111111-1111-1111-1111-111111111111@edge.example.com:443?security=tls&type=tcp#vless-tls",
                "vless://11111111-1111-1111-1111-111111111111@edge.example.com:18080?security=tls&type=tcp#vless-non443",
                "vless://11111111-1111-1111-1111-111111111111@edge.example.com:18081?security=reality&type=tcp#vless-reality",
                "vless://11111111-1111-1111-1111-111111111111@edge.example.com:18082?security=tls&type=grpc#vless-grpc",
                "trojan://password@edge.example.com:18083?security=tls&type=tcp#trojan-tls",
                "trojan://password@edge.example.com:18091?security=tls&type=grpc#trojan-grpc",
                f"vmess://{b64(json.dumps(vmess_ws))}",
                f"vmess://{b64(json.dumps(vmess_grpc))}",
                "ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpwYXNzd29yZA@edge.example.com:18085#ss",
            ]
        )

        output = build_stable_native_subscription(base64.b64encode(links.encode()))
        decoded = "\n".join(decode_subscription_links(output))

        self.assertIn("vless-tls", decoded)
        self.assertNotIn("vless-non443", decoded)
        self.assertNotIn("trojan-tls", decoded)
        self.assertNotIn(f"vmess://{b64(json.dumps(vmess_ws))}", decoded)
        self.assertNotIn("#ss", decoded)
        self.assertNotIn("vless-reality", decoded)
        self.assertNotIn("vless-grpc", decoded)
        self.assertNotIn("trojan-grpc", decoded)
        self.assertNotIn("vmess-grpc", decoded)

    def test_build_stable_native_subscription_can_keep_legacy_stable_links(self):
        links = "\n".join(
            [
                "vless://11111111-1111-1111-1111-111111111111@edge.example.com:18080?security=tls&type=tcp#vless-tls",
                "trojan://password@edge.example.com:18083?security=tls&type=tcp#trojan-tls",
                "ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpwYXNzd29yZA@edge.example.com:18085#ss",
            ]
        )

        output = build_stable_native_subscription(base64.b64encode(links.encode()), public_only=False)
        decoded = "\n".join(decode_subscription_links(output))

        self.assertIn("vless-tls", decoded)
        self.assertIn("trojan-tls", decoded)
        self.assertIn("#ss", decoded)

    def test_build_stable_native_subscription_can_resolve_vless_server_to_origin_ip(self):
        links = "\n".join(
            [
                "vless://11111111-1111-1111-1111-111111111111@edge.example.com:443?security=tls&type=tcp&sni=edge.example.com&host=edge.example.com#vless-tls",
            ]
        )

        with patch("linkray.native.public_ipv4_for_host", return_value="203.0.113.10"):
            output = build_stable_native_subscription(base64.b64encode(links.encode()), resolve_public_hosts=True)

        decoded = "\n".join(decode_subscription_links(output))
        self.assertIn("@203.0.113.10:443", decoded)
        self.assertIn("sni=edge.example.com", decoded)
        self.assertIn("host=edge.example.com", decoded)

    def test_build_stable_native_subscription_can_resolve_vmess_server_to_origin_ip(self):
        vmess_ws = {
            "ps": "vmess-ws",
            "add": "edge.example.com",
            "port": "443",
            "id": "00000000-0000-0000-0000-000000000000",
            "net": "ws",
            "host": "edge.example.com",
            "sni": "edge.example.com",
            "tls": "tls",
        }
        links = f"vmess://{b64(json.dumps(vmess_ws))}"

        with patch("linkray.native.public_ipv4_for_host", return_value="203.0.113.10"):
            output = build_stable_native_subscription(base64.b64encode(links.encode()), resolve_public_hosts=True)

        decoded_links = decode_subscription_links(output)
        decoded_vmess = json.loads(base64.urlsafe_b64decode(decoded_links[0].removeprefix("vmess://") + "==").decode())
        self.assertEqual(decoded_vmess["add"], "203.0.113.10")
        self.assertEqual(decoded_vmess["host"], "edge.example.com")
        self.assertEqual(decoded_vmess["sni"], "edge.example.com")

    def test_relay_secondary_node_link_keeps_public_fallback_ports_direct(self):
        vless_ws = "vless://11111111-1111-1111-1111-111111111111@edge-b.example.com:443?security=tls&type=ws&sni=edge-b.example.com#edge-b-VLESS_WS_TLS"
        vmess_ws = {
            "ps": "edge-b-VMess_WS_TLS",
            "add": "edge-b.example.com",
            "port": "443",
            "id": "00000000-0000-0000-0000-000000000000",
            "net": "ws",
            "tls": "tls",
        }
        vmess_httpupgrade = dict(vmess_ws, ps="edge-b-VMess_HTTPUpgrade_TLS", net="httpupgrade")

        relayed_vless_ws = relay_secondary_node_link(vless_ws, "edge-a.example.com")
        relayed_vmess_ws = json.loads(
            b64decode_vmess(relay_secondary_node_link(f"vmess://{b64(json.dumps(vmess_ws))}", "edge-a.example.com"))
        )
        relayed_vmess_httpupgrade = json.loads(
            b64decode_vmess(relay_secondary_node_link(f"vmess://{b64(json.dumps(vmess_httpupgrade))}", "edge-a.example.com"))
        )

        self.assertIn("@edge-b.example.com:443", relayed_vless_ws)
        self.assertEqual(relayed_vmess_ws["add"], "edge-b.example.com")
        self.assertEqual(relayed_vmess_ws["port"], "443")
        self.assertEqual(relayed_vmess_httpupgrade["add"], "edge-b.example.com")
        self.assertEqual(relayed_vmess_httpupgrade["port"], "443")


    def test_b64decode_text_handles_missing_padding(self):
        from linkray.native import b64decode_text

        raw = base64.urlsafe_b64encode(b"hello world").decode().rstrip("=")
        self.assertEqual(b64decode_text(raw), "hello world")

    def test_stable_vless_accepts_tls_tcp_and_ws(self):
        from linkray.native import stable_vless

        self.assertTrue(stable_vless("vless://u@h:1?security=tls&type=tcp"))
        self.assertTrue(stable_vless("vless://u@h:1?security=tls&type=ws"))
        self.assertTrue(stable_vless("vless://u@h:1?security=reality&type=tcp"))
        self.assertFalse(stable_vless("vless://u@h:1?security=tls&type=grpc"))

    def test_stable_trojan_accepts_tcp_and_ws_only(self):
        from linkray.native import stable_trojan

        self.assertTrue(stable_trojan("trojan://p@h:1?type=tcp"))
        self.assertTrue(stable_trojan("trojan://p@h:1?type=ws"))
        self.assertFalse(stable_trojan("trojan://p@h:1?type=grpc"))

    def test_stable_vmess_accepts_tcp_and_ws_only(self):
        from linkray.native import stable_vmess

        vmess_ws = b64(json.dumps({"add": "h", "port": 1, "id": "u", "net": "ws", "tls": "tls"}))
        vmess_grpc = b64(json.dumps({"add": "h", "port": 1, "id": "u", "net": "grpc"}))

        self.assertTrue(stable_vmess(f"vmess://{vmess_ws}"))
        self.assertFalse(stable_vmess(f"vmess://{vmess_grpc}"))
        self.assertFalse(stable_vmess("vmess://!!!not-base64!!!"))

    def test_stable_native_link_passes_ss_unconditionally(self):
        from linkray.native import stable_native_link

        self.assertTrue(stable_native_link("ss://anything@h:1"))
        self.assertFalse(stable_native_link("hysteria2://anything"))
        self.assertFalse(stable_native_link("unknown://anything"))


if __name__ == "__main__":
    unittest.main()
