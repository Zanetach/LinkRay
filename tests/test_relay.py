import unittest

from linkray.relay import parse_relay_node, relay_specs


class RelayTests(unittest.TestCase):
    def test_parse_relay_node_accepts_domain_and_offset(self):
        node = parse_relay_node("la=la.example.com:100")

        self.assertEqual(node.name, "la")
        self.assertEqual(node.domain, "la.example.com")
        self.assertEqual(node.port_offset, 100)

    def test_relay_specs_shift_secondary_node_ports(self):
        specs = relay_specs([parse_relay_node("la=la.example.com:100")], inbound_ports=[("vless_tls", 32080)])
        by_tag = {item.inbound_tag: item for item in specs}

        self.assertEqual(by_tag["VLESS TCP TLS"].listen_port, 32180)
        self.assertEqual(by_tag["VLESS TCP TLS"].target_port, 32080)
        self.assertEqual(by_tag["VLESS TCP TLS"].domain, "la.example.com")


if __name__ == "__main__":
    unittest.main()
