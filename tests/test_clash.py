import base64
import json
import unittest
from unittest.mock import patch

from linkray.clash import build_clash_meta_yaml
from linkray.config import LinkRayConfig
from linkray.protocol_prefs import ProtocolPreferences
from linkray.snell_runtime import credential_for_token


def encoded_subscription(*links: str) -> bytes:
    return base64.b64encode(("\n".join(links) + "\n").encode("utf-8"))


def vmess_link(payload: dict[str, object]) -> str:
    text = json.dumps(payload, separators=(",", ":"))
    return "vmess://" + base64.b64encode(text.encode("utf-8")).decode("ascii")


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
        self.assertIn("fake-ip-filter:", text)
        self.assertIn("- ca.example.com", text)
        self.assertIn("nameserver-policy:", text)
        self.assertIn("ca.example.com: 223.5.5.5", text)
        self.assertIn("name: ca-VLESS_TLS_Vision", text)
        self.assertIn("type: vless", text)
        self.assertIn("flow: xtls-rprx-vision", text)
        self.assertIn("client-fingerprint: chrome", text)
        self.assertIn("name: ca-Trojan_gRPC_TLS", text)
        self.assertIn("network: grpc", text)
        self.assertIn("grpc-opts:", text)
        self.assertIn("alpn:", text)
        self.assertIn("- h2", text)
        self.assertIn("name: ca-VMess_WS_TLS", text)
        self.assertIn("ws-opts:", text)
        self.assertIn("name: 全球代理", text)
        self.assertIn("DOMAIN-SUFFIX,google.com,Google", text)
        self.assertIn("GEOIP,CN,国内站点", text)
        self.assertIn("MATCH,漏网之鱼", text)

    def test_build_clash_meta_yaml_uses_local_metacubex_rule_assets(self):
        payload = encoded_subscription(
            "trojan://secret@ca.example.com:8443?security=tls&type=tcp&sni=ca.example.com#ca-Trojan_TLS"
        )

        text = build_clash_meta_yaml(
            payload,
            rules_base_url="https://edge-a.example.com:9443/linkray/rules",
        )

        self.assertIn("geox-url:", text)
        self.assertIn("geoip: https://edge-a.example.com:9443/linkray/rules/geoip.dat", text)
        self.assertIn("geosite: https://edge-a.example.com:9443/linkray/rules/geosite.dat", text)
        self.assertIn("mmdb: https://edge-a.example.com:9443/linkray/rules/country.mmdb", text)
        self.assertIn("asn: https://edge-a.example.com:9443/linkray/rules/GeoLite2-ASN.mmdb", text)
        self.assertIn("rule-providers:", text)
        self.assertIn("url: https://edge-a.example.com:9443/linkray/rules/mihomo/geosite-cn.mrs", text)
        self.assertIn("url: https://edge-a.example.com:9443/linkray/rules/mihomo/geoip-cn.mrs", text)
        self.assertEqual(text.count("proxy: DIRECT"), 2)
        self.assertIn("url: https://cp.cloudflare.com/generate_204", text)
        self.assertIn("RULE-SET,linkray-cn-domain,国内站点", text)
        self.assertIn("RULE-SET,linkray-cn-ip,国内站点", text)
        self.assertNotIn("/api/linkray/health", text)
        self.assertNotIn("https://www.gstatic.com/generate_204", text)
        self.assertNotIn("https://dns.google/dns-query", text)
        self.assertNotIn("raw.githubusercontent.com", text)
        self.assertNotIn("github.com/MetaCubeX", text)

    def test_build_clash_meta_yaml_filters_xhttp_until_mihomo_support_is_stable(self):
        payload = encoded_subscription(
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:443?encryption=none&security=reality&type=xhttp&sni=www.microsoft.com&pbk=abc&sid=1234#ca-VLESS_XHTTP_Reality",
            "ss://YWVzLTEyOC1nY206cGFzcw@ca.example.com:8388#ca-Shadowsocks",
        )

        text = build_clash_meta_yaml(payload)

        self.assertNotIn("ca-VLESS_XHTTP_Reality", text)
        self.assertIn("name: ca-Shadowsocks", text)

    def test_build_clash_meta_yaml_routes_relayed_tls_nodes_directly_to_cert_domain(self):
        payload = encoded_subscription(
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:18180?encryption=none&security=tls&fp=chrome&type=tcp&sni=la.example.com&flow=xtls-rprx-vision#la-VLESS_TLS_Vision",
            vmess_link(
                {
                    "ps": "la-VMess_TLS",
                    "add": "ca.example.com",
                    "port": "18184",
                    "id": "22222222-2222-2222-2222-222222222222",
                    "aid": "0",
                    "scy": "auto",
                    "net": "tcp",
                    "tls": "tls",
                    "sni": "la.example.com",
                    "host": "la.example.com",
                }
            ),
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:18181?encryption=none&security=reality&fp=chrome&type=tcp&sni=www.microsoft.com&pbk=abc&sid=1234#la-VLESS_Reality_Vision",
        )

        text = build_clash_meta_yaml(payload)

        self.assertRegex(
            text,
            r"name: la-VLESS_TLS_Vision\n\s+type: vless\n\s+server: la\.example\.com\n\s+port: 18080",
        )
        self.assertRegex(
            text,
            r"name: la-VMess_TLS\n\s+type: vmess\n\s+server: la\.example\.com\n\s+port: 18084",
        )
        self.assertRegex(
            text,
            r"name: la-VLESS_Reality_Vision\n\s+type: vless\n\s+server: ca\.example\.com\n\s+port: 18181",
        )

    def test_build_clash_meta_yaml_filters_vmess_httpupgrade_for_mihomo_clients(self):
        payload = encoded_subscription(
            vmess_link(
                {
                    "ps": "ca-VMess_HTTPUpgrade_TLS",
                    "add": "ca.example.com",
                    "port": "18090",
                    "id": "22222222-2222-2222-2222-222222222222",
                    "aid": "0",
                    "scy": "auto",
                    "net": "httpupgrade",
                    "host": "ca.example.com",
                    "path": "/vmess-httpupgrade",
                    "tls": "tls",
                    "sni": "ca.example.com",
                }
            ),
            "trojan://secret@ca.example.com:8443?security=tls&type=tcp&sni=ca.example.com#ca-Trojan_TLS",
        )

        text = build_clash_meta_yaml(payload)

        self.assertNotIn("ca-VMess_HTTPUpgrade_TLS", text)
        self.assertIn("name: ca-Trojan_TLS", text)

    def test_build_clash_meta_yaml_public_only_filters_grpc_fallback_nodes(self):
        payload = encoded_subscription(
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:443?encryption=none&security=tls&fp=chrome&type=tcp&sni=ca.example.com&flow=xtls-rprx-vision#ca-VLESS_TLS_Vision",
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:18087?encryption=none&security=tls&fp=chrome&type=grpc&sni=ca.example.com&serviceName=grpc#ca-VLESS_gRPC_TLS",
            "trojan://secret@ca.example.com:18091?security=tls&type=grpc&sni=ca.example.com&serviceName=trojan-grpc#ca-Trojan_gRPC_TLS",
            "trojan://secret@ca.example.com:18083?security=tls&type=tcp&sni=ca.example.com#ca-Trojan_TLS",
        )

        text = build_clash_meta_yaml(payload, public_only=True)

        self.assertIn("name: ca-VLESS_TLS_Vision", text)
        self.assertNotIn("name: ca-VLESS_gRPC_TLS", text)
        self.assertNotIn("name: ca-Trojan_gRPC_TLS", text)
        self.assertNotIn("network: grpc", text)
        self.assertNotIn("name: ca-Trojan_TLS", text)

    def test_build_clash_meta_yaml_pins_proxy_server_domains_to_public_hosts(self):
        payload = encoded_subscription(
            "trojan://secret@ca.example.com:8443?security=tls&type=tcp&sni=ca.example.com#ca-Trojan_TLS",
            "trojan://secret@la.example.com:8443?security=tls&type=tcp&sni=la.example.com#la-Trojan_TLS",
        )

        def fake_getaddrinfo(host, *args, **kwargs):
            addresses = {"ca.example.com": "107.172.216.169", "la.example.com": "69.63.198.100"}
            return [(None, None, None, "", (addresses[host], 0))]

        with patch("linkray.clash.socket.getaddrinfo", side_effect=fake_getaddrinfo):
            text = build_clash_meta_yaml(payload, config=LinkRayConfig(domain="ca.example.com"))

        self.assertIn("hosts:", text)
        self.assertIn("ca.example.com: 107.172.216.169", text)
        self.assertIn("la.example.com: 69.63.198.100", text)
        self.assertIn("- ca.example.com", text)
        self.assertIn("- la.example.com", text)
        self.assertIn("ca.example.com: 223.5.5.5", text)
        self.assertIn("la.example.com: 223.5.5.5", text)

    def test_build_clash_meta_yaml_public_only_uses_origin_ip_as_proxy_server(self):
        payload = encoded_subscription(
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:443?encryption=none&security=tls&fp=chrome&type=tcp&sni=ca.example.com#ca-VLESS_TLS_Vision",
            "vless://11111111-1111-1111-1111-111111111111@la.example.com:443?encryption=none&security=tls&fp=chrome&type=ws&sni=la.example.com&host=la.example.com&path=/vless-ws#la-VLESS_WS_TLS",
        )

        def fake_getaddrinfo(host, *args, **kwargs):
            addresses = {"ca.example.com": "107.172.216.169", "la.example.com": "69.63.198.100"}
            return [(None, None, None, "", (addresses[host], 0))]

        with patch("linkray.clash.socket.getaddrinfo", side_effect=fake_getaddrinfo):
            text = build_clash_meta_yaml(payload, config=LinkRayConfig(domain="ca.example.com"), public_only=True)

        self.assertRegex(
            text,
            r"name: ca-VLESS_TLS_Vision\n\s+type: vless\n\s+server: 107\.172\.216\.169\n\s+port: 443\n\s+uuid:",
        )
        self.assertRegex(
            text,
            r"name: la-VLESS_WS_TLS\n\s+type: vless\n\s+server: 69\.63\.198\.100\n\s+port: 443\n\s+uuid:",
        )
        self.assertIn("servername: ca.example.com", text)
        self.assertIn("servername: la.example.com", text)
        self.assertIn("Host: la.example.com", text)

    def test_build_clash_meta_yaml_ignores_fake_ip_host_resolution(self):
        payload = encoded_subscription(
            "trojan://secret@ca.example.com:8443?security=tls&type=tcp&sni=ca.example.com#ca-Trojan_TLS"
        )

        with patch(
            "linkray.clash.socket.getaddrinfo",
            return_value=[(None, None, None, "", ("198.18.0.31", 0))],
        ):
            text = build_clash_meta_yaml(payload, config=LinkRayConfig(domain="ca.example.com"))

        self.assertNotIn("hosts:", text)
        self.assertIn("- ca.example.com", text)
        self.assertIn("ca.example.com: 223.5.5.5", text)

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
