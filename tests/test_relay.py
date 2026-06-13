import unittest

from linkray.relay import parse_relay_node, relay_specs


class RelayTests(unittest.TestCase):
    def test_parse_relay_node_accepts_domain_and_offset(self):
        node = parse_relay_node("edge-b=edge-b.example.com:100")

        self.assertEqual(node.name, "edge-b")
        self.assertEqual(node.domain, "edge-b.example.com")
        self.assertEqual(node.port_offset, 100)

    def test_relay_specs_shift_secondary_node_ports(self):
        specs = relay_specs([parse_relay_node("edge-b=edge-b.example.com:100")], inbound_ports=[("vless_tls", 18080)])
        by_tag = {item.inbound_tag: item for item in specs}

        self.assertEqual(by_tag["VLESS TCP TLS"].listen_port, 18180)
        self.assertEqual(by_tag["VLESS TCP TLS"].target_port, 18080)
        self.assertEqual(by_tag["VLESS TCP TLS"].domain, "edge-b.example.com")


    def test_parse_relay_node_defaults_offset_to_100(self):
        node = parse_relay_node("edge-b=edge-b.example.com")

        self.assertEqual(node.port_offset, 100)

    def test_parse_relay_node_rejects_missing_equals(self):
        with self.assertRaises(ValueError):
            parse_relay_node("edge-b.example.com")

    def test_parse_relay_node_rejects_bad_offset(self):
        with self.assertRaises(ValueError):
            parse_relay_node("edge-b=edge-b.example.com:notanumber")

    def test_parse_relay_node_rejects_non_fqdn(self):
        with self.assertRaises(ValueError):
            parse_relay_node("edge-b=localhost")

    def test_relay_specs_two_nodes_use_increasing_offsets(self):
        specs = relay_specs(
            [parse_relay_node("edge-b=edge-b.example.com:100"),
             parse_relay_node("edge-c=edge-c.example.com:100")],
            inbound_ports=[("vless_tls", 18080)],
        )
        by_node = {item.node: item for item in specs if item.inbound_tag == "VLESS TCP TLS"}

        self.assertEqual(by_node["edge-b"].listen_port, 18180)
        self.assertEqual(by_node["edge-c"].listen_port, 18280)

    def test_relay_specs_reject_public_listen_port_conflict_with_primary_xray(self):
        with self.assertRaisesRegex(ValueError, "relay port conflict"):
            relay_specs(
                [parse_relay_node("edge-b=edge-b.example.com:100")],
                inbound_ports=[("vless_reality", 17982)],
            )


if __name__ == "__main__":
    unittest.main()
