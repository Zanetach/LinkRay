import base64
import unittest

from linkray.clash import build_clash_meta_yaml
from linkray.config import LinkRayConfig
from linkray.protocol_prefs import ProtocolPreferences
from linkray.snell_runtime import credential_for_token


def encoded_subscription(*links: str) -> bytes:
    return base64.b64encode(("\n".join(links) + "\n").encode("utf-8"))


class ClashTests(unittest.TestCase):
    def test_build_clash_meta_yaml_adds_groups_dns_and_route_rules(self):
        payload = encoded_subscription(
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:443?encryption=none&security=tls&fp=chrome&type=tcp&sni=ca.example.com&flow=xtls-rprx-vision#ca-VLESS_TLS_Vision",
            "trojan://secret@ca.example.com:8443?security=tls&type=grpc&sni=ca.example.com&serviceName=trojan-grpc#ca-Trojan_gRPC_TLS",
            "vmess://eyJwcyI6ImNhLVZNZXNzX1dTX1RMUyIsImFkZCI6ImNhLmV4YW1wbGUuY29tIiwicG9ydCI6Ijg0NDMiLCJpZCI6IjIyMjIyMjIyLTIyMjItMjIyMi0yMjIyLTIyMjIyMjIyMjIyMiIsImFpZCI6IjAiLCJzY3kiOiJhdXRvIiwibmV0Ijoid3MiLCJ0eXBlIjoibm9uZSIsImhvc3QiOiJjYS5leGFtcGxlLmNvbSIsInBhdGgiOiIvdm1lc3Mtd3MiLCJ0bHMiOiJ0bHMiLCJzbmkiOiJjYS5leGFtcGxlLmNvbSJ9",
        )

        text = build_clash_meta_yaml(payload)

        self.assertIn("proxies:", text)
        self.assertIn("proxy-groups:", text)
        self.assertIn("rules:", text)
        self.assertIn("direct-nameserver:", text)
        self.assertIn("proxy-server-nameserver:", text)
        self.assertIn("name: ca-VLESS_TLS_Vision", text)
        self.assertIn("type: vless", text)
        self.assertIn("flow: xtls-rprx-vision", text)
        self.assertIn("client-fingerprint: chrome", text)
        self.assertIn("name: ca-Trojan_gRPC_TLS", text)
        self.assertIn("network: grpc", text)
        self.assertIn("grpc-opts:", text)
        self.assertIn("name: ca-VMess_WS_TLS", text)
        self.assertIn("ws-opts:", text)
        self.assertIn("name: 全球代理", text)
        self.assertIn("DOMAIN-SUFFIX,google.com,Google", text)
        self.assertIn("GEOIP,CN,国内站点", text)
        self.assertIn("MATCH,漏网之鱼", text)

    def test_build_clash_meta_yaml_filters_xhttp_until_mihomo_support_is_stable(self):
        payload = encoded_subscription(
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:443?encryption=none&security=reality&type=xhttp&sni=www.microsoft.com&pbk=abc&sid=1234#ca-VLESS_XHTTP_Reality",
            "ss://YWVzLTEyOC1nY206cGFzcw@ca.example.com:8388#ca-Shadowsocks",
        )

        text = build_clash_meta_yaml(payload)

        self.assertNotIn("ca-VLESS_XHTTP_Reality", text)
        self.assertIn("name: ca-Shadowsocks", text)

    def test_build_clash_meta_yaml_does_not_append_snell_v5_node(self):
        user = credential_for_token("subscription-token", "server-secret", name="cyclelink", port=40123)
        payload = encoded_subscription(
            "trojan://secret@ca.example.com:8443?security=tls&type=tcp&sni=ca.example.com#ca-Trojan_TLS"
        )

        text = build_clash_meta_yaml(
            payload,
            config=LinkRayConfig(domain="edge-a.example.com"),
            snell_user=user,
        )

        self.assertNotIn("cyclelink-Snell", text)
        self.assertNotIn("type: snell", text)
        self.assertNotIn("version: 5", text)
        self.assertIn("name: ca-Trojan_TLS", text)

        filtered = build_clash_meta_yaml(
            payload,
            config=LinkRayConfig(domain="edge-a.example.com"),
            snell_user=user,
            protocol_preferences=ProtocolPreferences(users={"cyclelink": {"tuic"}}),
        )
        self.assertNotIn("cyclelink-Snell", filtered)


if __name__ == "__main__":
    unittest.main()
