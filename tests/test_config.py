import unittest

from linkray.config import LinkRayConfig


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


if __name__ == "__main__":
    unittest.main()
