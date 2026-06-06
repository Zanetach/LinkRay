import base64
import json
import unittest

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


if __name__ == "__main__":
    unittest.main()
