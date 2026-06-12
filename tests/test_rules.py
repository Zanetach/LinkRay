import tempfile
import unittest
from pathlib import Path

from linkray.rules import (
    BUILTIN_CN_DOMAIN_SUFFIXES,
    BUILTIN_CN_IP_CIDRS,
    COMPACT_CN_DOMAIN_SUFFIXES,
    FOREIGN_DOMAIN_SUFFIXES,
    METACUBEX_ASSETS,
    RouteRules,
    download_metacubex_assets,
    load_route_rules,
    parse_cidr_lines,
    parse_domain_lines,
    write_route_rules,
)


class RouteRuleTests(unittest.TestCase):
    def test_parse_domain_lines_accepts_dnsmasq_and_rule_formats(self):
        text = "\n".join(
            [
                "# comment",
                "server=/qq.com/114.114.114.114",
                "DOMAIN-SUFFIX,baidu.com,国内站点",
                "full:example.cn",
                "  taobao.com  ",
            ]
        )

        self.assertEqual(parse_domain_lines(text), ["baidu.com", "example.cn", "qq.com", "taobao.com"])

    def test_parse_cidr_lines_accepts_plain_and_rule_formats(self):
        text = "\n".join(
            [
                "# comment",
                "106.52.0.0/15",
                "IP-CIDR,106.54.0.0/16,国内站点,no-resolve",
                "192.168.1.1",
            ]
        )

        self.assertEqual(parse_cidr_lines(text), ["106.52.0.0/15", "106.54.0.0/16", "192.168.1.1/32"])

    def test_write_and_load_route_rules_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_route_rules(
                root,
                RouteRules(
                    cn_domain_suffixes=["qq.com", "baidu.com", "qq.com"],
                    cn_ip_cidrs=["106.54.0.0/16", "106.52.0.0/15"],
                ),
            )

            loaded = load_route_rules(root)

        self.assertEqual(loaded.cn_domain_suffixes, ["baidu.com", "qq.com"])
        self.assertEqual(loaded.cn_ip_cidrs, ["106.52.0.0/15", "106.54.0.0/16"])

    def test_load_route_rules_falls_back_to_builtins(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = load_route_rules(Path(tmp))

        self.assertIn("cn", loaded.cn_domain_suffixes)
        self.assertIn("baidu.com", loaded.cn_domain_suffixes)
        self.assertIn("106.52.0.0/15", loaded.cn_ip_cidrs)
        self.assertEqual(loaded.cn_domain_suffixes, sorted(set(BUILTIN_CN_DOMAIN_SUFFIXES)))
        self.assertEqual(loaded.cn_ip_cidrs, sorted(set(BUILTIN_CN_IP_CIDRS)))

    def test_builtin_rules_force_wechat_and_tencent_traffic_direct(self):
        expected = {
            "qq.com",
            "weixin.qq.com",
            "wechat.com",
            "wx.qq.com",
            "weixinbridge.com",
            "servicewechat.com",
            "qlogo.cn",
            "qpic.cn",
            "tenpay.com",
            "qqmail.com",
            "imqq.com",
            "myapp.com",
            "tencent.com",
            "tencent-cloud.com",
            "smtcdns.com",
        }

        self.assertTrue(expected.issubset(set(BUILTIN_CN_DOMAIN_SUFFIXES)))

    def test_compact_cn_domain_suffixes_is_superset_of_builtins_and_includes_extras(self):
        self.assertTrue(set(BUILTIN_CN_DOMAIN_SUFFIXES).issubset(set(COMPACT_CN_DOMAIN_SUFFIXES)))
        self.assertIn("dns.pub", COMPACT_CN_DOMAIN_SUFFIXES)
        self.assertIn("doh.pub", COMPACT_CN_DOMAIN_SUFFIXES)
        self.assertIn("alidns.com", COMPACT_CN_DOMAIN_SUFFIXES)
        self.assertEqual(list(COMPACT_CN_DOMAIN_SUFFIXES), sorted(COMPACT_CN_DOMAIN_SUFFIXES))

    def test_foreign_domain_suffixes_covers_key_services(self):
        expected = {"google.com", "github.com", "youtube.com", "telegram.org", "openai.com", "anthropic.com"}
        self.assertTrue(expected.issubset(set(FOREIGN_DOMAIN_SUFFIXES)))
        self.assertNotIn("baidu.com", FOREIGN_DOMAIN_SUFFIXES)
        self.assertNotIn("qq.com", FOREIGN_DOMAIN_SUFFIXES)

    def test_download_metacubex_assets_writes_expected_local_cache_files(self):
        requested: list[str] = []

        def fake_fetch(url: str, timeout: float = 20.0) -> bytes:
            requested.append(url)
            return f"asset:{url}".encode("utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = download_metacubex_assets(root, fetcher=fake_fetch)

            relative = {path.relative_to(root).as_posix() for path in paths}
            self.assertEqual(relative, {asset.path for asset in METACUBEX_ASSETS})
            self.assertTrue((root / "geosite.dat").read_bytes().startswith(b"asset:https://"))
            self.assertTrue((root / "mihomo/geosite-cn.mrs").read_bytes().startswith(b"asset:https://"))
            self.assertTrue((root / "sing-box/geosite-cn.srs").read_bytes().startswith(b"asset:https://"))

        self.assertIn(
            "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geosite.dat",
            requested,
        )
        self.assertIn(
            "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geosite/cn.mrs",
            requested,
        )
        self.assertIn(
            "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/sing/geo/geosite/cn.srs",
            requested,
        )


if __name__ == "__main__":
    unittest.main()
