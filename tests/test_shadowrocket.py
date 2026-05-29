import base64
import importlib
import json
import unittest

from linkray.rules import RouteRules


def b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


class ShadowrocketTests(unittest.TestCase):
    def shadowrocket_module(self):
        try:
            return importlib.import_module("linkray.shadowrocket")
        except ModuleNotFoundError:
            self.fail("linkray.shadowrocket module is required")

    def test_build_shadowrocket_conf_filters_unstable_links_and_adds_policy_rules(self):
        module = self.shadowrocket_module()
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
                "vless://11111111-1111-1111-1111-111111111111@edge-a.example.com:18081?security=reality&type=tcp&sni=www.microsoft.com#edge-a-VLESS_Reality_Vision",
                "trojan://password@edge-a.example.com:18083?security=tls&type=tcp&sni=edge-a.example.com#edge-a-Trojan_TLS",
                f"vmess://{b64(json.dumps(vmess))}",
                "ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpwYXNzd29yZA@edge-a.example.com:18085#edge-a-Shadowsocks",
            ]
        )

        output = module.build_shadowrocket_conf(
            base64.b64encode(links.encode()),
            route_rules=RouteRules(cn_domain_suffixes=["baidu.com"], cn_ip_cidrs=["106.52.0.0/15"]),
        )

        self.assertIn("[General]", output)
        self.assertIn("[Proxy]", output)
        self.assertIn("[Proxy Group]", output)
        self.assertIn("[Rule]", output)
        self.assertIn("edge-a-VLESS_TLS_Vision = vless,edge-a.example.com,18080", output)
        self.assertIn("password=11111111-1111-1111-1111-111111111111", output)
        self.assertIn("flow=xtls-rprx-vision", output)
        self.assertIn("edge-a-Trojan_TLS = trojan,edge-a.example.com,18083", output)
        self.assertIn("edge-a-VMess_WS_TLS = vmess,edge-a.example.com,18089", output)
        self.assertIn("edge-a-Shadowsocks = ss,edge-a.example.com,18085", output)
        self.assertNotIn("edge-a-VLESS_Reality_Vision", output)
        self.assertIn("全球代理 = select,手动切换,自动选择", output)
        self.assertIn("DOMAIN-SUFFIX,google.com,全球代理", output)
        self.assertIn("DOMAIN-SUFFIX,baidu.com,国内站点", output)
        self.assertIn("GEOIP,CN,国内站点", output)
        self.assertNotIn("IP-CIDR,106.52.0.0/15,国内站点", output)
        self.assertIn("FINAL,漏网之鱼", output)

    def test_build_shadowrocket_conf_keeps_large_cn_rule_sets_compact(self):
        module = self.shadowrocket_module()
        links = "trojan://password@edge-a.example.com:18083?security=tls&type=tcp&sni=edge-a.example.com#edge-a-Trojan_TLS"
        output = module.build_shadowrocket_conf(
            base64.b64encode(links.encode()),
            route_rules=RouteRules(
                cn_domain_suffixes=[f"example-{index}.cn" for index in range(120000)],
                cn_ip_cidrs=[f"10.{index // 256}.{index % 256}.0/24" for index in range(8000)],
            ),
        )

        self.assertLess(len(output), 12000)
        self.assertIn("DOMAIN-SUFFIX,cn,国内站点", output)
        self.assertIn("GEOIP,CN,国内站点", output)
        self.assertNotIn("example-119999.cn", output)
        self.assertNotIn("10.31.63.0/24", output)

    def test_build_shadowrocket_subscription_returns_node_links_not_conf(self):
        module = self.shadowrocket_module()
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
                "vless://11111111-1111-1111-1111-111111111111@edge-a.example.com:18080?security=tls&type=tcp&sni=edge-a.example.com#edge-a-VLESS_TLS_Vision",
                "vless://11111111-1111-1111-1111-111111111111@edge-a.example.com:18081?security=reality&type=tcp&sni=www.microsoft.com#edge-a-VLESS_Reality_Vision",
                "trojan://password@edge-a.example.com:18083?security=tls&type=tcp&sni=edge-a.example.com#edge-a-Trojan_TLS",
                f"vmess://{b64(json.dumps(vmess))}",
            ]
        )

        output = module.build_shadowrocket_subscription(base64.b64encode(links.encode()))
        decoded = base64.b64decode(output).decode()

        self.assertNotIn("[General]", decoded)
        self.assertNotIn("[Proxy]", decoded)
        self.assertIn("edge-a-VLESS_TLS_Vision", decoded)
        self.assertIn("edge-a-Trojan_TLS", decoded)
        self.assertIn("vmess://", decoded)
        self.assertNotIn("edge-a-VLESS_Reality_Vision", decoded)

    def test_forwarded_headers_do_not_expose_internal_profile_url(self):
        module = self.shadowrocket_module()

        self.assertNotIn("profile-web-page-url", module.PASS_HEADERS)


if __name__ == "__main__":
    unittest.main()
