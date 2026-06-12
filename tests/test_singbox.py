import base64
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from linkray.rules import RouteRules


def b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


class SingBoxTests(unittest.TestCase):
    def test_build_singbox_json_filters_xhttp_and_uses_local_route_rules(self):
        from linkray.singbox import build_singbox_json

        vmess = {
            "ps": "edge-a-VMess_WS_TLS",
            "add": "edge-a.example.com",
            "port": "18089",
            "id": "00000000-0000-0000-0000-000000000000",
            "aid": "0",
            "net": "ws",
            "path": "/vmess-ws",
            "host": "edge-a.example.com",
            "tls": "tls",
            "scy": "auto",
        }
        links = "\n".join(
            [
                "vless://11111111-1111-1111-1111-111111111111@edge-a.example.com:18080?security=tls&type=tcp&sni=edge-a.example.com&flow=xtls-rprx-vision#edge-a-VLESS_TLS_Vision",
                "vless://11111111-1111-1111-1111-111111111111@edge-a.example.com:18081?security=reality&type=tcp&sni=www.microsoft.com&pbk=public-key&sid=abcd#edge-a-VLESS_Reality_Vision",
                "vless://11111111-1111-1111-1111-111111111111@edge-a.example.com:18088?security=reality&type=xhttp&sni=www.microsoft.com&path=/vless-xhttp&pbk=public-key&sid=abcd#edge-a-VLESS_XHTTP_Reality",
                "trojan://password@edge-a.example.com:18083?security=tls&type=tcp&sni=edge-a.example.com#edge-a-Trojan_TLS",
                f"vmess://{b64(json.dumps(vmess))}",
                "ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpwYXNzd29yZA@edge-a.example.com:18085#edge-a-Shadowsocks",
            ]
        )

        output = build_singbox_json(
            base64.b64encode(links.encode()),
            route_rules=RouteRules(cn_domain_suffixes=["baidu.com"], cn_ip_cidrs=["106.52.0.0/15"]),
        )
        data = json.loads(output)
        outbounds = {item["tag"]: item for item in data["outbounds"]}

        self.assertIn("edge-a-VLESS_TLS_Vision", outbounds)
        self.assertIn("edge-a-VLESS_Reality_Vision", outbounds)
        self.assertIn("edge-a-Trojan_TLS", outbounds)
        self.assertIn("edge-a-VMess_WS_TLS", outbounds)
        self.assertIn("edge-a-Shadowsocks", outbounds)
        self.assertNotIn("edge-a-VLESS_XHTTP_Reality", outbounds)
        self.assertEqual(outbounds["edge-a-VLESS_Reality_Vision"]["tls"]["reality"]["enabled"], True)
        self.assertEqual(outbounds["edge-a-VLESS_TLS_Vision"]["flow"], "xtls-rprx-vision")
        self.assertEqual(outbounds["edge-a-VMess_WS_TLS"]["transport"]["type"], "ws")
        self.assertEqual(outbounds["自动选择"]["type"], "urltest")
        self.assertEqual(outbounds["全球代理"]["type"], "selector")

        rules = data["route"]["rules"]
        self.assertIn({"domain_suffix": ["baidu.com"], "outbound": "国内站点"}, rules)
        self.assertIn({"ip_cidr": ["106.52.0.0/15"], "outbound": "国内站点"}, rules)
        self.assertIn({"domain_suffix": ["google.com"], "outbound": "全球代理"}, rules)
        self.assertEqual(data["route"]["final"], "漏网之鱼")
        self.assertNotIn("rule_set", data["route"])
        self.assertNotIn("download_detour", output)
        self.assertNotIn("raw.githubusercontent.com", output)

    def test_build_singbox_json_keeps_large_domain_rules_compact_but_keeps_cn_cidrs(self):
        from linkray.singbox import build_singbox_json

        links = "trojan://password@edge-a.example.com:18083?security=tls&type=tcp&sni=edge-a.example.com#edge-a-Trojan_TLS"
        output = build_singbox_json(
            base64.b64encode(links.encode()),
            route_rules=RouteRules(
                cn_domain_suffixes=[f"example-{index}.cn" for index in range(120000)],
                cn_ip_cidrs=[f"10.{index // 256}.{index % 256}.0/24" for index in range(8000)],
            ),
        )
        data = json.loads(output)

        self.assertLess(len(output), 240000)
        self.assertIn({"domain_suffix": ["cn"], "outbound": "国内站点"}, data["route"]["rules"])
        self.assertNotIn("example-119999.cn", output)
        self.assertIn("10.31.63.0/24", output)


    def test_singbox_dns_routes_cn_domains_to_local_server(self):
        from linkray.singbox import build_singbox_json

        links = "trojan://password@edge-a.example.com:18083?security=tls&type=tcp&sni=edge-a.example.com#t"
        data = json.loads(build_singbox_json(base64.b64encode(links.encode())))
        dns = data["dns"]

        self.assertEqual(dns["final"], "remote")
        servers = {s["tag"] for s in dns["servers"]}
        self.assertIn("local", servers)
        self.assertIn("remote", servers)

        rules = dns["rules"]
        cn_rule = next((r for r in rules if r.get("server") == "local" and "domain_suffix" in r), None)
        self.assertIsNotNone(cn_rule, "expected a domain_suffix rule routing to local DNS")
        self.assertIn("baidu.com", cn_rule["domain_suffix"])
        self.assertIn("qq.com", cn_rule["domain_suffix"])

        private_rule = next((r for r in rules if r.get("server") == "local" and "ip_cidr" in r), None)
        self.assertIsNotNone(private_rule, "expected a private-IP rule routing to local DNS")
        self.assertIn("192.168.0.0/16", private_rule["ip_cidr"])

    def test_singbox_reality_missing_params_produce_empty_strings_not_null(self):
        from linkray.singbox import build_singbox_json

        link = "vless://uuid@1.2.3.4:18081?security=reality&type=tcp&sni=www.microsoft.com#no-pbk-sid"
        data = json.loads(build_singbox_json(base64.b64encode(link.encode())))
        reality = data["outbounds"][0]["tls"]["reality"]

        self.assertEqual(reality["public_key"], "")
        self.assertEqual(reality["short_id"], "")
        self.assertIsNotNone(reality["public_key"])
        self.assertIsNotNone(reality["short_id"])

    def test_build_singbox_json_can_append_linkray_advanced_outbounds(self):
        from linkray.config import LinkRayConfig
        from linkray.protocol_prefs import ProtocolPreferences
        from linkray.singbox import build_singbox_json
        from linkray.singbox_runtime import credential_for_token

        user = credential_for_token("token-a", "secret-a")
        link = "trojan://password@edge-a.example.com:18083?security=tls&type=tcp&sni=edge-a.example.com#edge-a-Trojan_TLS"
        data = json.loads(
            build_singbox_json(
                base64.b64encode(link.encode()),
                config=LinkRayConfig(domain="edge-a.example.com"),
                advanced_user=user,
            )
        )
        outbounds = {item["tag"]: item for item in data["outbounds"]}

        self.assertIn("Hysteria2", outbounds)
        self.assertIn("TUIC", outbounds)
        self.assertIn("AnyTLS", outbounds)
        self.assertIn("Hysteria2", outbounds["全球代理"]["outbounds"])
        self.assertEqual(outbounds["TUIC"]["uuid"], user.uuid)

        filtered = json.loads(
            build_singbox_json(
                base64.b64encode(b""),
                config=LinkRayConfig(domain="edge-a.example.com"),
                advanced_user=credential_for_token("token-b", "secret-a", name="lichen"),
                protocol_preferences=ProtocolPreferences(users={"lichen": {"tuic"}}),
            )
        )
        filtered_outbounds = {item["tag"]: item for item in filtered["outbounds"]}
        self.assertNotIn("Hysteria2", filtered_outbounds)
        self.assertIn("TUIC", filtered_outbounds)
        self.assertNotIn("AnyTLS", filtered_outbounds)

    def test_singbox_sidecar_reconcile_endpoint_prunes_runtime_users(self):
        from linkray.config import LinkRayConfig
        from linkray.singbox import make_singbox_server
        from linkray.singbox_runtime import ensure_runtime_user, load_users

        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            config = LinkRayConfig(domain="edge-a.example.com")
            ensure_runtime_user("token-a", config, runtime_dir, secret="server-secret", name="active-user")
            ensure_runtime_user("token-b", config, runtime_dir, secret="server-secret", name="stale-user")
            server = make_singbox_server(
                "127.0.0.1",
                0,
                "http://127.0.0.1:1",
                server_domain="edge-a.example.com",
                runtime_dir=runtime_dir,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                body = json.dumps({"active_usernames": ["active-user"]}).encode("utf-8")
                request = Request(
                    f"http://127.0.0.1:{port}/runtime/reconcile",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=3) as response:
                    payload = json.loads(response.read())
                self.assertEqual(payload["remaining"], 1)
                self.assertTrue(payload["changed"])
                self.assertEqual([user.name for user in load_users(runtime_dir)], ["active-user"])
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
