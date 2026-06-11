import json
import unittest
from contextlib import redirect_stdout
from io import StringIO

from linkray.cli import main
from linkray.protocols import PROTOCOL_CAPABILITIES, capabilities_by_status, protocol_capabilities_json


class ProtocolCapabilityTests(unittest.TestCase):
    def test_protocol_capabilities_include_xray_supported_and_singbox_planned_protocols(self):
        by_key = {item.key: item for item in PROTOCOL_CAPABILITIES}

        self.assertEqual(by_key["vless_tls"].runtime, "xray")
        self.assertEqual(by_key["vless_tls"].status, "supported")
        self.assertEqual(by_key["vless_xhttp_reality"].runtime, "xray")
        self.assertEqual(by_key["vless_xhttp_reality"].status, "supported")

        for key in ["hysteria2", "tuic", "anytls"]:
            self.assertEqual(by_key[key].runtime, "sing-box")
            self.assertEqual(by_key[key].status, "planned")
            self.assertIn("stats", by_key[key].notes.lower())

    def test_capabilities_by_status_groups_without_losing_protocols(self):
        grouped = capabilities_by_status()

        self.assertIn("supported", grouped)
        self.assertIn("planned", grouped)
        self.assertEqual(
            {item.key for item in grouped["planned"]},
            {"hysteria2", "tuic", "anytls"},
        )

    def test_protocol_capabilities_json_is_stable(self):
        data = json.loads(protocol_capabilities_json())

        self.assertEqual(data["version"], 1)
        self.assertGreaterEqual(len(data["protocols"]), 15)
        self.assertEqual(data["protocols"][0]["key"], "vless_tls")
        self.assertEqual(data["protocols"][-1]["key"], "anytls")

    def test_protocols_cli_prints_json(self):
        stream = StringIO()
        with redirect_stdout(stream):
            code = main(["protocols", "--json"])

        self.assertEqual(code, 0)
        data = json.loads(stream.getvalue())
        self.assertEqual(data["protocols"][-1]["key"], "anytls")


if __name__ == "__main__":
    unittest.main()
