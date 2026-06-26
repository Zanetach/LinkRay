import unittest

from linkray.config import LinkRayConfig, parse_residential_proxy_url


class ConfigTests(unittest.TestCase):
    def test_validate_checks_xray_ports_even_when_reality_key_is_placeholder(self):
        config = LinkRayConfig(
            domain="edge-a.example.com",
            inbound_ports=(("vless_tls", 18081),),
        )

        with self.assertRaisesRegex(ValueError, "duplicate inbound port"):
            config.validate()

    def test_validate_checks_singbox_ports_even_when_reality_key_is_placeholder(self):
        config = LinkRayConfig(
            domain="edge-a.example.com",
            singbox_inbound_ports=(("hysteria2", 8443),),
        )

        with self.assertRaisesRegex(ValueError, "duplicate inbound port"):
            config.validate()

    def test_validate_checks_snell_ports_even_when_reality_key_is_placeholder(self):
        config = LinkRayConfig(
            domain="edge-a.example.com",
            snell_inbound_ports=(("snell", 0),),
        )

        with self.assertRaisesRegex(ValueError, "invalid port"):
            config.validate()

    def test_parse_residential_proxy_url_accepts_socks5_without_leaking_secret_repr(self):
        proxy = parse_residential_proxy_url("socks5://user:pass@example.com:443")

        self.assertIsNotNone(proxy)
        self.assertEqual(proxy.server, "example.com")
        self.assertEqual(proxy.port, 443)
        self.assertEqual(proxy.username, "user")
        self.assertEqual(proxy.password, "pass")
        self.assertEqual(proxy.safe_summary, "socks5://example.com:443")
        self.assertNotIn("pass", repr(proxy))

    def test_validate_rejects_non_socks_residential_proxy(self):
        config = LinkRayConfig(
            domain="edge-a.example.com",
            residential_proxy_url="http://user:pass@example.com:8080",
        )

        with self.assertRaisesRegex(ValueError, "socks5"):
            config.validate()


if __name__ == "__main__":
    unittest.main()
