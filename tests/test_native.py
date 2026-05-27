import base64
import json
import unittest

from linkray.native import build_stable_native_subscription, decode_subscription_links


def b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


class NativeSubscriptionTests(unittest.TestCase):
    def test_build_stable_native_subscription_filters_advanced_mobile_protocols(self):
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
                "vless://11111111-1111-1111-1111-111111111111@edge.example.com:18080?security=tls&type=tcp#vless-tls",
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
        self.assertIn("trojan-tls", decoded)
        self.assertIn(f"vmess://{b64(json.dumps(vmess_ws))}", decoded)
        self.assertIn("#ss", decoded)
        self.assertNotIn("vless-reality", decoded)
        self.assertNotIn("vless-grpc", decoded)
        self.assertNotIn("trojan-grpc", decoded)
        self.assertNotIn("vmess-grpc", decoded)


if __name__ == "__main__":
    unittest.main()
