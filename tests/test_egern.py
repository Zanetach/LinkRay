import base64
import json
import unittest
from unittest.mock import patch

from linkray.config import LinkRayConfig
from linkray.egern import PASS_HEADERS, build_egern_yaml, convert_link, resolve_server_address
from linkray.rules import RouteRules


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
                "vless://11111111-1111-1111-1111-111111111111@edge.example.com:18081?security=reality&type=tcp&sni=www.microsoft.com&pbk=abc&sid=1234#vless-reality",
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
        self.assertIn("vless-reality", output)
        self.assertIn("reality:", output)
        self.assertIn('public_key: "abc"', output)
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

    def test_build_egern_yaml_filters_secondary_servers_in_public_mode(self):
        vmess = {
            "ps": "la-VMess_TLS",
            "add": "la.example.com",
            "port": "18084",
            "id": "00000000-0000-0000-0000-000000000000",
            "net": "tcp",
            "tls": "tls",
            "sni": "la.example.com",
            "host": "la.example.com",
            "scy": "auto",
        }
        links = "\n".join(
            [
                "vless://11111111-1111-1111-1111-111111111111@ca.example.com:443?security=tls&type=tcp&sni=ca.example.com&flow=xtls-rprx-vision#ca-VLESS_TLS_Vision",
                "vless://11111111-1111-1111-1111-111111111111@la.example.com:443?security=tls&type=tcp&sni=la.example.com&flow=xtls-rprx-vision#la-VLESS_TLS_Vision",
                "trojan://password@la.example.com:18083?security=tls&type=tcp&sni=la.example.com#la-Trojan_TLS",
                f"vmess://{b64(json.dumps(vmess))}",
                "ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpwYXNzd29yZA@la.example.com:18085#la-Shadowsocks",
            ]
        )

        with patch("linkray.egern.socket.getaddrinfo", return_value=[(None, None, None, None, ("203.0.113.10", 0))]):
            output = build_egern_yaml(
                base64.b64encode(links.encode()),
                config=LinkRayConfig(domain="ca.example.com"),
                public_only=True,
            )

        self.assertIn('flow: "xtls-rprx-vision"', output)
        self.assertIn('name: "ca-VLESS_TLS_Vision"', output)
        self.assertNotIn('name: "la-VLESS_TLS_Vision"', output)
        self.assertNotIn('name: "la-Trojan_TLS"', output)
        self.assertNotIn('name: "la-VMess_TLS"', output)
        self.assertNotIn('name: "la-Shadowsocks"', output)
        self.assertIn('server: "203.0.113.10"', output)
        self.assertIn("port: 443", output)
        self.assertNotIn("port: 18183", output)
        self.assertNotIn("port: 18184", output)
        self.assertNotIn("port: 18185", output)
        self.assertNotIn('sni: "la.example.com"', output)

    def test_build_egern_yaml_skips_legacy_marzban_placeholder_node(self):
        links = "\n".join(
            [
                "vless://11111111-1111-1111-1111-111111111111@ca.example.com:443?security=tls&type=tcp&sni=ca.example.com#ca-VLESS_TLS_Vision",
                "vless://11111111-1111-1111-1111-111111111111@203.0.113.10:18080?security=tls&type=tcp&sni=edge-a.example.com#%F0%9F%9A%80%20Marz%20%28sampleadmin%29%20%5BVLESS%20-%20tcp%5D",
            ]
        )

        output = build_egern_yaml(base64.b64encode(links.encode()), public_only=True)

        self.assertIn('name: "ca-VLESS_TLS_Vision"', output)
        self.assertNotIn("Marz (sampleadmin)", output)

    def test_build_egern_yaml_adds_policy_groups_and_route_rules(self):
        links = "\n".join(
            [
                "vless://11111111-1111-1111-1111-111111111111@edge-a.example.com:18080?security=tls&type=tcp&sni=edge-a.example.com&flow=xtls-rprx-vision#edge-a-VLESS_TLS_Vision",
                "trojan://password@edge-a.example.com:18083?security=tls&type=tcp&sni=edge-a.example.com#edge-a-Trojan_TLS",
            ]
        )

        output = build_egern_yaml(
            base64.b64encode(links.encode()),
            route_rules=RouteRules(cn_domain_suffixes=["cn", "baidu.com"], cn_ip_cidrs=["106.52.0.0/15"]),
        )

        self.assertIn("policy_groups:", output)
        self.assertIn('name: "全球代理"', output)
        self.assertIn('name: "国内站点"', output)
        self.assertIn("auto_test:", output)
        self.assertNotIn("url_test:", output)
        self.assertIn("rules:", output)
        self.assertIn("domain_suffix:", output)
        self.assertIn('match: "baidu.com"', output)
        self.assertIn("geoip:", output)
        self.assertIn('match: "CN"', output)
        self.assertNotIn('match: "106.52.0.0/15"', output)
        self.assertIn("default:", output)
        self.assertNotIn("final:", output)
        self.assertIn('policy: "漏网之鱼"', output)

    def test_build_egern_yaml_keeps_large_cn_rule_sets_compact(self):
        links = "trojan://password@edge-a.example.com:18083?security=tls&type=tcp&sni=edge-a.example.com#edge-a-Trojan_TLS"
        output = build_egern_yaml(
            base64.b64encode(links.encode()),
            route_rules=RouteRules(
                cn_domain_suffixes=[f"example-{index}.cn" for index in range(120000)],
                cn_ip_cidrs=[f"10.{index // 256}.{index % 256}.0/24" for index in range(8000)],
            ),
        )

        self.assertLess(len(output), 12000)
        self.assertIn("domain_suffix:", output)
        self.assertIn('match: "cn"', output)
        self.assertIn("geoip:", output)
        self.assertIn('match: "CN"', output)
        self.assertNotIn("example-119999.cn", output)
        self.assertNotIn("10.31.63.0/24", output)

    def test_forwarded_headers_do_not_expose_internal_profile_url(self):
        self.assertNotIn("profile-web-page-url", PASS_HEADERS)

    def test_vless_to_egern_tls_tcp(self):
        from linkray.egern import vless_to_egern

        result = vless_to_egern(
            "vless://uuid@edge.example.com:18080?security=tls&type=tcp&sni=edge.example.com&flow=xtls-rprx-vision#my-node"
        )
        self.assertIsNotNone(result)
        item = result["vless"]
        self.assertEqual(item["user_id"], "uuid")
        self.assertEqual(item["flow"], "xtls-rprx-vision")
        self.assertEqual(item["port"], 18080)
        self.assertIn("tls", item["transport"])

    def test_vless_to_egern_supports_reality_and_rejects_grpc(self):
        from linkray.egern import vless_to_egern

        result = vless_to_egern("vless://u@h:1?security=reality&type=tcp&sni=www.microsoft.com&pbk=public-key&sid=abcd#reality")
        self.assertIsNotNone(result)
        item = result["vless"]
        self.assertEqual(item["transport"]["tls"]["sni"], "www.microsoft.com")
        self.assertEqual(item["transport"]["tls"]["reality"]["public_key"], "public-key")
        self.assertEqual(item["transport"]["tls"]["reality"]["short_id"], "abcd")
        self.assertIsNone(vless_to_egern("vless://u@h:1?security=tls&type=grpc"))

    def test_vless_to_egern_ws(self):
        from linkray.egern import vless_to_egern

        result = vless_to_egern(
            "vless://uuid@edge.example.com:18086?security=tls&type=ws&sni=edge.example.com&path=/vless-ws&host=edge.example.com#ws-node"
        )
        self.assertIsNotNone(result)
        item = result["vless"]
        # egern uses "wss" key for WS+TLS, "ws" for plain WS
        transport_key = "wss" if "wss" in item["transport"] else "ws"
        self.assertIn(transport_key, item["transport"])
        self.assertEqual(item["transport"][transport_key]["path"], "/vless-ws")

    def test_trojan_to_egern_tcp(self):
        from linkray.egern import trojan_to_egern

        result = trojan_to_egern(
            "trojan://secretpassword@edge.example.com:18083?security=tls&type=tcp&sni=edge.example.com#trojan-node"
        )
        self.assertIsNotNone(result)
        item = result["trojan"]
        self.assertEqual(item["password"], "secretpassword")
        self.assertEqual(item["sni"], "edge.example.com")
        self.assertFalse(item["skip_tls_verify"])

    def test_trojan_to_egern_rejects_grpc(self):
        from linkray.egern import trojan_to_egern

        self.assertIsNone(trojan_to_egern("trojan://p@h:1?type=grpc"))

    def test_vmess_to_egern_ws_tls(self):
        from linkray.egern import vmess_to_egern

        data = {"ps": "my-vmess", "add": "edge.example.com", "port": "18089", "id": "uuid",
                "net": "ws", "path": "/ws", "host": "edge.example.com", "tls": "tls", "scy": "auto"}
        result = vmess_to_egern(f"vmess://{b64(json.dumps(data))}")

        self.assertIsNotNone(result)
        item = result["vmess"]
        self.assertEqual(item["user_id"], "uuid")
        self.assertIn("wss", item["transport"])

    def test_vmess_to_egern_rejects_grpc_and_bad_b64(self):
        from linkray.egern import vmess_to_egern

        bad_grpc = b64(json.dumps({"add": "h", "port": 1, "id": "u", "net": "grpc"}))
        self.assertIsNone(vmess_to_egern(f"vmess://{bad_grpc}"))
        self.assertIsNone(vmess_to_egern("vmess://!!!not-base64!!!"))

    def test_shadowsocks_to_egern_plain_userinfo(self):
        from linkray.egern import shadowsocks_to_egern

        result = shadowsocks_to_egern(
            "ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpwYXNzd29yZA@edge.example.com:18085#ss-node"
        )
        self.assertIsNotNone(result)
        item = result["shadowsocks"]
        self.assertEqual(item["method"], "chacha20-ietf-poly1305")
        self.assertEqual(item["password"], "password")


if __name__ == "__main__":
    unittest.main()
