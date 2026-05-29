import json
import tempfile
import unittest
from pathlib import Path

from linkray.config import DEFAULT_PORTS, LinkRayConfig, NodeHost, parse_inbound_ports, parse_node_host
from linkray.install import install_master, install_node
from linkray.render import (
    first_existing_path,
    host_rows,
    hosts_sql,
    marzban_env,
    render_master,
    render_node,
    validate_rendered,
    xray_config,
)


class RenderTests(unittest.TestCase):
    def test_xray_config_contains_extended_twelve_inbounds(self):
        data = xray_config(
            LinkRayConfig(
                domain="edge-a.example.com",
                reality_private_key="a" * 43,
                reality_short_id="6ba85179e30d4fc2",
            )
        )

        inbounds = data["inbounds"]
        self.assertEqual(len(inbounds), 12)
        self.assertEqual({item["port"] for item in inbounds}, set(DEFAULT_PORTS.values()))
        self.assertEqual(
            {item["protocol"] for item in inbounds},
            {"vless", "trojan", "vmess", "shadowsocks"},
        )
        by_tag = {item["tag"]: item for item in inbounds}
        self.assertEqual(by_tag["VLESS WS TLS"]["streamSettings"]["network"], "ws")
        self.assertNotIn("headers", by_tag["VLESS WS TLS"]["streamSettings"]["wsSettings"])
        self.assertEqual(by_tag["VLESS GRPC TLS"]["streamSettings"]["network"], "grpc")
        self.assertEqual(by_tag["VLESS XHTTP REALITY"]["streamSettings"]["network"], "xhttp")
        self.assertNotIn("host", by_tag["VLESS XHTTP REALITY"]["streamSettings"]["xhttpSettings"])
        self.assertEqual(
            by_tag["VLESS TCP REALITY"]["streamSettings"]["realitySettings"]["dest"],
            "www.microsoft.com:443",
        )
        self.assertEqual(
            by_tag["VLESS TCP REALITY"]["streamSettings"]["realitySettings"]["serverNames"],
            ["www.microsoft.com"],
        )
        self.assertEqual(by_tag["VMess HTTPUpgrade TLS"]["streamSettings"]["network"], "httpupgrade")
        self.assertNotIn("host", by_tag["VMess HTTPUpgrade TLS"]["streamSettings"]["httpupgradeSettings"])
        self.assertEqual(by_tag["Trojan GRPC TLS"]["streamSettings"]["network"], "grpc")

    def test_custom_inbound_ports_apply_to_xray_hosts_and_api_service(self):
        config = LinkRayConfig(
            domain="edge-a.example.com",
            inbound_ports=parse_inbound_ports(["vless_tls=28080", "trojan_grpc_tls=28091"]),
        )
        data = xray_config(config)
        by_tag = {item["tag"]: item for item in data["inbounds"]}
        self.assertEqual(by_tag["VLESS TCP TLS"]["port"], 28080)
        self.assertEqual(by_tag["Trojan GRPC TLS"]["port"], 28091)

        rows = host_rows(config, [NodeHost("edge-a", "edge-a.example.com")])
        self.assertIn(28080, [row[2] for row in rows])
        self.assertIn(28091, [row[2] for row in rows])

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            render_master(config, output, nodes=[NodeHost("edge-a", "edge-a.example.com")])
            service = (output / "etc/systemd/system/linkray-api.service").read_text()
            self.assertIn("--inbound vless_tls=28080", service)
            self.assertIn("--inbound trojan_grpc_tls=28091", service)
            self.assertEqual(validate_rendered(output), [])

    def test_render_master_writes_expected_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            result = render_master(
                LinkRayConfig(domain="edge-a.example.com"),
                output,
                nodes=[
                    NodeHost("edge-a", "edge-a.example.com"),
                    NodeHost("edge-b", "edge-b.example.com"),
                ],
            )
            relative = {path.relative_to(output).as_posix() for path in result.files}

            self.assertIn("var/lib/marzban/xray_config.json", relative)
            self.assertIn("opt/marzban/docker-compose.yml", relative)
            self.assertIn("opt/marzban/.env", relative)
            self.assertIn("etc/nginx/conf.d/marzban-panel.conf", relative)
            self.assertIn("etc/systemd/system/linkray-api.service", relative)
            self.assertIn("etc/systemd/system/linkray-egern.service", relative)
            self.assertIn("etc/systemd/system/linkray-shadowrocket.service", relative)
            self.assertIn("etc/systemd/system/linkray-sub-auto.service", relative)
            self.assertIn("etc/systemd/system/linkray-relay.service", relative)
            self.assertIn("etc/systemd/system/linkray-rules-update.service", relative)
            self.assertIn("etc/systemd/system/linkray-rules-update.timer", relative)
            self.assertIn("var/lib/marzban/linkray/hosts.sql", relative)
            self.assertIn("var/lib/marzban/linkray/rules/cn-domains.txt", relative)
            self.assertIn("var/lib/marzban/linkray/rules/cn-ip-cidrs.txt", relative)
            self.assertIn("var/lib/marzban/linkray/patches/clash.py", relative)
            self.assertNotIn("var/lib/marzban/linkray/public/ports.html", relative)
            self.assertNotIn("var/lib/marzban/linkray/public/ports.json", relative)
            self.assertIn("var/lib/marzban/templates/clash/default.yml", relative)
            self.assertIn("var/lib/marzban/templates/subscription/index.html", relative)
            self.assertIn("var/lib/marzban/dashboard-patches/index.linkray.js", relative)
            self.assertEqual(validate_rendered(output), [])

            xray = json.loads((output / "var/lib/marzban/xray_config.json").read_text())
            self.assertEqual(xray["inbounds"][0]["tag"], "VLESS TCP TLS")
            compose = (output / "opt/marzban/docker-compose.yml").read_text()
            self.assertIn("/var/lib/marzban/linkray/bin/xray:/usr/local/bin/xray:ro", compose)
            self.assertIn("/var/lib/marzban/linkray/patches/clash.py:/code/app/subscription/clash.py:ro", compose)
            self.assertIn("index.linkray.js", compose)
            nginx = (output / "etc/nginx/conf.d/marzban-panel.conf").read_text()
            self.assertIn("location ~ ^/sub/[^/]+/?$", nginx)
            self.assertIn("proxy_pass http://127.0.0.1:61993", nginx)
            self.assertIn("location ~ ^/sub/[^/]+/egern/?$", nginx)
            self.assertIn("proxy_pass http://127.0.0.1:61992", nginx)
            self.assertIn("location ~ ^/sub/[^/]+/shadowrocket/?$", nginx)
            self.assertIn("proxy_pass http://127.0.0.1:61994", nginx)
            self.assertIn("location = /statics/index.linkray.js", nginx)
            self.assertIn("location /api/linkray/", nginx)
            self.assertIn("location = /linkray/ports.html", nginx)
            self.assertIn("return 302 /dashboard/", nginx)
            self.assertIn("location = /linkray/ports.json", nginx)
            self.assertIn("proxy_pass http://127.0.0.1:61990/nodes", nginx)
            service = (output / "etc/systemd/system/linkray-api.service").read_text()
            self.assertIn("ExecStart=/usr/local/bin/linkray api --listen 127.0.0.1 --port 61990", service)
            self.assertIn("--node edge-a=edge-a.example.com --node edge-b=edge-b.example.com", service)
            egern_service = (output / "etc/systemd/system/linkray-egern.service").read_text()
            self.assertIn("ExecStart=/usr/local/bin/linkray egern --listen 127.0.0.1 --port 61992", egern_service)
            shadowrocket_service = (output / "etc/systemd/system/linkray-shadowrocket.service").read_text()
            self.assertIn("ExecStart=/usr/local/bin/linkray shadowrocket --listen 127.0.0.1 --port 61994", shadowrocket_service)
            auto_service = (output / "etc/systemd/system/linkray-sub-auto.service").read_text()
            self.assertIn("ExecStart=/usr/local/bin/linkray sub-auto --listen 127.0.0.1 --port 61993", auto_service)
            self.assertIn("--egern-url http://127.0.0.1:61992", auto_service)
            self.assertIn("--shadowrocket-url http://127.0.0.1:61994", auto_service)
            rules_service = (output / "etc/systemd/system/linkray-rules-update.service").read_text()
            self.assertIn("ExecStart=/usr/local/bin/linkray rules update --output /var/lib/marzban/linkray/rules", rules_service)
            rules_timer = (output / "etc/systemd/system/linkray-rules-update.timer").read_text()
            self.assertIn("OnCalendar=daily", rules_timer)
            relay_service = (output / "etc/systemd/system/linkray-relay.service").read_text()
            self.assertIn("ExecStart=/usr/local/bin/linkray relay --listen 0.0.0.0 --node edge-b=edge-b.example.com:100", relay_service)

    def test_dashboard_patch_injects_node_info_panel(self):
        for patch_path in [
            Path("patches/marzban-dashboard/current/index.linkray.js"),
            Path("linkray/assets/patches/marzban-dashboard/current/index.linkray.js"),
        ]:
            with self.subTest(patch=str(patch_path)):
                patch = patch_path.read_text()

                self.assertIn("节点信息", patch)
                self.assertIn("/api/linkray/nodes", patch)
                self.assertIn("/api/linkray/nodes/refresh", patch)
                self.assertIn("PAGE_SIZE=10", patch)
                self.assertIn("下一页", patch)
                self.assertIn("linkray-node-info-footer", patch)
                self.assertIn("自动识别订阅", patch)
                self.assertIn("Shadowrocket", patch)
                self.assertIn("base+'/egern'", patch)
                self.assertIn("['Shadowrocket',base+'/shadowrocket']", patch)
                self.assertIn("base+'/clash-meta'", patch)
                self.assertNotIn("Clash" + " for Windows", patch)
                self.assertNotIn("base+'/clash'", patch)
                self.assertNotIn("Clash " + "旧版", patch)

    def test_subscription_page_lists_auto_first_and_no_clash_for_windows(self):
        for page_path in [
            Path("patches/marzban-subscription-page/current/index.html"),
            Path("linkray/assets/patches/marzban-subscription-page/current/index.html"),
        ]:
            with self.subTest(page=str(page_path)):
                html = page_path.read_text()

                self.assertIn("自动识别订阅", html)
                self.assertIn("Shadowrocket", html)
                self.assertIn("base + '/egern'", html)
                self.assertIn("['Shadowrocket', base + '/shadowrocket']", html)
                self.assertLess(html.index("['自动识别订阅', base]"), html.index("['Clash/Mihomo', base + '/clash-meta']"))
                self.assertLess(html.index("['Clash/Mihomo', base + '/clash-meta']"), html.index("['Shadowrocket', base + '/shadowrocket']"))
                self.assertNotIn("Clash" + " for Windows", html)

    def test_dashboard_html_adds_protocol_inbound_details_without_touching_app_bundle(self):
        for html_path in [
            Path("patches/marzban-dashboard/current/index.html"),
            Path("linkray/assets/patches/marzban-dashboard/current/index.html"),
        ]:
            with self.subTest(html=str(html_path)):
                html = html_path.read_text()

                self.assertIn("linkray-protocol-card-detail", html)
                self.assertIn("LinkRay 完整入站", html)
                self.assertIn("VLESS XHTTP REALITY", html)
                self.assertIn("VMess HTTPUpgrade TLS", html)
                self.assertIn("Trojan GRPC TLS", html)
                self.assertIn("TCP TLS / Reality / gRPC Reality / WS TLS / gRPC TLS / XHTTP Reality", html)
                self.assertNotIn("linkrayProtocolCardDetails failed hard", html)

    def test_clash_template_uses_scalar_dns_policy(self):
        for template_path in [
            Path("templates/marzban/clash/default.yml"),
            Path("linkray/assets/templates/marzban/clash/default.yml"),
        ]:
            with self.subTest(template=str(template_path)):
                text = template_path.read_text()
                self.assertNotIn("GEOSITE,", text)
                self.assertNotIn("GEOIP,", text)
                self.assertNotIn("geox-url:", text)
                self.assertNotIn("geo-auto-update:", text)
                self.assertNotIn("geosite:", text)
                self.assertIn("proxy_server_domains", text)
                self.assertIn("proxy_server_addresses", text)
                self.assertIn("route-exclude-address", text)
                self.assertIn("store-fake-ip: false", text)
                self.assertIn("respect-rules: true", text)
                self.assertIn("direct-nameserver:", text)
                self.assertIn("https://doh.pub/dns-query", text)
                self.assertIn("https://dns.alidns.com/dns-query", text)
                self.assertNotIn("https://1.1.1.1/dns-query", text)
                self.assertNotIn("https://8.8.8.8/dns-query", text)
                self.assertIn(
                    '{{ conf | except("proxy-groups", "listeners", "sub-rules", "rule-providers", "proxy-providers", "port", "socks-port", "redir-port", "tproxy-port", "mixed-port", "mode", "rules", "dns", "tun", "profile", "sniffer", "allow-lan", "bind-address", "log-level", "ipv6", "unified-delay", "tcp-concurrent", "geox-url", "geo-auto-update", "geodata-mode", "geosite-matcher") | yaml }}',
                    text,
                )
                self.assertLess(text.index("- name: 全球代理"), text.index("- name: 流媒体"))
                global_block = text[text.index("- name: 全球代理"):text.index("- name: 流媒体")]
                self.assertLess(global_block.index("- 手动切换"), global_block.index("- 自动选择"))
                self.assertIn("name: TikTok", text)
                self.assertIn("DOMAIN-SUFFIX,tiktok.com,TikTok", text)
                self.assertIn("DOMAIN-KEYWORD,tiktok,TikTok", text)
                self.assertIn("name: Facebook", text)
                self.assertIn("DOMAIN-SUFFIX,facebook.com,Facebook", text)
                self.assertIn("name: X", text)
                self.assertIn("DOMAIN-SUFFIX,x.com,X", text)
                self.assertIn("name: 国内站点", text)
                self.assertIn("[proxy_remarks[0]]", text)
                domestic_block = text[text.index("- name: 国内站点"):text.index("- name: 本地直连")]
                self.assertLess(domestic_block.index("- DIRECT"), domestic_block.index("[proxy_remarks[0]]"))
                self.assertIn("domestic_ip_rules", text)
                self.assertIn("domestic_domain_rules", text)
                self.assertIn("IP-CIDR,{{ cidr }},国内站点,no-resolve", text)
                self.assertIn("DOMAIN-SUFFIX,{{ domain }},国内站点", text)
                self.assertLess(text.index("DOMAIN-SUFFIX,google.com,Google"), text.index("domestic_domain_rules"))
                self.assertLess(text.index("domestic_domain_rules"), text.index("DOMAIN-SUFFIX,bilibili.com,国内媒体"))
                self.assertNotIn("DOMAIN-REGEX", text)
                self.assertNotIn("IP-CIDR,0.0.0.0/0,国内站点,no-resolve", text)
                self.assertNotIn("IP-CIDR6,::/0,国内站点,no-resolve", text)
                self.assertNotIn("store-fake-ip: true", text)

    def test_clash_patch_exposes_proxy_server_domains(self):
        for patch_path in [
            Path("patches/marzban-subscription/current/clash.py"),
            Path("linkray/assets/patches/marzban-subscription/current/clash.py"),
        ]:
            with self.subTest(patch=str(patch_path)):
                text = patch_path.read_text()
                self.assertIn("def proxy_server_domains", text)
                self.assertIn('"proxy_server_domains": self.proxy_server_domains()', text)
                self.assertIn("def proxy_server_addresses", text)
                self.assertIn('"proxy_server_addresses": self.proxy_server_addresses()', text)
                self.assertIn("def resolve_proxy_server", text)
                self.assertIn('"conf": self.resolved_proxy_data()', text)
                self.assertIn('"domestic_domain_rules": self.domestic_domain_rules()', text)
                self.assertIn('"domestic_ip_rules": self.domestic_ip_rules()', text)
                self.assertIn("def read_rule_file", text)
                self.assertIn("'dialer-proxy'", text)
                self.assertIn("primary_server", text)

    def test_marzban_env_contains_directly_usable_defaults(self):
        env = marzban_env(
            LinkRayConfig(
                domain="edge-a.example.com",
                admin_username="owner",
                admin_password="secret-value",
            )
        )

        self.assertIn("UVICORN_PORT = 8000", env)
        self.assertIn("SUDO_USERNAME = owner", env)
        self.assertIn("SUDO_PASSWORD = secret-value", env)
        self.assertIn("XRAY_JSON = /var/lib/marzban/xray_config.json", env)
        self.assertIn("XRAY_SUBSCRIPTION_URL_PREFIX = https://edge-a.example.com:9443", env)

    def test_render_node_writes_compose(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            result = render_node(output)
            self.assertEqual(len(result.files), 1)
            self.assertTrue((output / "opt/marzban-node/docker-compose.yml").exists())
            self.assertEqual(validate_rendered(output), [])

    def test_hosts_sql_contains_two_node_rows(self):
        config = LinkRayConfig(domain="edge-a.example.com")
        nodes = [NodeHost("edge-a", "edge-a.example.com"), NodeHost("edge-b", "edge-b.example.com")]
        rows = host_rows(config, nodes)
        sql = hosts_sql(config, nodes)

        self.assertEqual(len(rows), 24)
        self.assertIn("edge-a-VLESS_TLS_Vision", sql)
        self.assertIn("edge-a-VLESS_WS_TLS", sql)
        self.assertIn("edge-a-VLESS_XHTTP_Reality", sql)
        self.assertIn("edge-a-VMess_HTTPUpgrade_TLS", sql)
        self.assertIn("edge-a-Trojan_gRPC_TLS", sql)
        self.assertIn("edge-b-Shadowsocks", sql)
        self.assertIn("'edge-a.example.com', 18180, 'VLESS TCP TLS'", sql)
        self.assertIn("'edge-a.example.com', 18191, 'Trojan GRPC TLS'", sql)
        self.assertIn("'VLESS TCP REALITY'", sql)
        self.assertIn("'www.microsoft.com'", sql)
        self.assertIn("'/vless-ws'", sql)
        self.assertIn("'/vmess-httpupgrade'", sql)
        self.assertIn("'edge-a.example.com'", sql)

    def test_clash_meta_patch_supports_xhttp(self):
        patch = Path("patches/marzban-subscription/current/clash.py").read_text()

        self.assertIn("def xhttp_config", patch)
        self.assertIn("elif network == 'xhttp'", patch)
        self.assertNotIn('("kcp", "splithttp", "xhttp") or', patch)

    def test_parse_node_host(self):
        node = parse_node_host("edge-b=edge-b.example.com")
        self.assertEqual(node.name, "edge-b")
        self.assertEqual(node.domain, "edge-b.example.com")

    def test_first_existing_path_falls_back_to_packaged_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fallback = root / "assets"
            fallback.mkdir()

            self.assertEqual(first_existing_path(root / "missing", fallback), fallback)

    def test_install_master_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            actions = install_master(LinkRayConfig(domain="edge-a.example.com"), root=root, apply=False)
            self.assertGreater(len(actions), 1)
            self.assertFalse((root / "var/lib/marzban/xray_config.json").exists())

    def test_install_master_apply_copies_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            actions = install_master(LinkRayConfig(domain="edge-a.example.com"), root=root, apply=True)
            self.assertGreater(len(actions), 1)
            self.assertTrue((root / "var/lib/marzban/xray_config.json").exists())
            self.assertTrue((root / "var/lib/marzban/linkray/hosts.sql").exists())
            self.assertTrue((root / "opt/marzban/.env").exists())
            self.assertTrue((root / "etc/systemd/system/linkray-egern.service").exists())
            self.assertTrue((root / "etc/systemd/system/linkray-shadowrocket.service").exists())
            self.assertTrue((root / "etc/systemd/system/linkray-sub-auto.service").exists())
            self.assertTrue((root / "etc/systemd/system/linkray-relay.service").exists())
            self.assertTrue((root / "etc/systemd/system/linkray-rules-update.service").exists())
            self.assertTrue((root / "etc/systemd/system/linkray-rules-update.timer").exists())
            self.assertTrue((root / "var/lib/marzban/linkray/rules/cn-domains.txt").exists())
            self.assertTrue((root / "var/lib/marzban/linkray/rules/cn-ip-cidrs.txt").exists())

    def test_install_node_apply_copies_compose(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            actions = install_node(root=root, apply=True)
            self.assertEqual(len(actions), 1)
            self.assertTrue((root / "opt/marzban-node/docker-compose.yml").exists())


if __name__ == "__main__":
    unittest.main()
