import unittest

from linkray.sub_auto import choose_suffix, parse_token


class SubAutoTests(unittest.TestCase):
    def test_choose_suffix_routes_known_clients(self):
        self.assertEqual(choose_suffix("Egern/1.0", "*/*")[0], "/egern")
        self.assertEqual(choose_suffix("sing-box", "*/*")[0], "/sing-box")
        self.assertEqual(choose_suffix("FlClash", "*/*")[0], "/clash-meta")
        self.assertEqual(choose_suffix("Shadowrocket/2520 CFNetwork", "*/*")[0], "/shadowrocket")
        self.assertEqual(choose_suffix("Mozilla/5.0", "text/html,*/*")[0], "")
        self.assertEqual(choose_suffix("unknown", "*/*")[0], "/native")

    def test_parse_token_accepts_only_base_subscription_path(self):
        self.assertEqual(parse_token("/sub/abc"), "abc")
        self.assertEqual(parse_token("/sub/abc/"), "abc")
        self.assertIsNone(parse_token("/sub/abc/egern"))
        self.assertIsNone(parse_token("/api/sub/abc"))


if __name__ == "__main__":
    unittest.main()
