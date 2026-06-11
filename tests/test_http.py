import unittest
from urllib.parse import parse_qs, urlparse

from linkray._http import first_query_value, parse_link_netloc


class FirstQueryValueTests(unittest.TestCase):
    def _q(self, url: str) -> dict:
        return parse_qs(urlparse(url).query)

    def test_returns_first_matching_value(self):
        q = self._q("vless://x@h:1?type=ws&sni=example.com")
        self.assertEqual(first_query_value(q, "sni", "servername"), "example.com")

    def test_tries_names_in_order(self):
        q = self._q("vless://x@h:1?servername=fallback.com")
        self.assertEqual(first_query_value(q, "sni", "servername"), "fallback.com")

    def test_returns_none_when_no_match(self):
        q = self._q("vless://x@h:1?type=tcp")
        self.assertIsNone(first_query_value(q, "sni", "servername"))

    def test_skips_empty_string_values(self):
        q = {"sni": [""], "servername": ["real.com"]}
        self.assertEqual(first_query_value(q, "sni", "servername"), "real.com")

    def test_returns_none_for_empty_query(self):
        self.assertIsNone(first_query_value({}, "sni"))


class ParseLinkNetlocTests(unittest.TestCase):
    def _p(self, url: str):
        return urlparse(url)

    def test_returns_host_and_port(self):
        result = parse_link_netloc(self._p("vless://uuid@edge.example.com:18080"))
        self.assertEqual(result, ("edge.example.com", 18080))

    def test_returns_none_when_port_missing(self):
        result = parse_link_netloc(self._p("vless://uuid@edge.example.com"))
        self.assertIsNone(result)

    def test_returns_none_when_host_missing(self):
        result = parse_link_netloc(self._p("vless://uuid@:18080"))
        self.assertIsNone(result)

    def test_handles_ip_address(self):
        result = parse_link_netloc(self._p("vless://uuid@1.2.3.4:443"))
        self.assertEqual(result, ("1.2.3.4", 443))


if __name__ == "__main__":
    unittest.main()
