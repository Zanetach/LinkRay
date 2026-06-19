import base64
import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.request import urlopen

from linkray.clash import build_clash_meta_yaml, make_clash_server
from linkray.config import LinkRayConfig
from linkray.protocol_prefs import ProtocolPreferences
from linkray.snell_runtime import credential_for_token


def encoded_subscription(*links: str) -> bytes:
    return base64.b64encode(("\n".join(links) + "\n").encode("utf-8"))


def vmess_link(payload: dict[str, object]) -> str:
    text = json.dumps(payload, separators=(",", ":"))
    return "vmess://" + base64.b64encode(text.encode("utf-8")).decode("ascii")


class ClashTests(unittest.TestCase):
    def test_build_clash_meta_yaml_adds_groups_dns_and_route_rules(self):
        payload = encoded_subscription(
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:443?encryption=none&security=tls&fp=chrome&type=tcp&sni=ca.example.com&flow=xtls-rprx-vision#ca-VLESS_TLS_Vision",
            "trojan://secret@ca.example.com:8443?security=tls&type=grpc&sni=ca.example.com&serviceName=trojan-grpc#ca-Trojan_gRPC_TLS",
            "vmess://eyJwcyI6ImNhLVZNZXNzX1dTX1RMUyIsImFkZCI6ImNhLmV4YW1wbGUuY29tIiwicG9ydCI6Ijg0NDMiLCJpZCI6IjIyMjIyMjIyLTIyMjItMjIyMi0yMjIyLTIyMjIyMjIyMjIyMiIsImFpZCI6IjAiLCJzY3kiOiJhdXRvIiwibmV0Ijoid3MiLCJ0eXBlIjoibm9uZSIsImhvc3QiOiJjYS5leGFtcGxlLmNvbSIsInBhdGgiOiIvdm1lc3Mtd3MiLCJ0bHMiOiJ0bHMiLCJzbmkiOiJjYS5leGFtcGxlLmNvbSJ9",
        )

        text = build_clash_meta_yaml(payload)

        self.assertIn("proxies:", text)
        self.assertIn("proxy-groups:", text)
        self.assertIn("rules:", text)
        self.assertIn("direct-nameserver:", text)
        self.assertIn("proxy-server-nameserver:", text)
        self.assertIn("fake-ip-filter:", text)
        self.assertIn("- ca.example.com", text)
        self.assertIn("nameserver-policy:", text)
        self.assertIn("ca.example.com: 223.5.5.5", text)
        self.assertIn("name: ca-VLESS_TLS_Vision", text)
        self.assertIn("type: vless", text)
        self.assertIn("flow: xtls-rprx-vision", text)
        self.assertIn("client-fingerprint: chrome", text)
        self.assertIn("name: ca-Trojan_gRPC_TLS", text)
        self.assertIn("network: grpc", text)
        self.assertIn("grpc-opts:", text)
        self.assertIn("alpn:", text)
        self.assertIn("- h2", text)
        self.assertIn("name: ca-VMess_WS_TLS", text)
        self.assertIn("ws-opts:", text)
        self.assertIn("name: 全球代理", text)
        self.assertIn("DOMAIN-SUFFIX,google.com,Google", text)
        self.assertIn("GEOIP,CN,国内站点", text)
        self.assertIn("MATCH,漏网之鱼", text)

    def test_build_clash_meta_yaml_uses_local_metacubex_rule_assets(self):
        payload = encoded_subscription(
            "trojan://secret@ca.example.com:8443?security=tls&type=tcp&sni=ca.example.com#ca-Trojan_TLS"
        )

        text = build_clash_meta_yaml(
            payload,
            rules_base_url="https://edge-a.example.com:9443/linkray/rules",
        )

        self.assertIn("geox-url:", text)
        self.assertIn("geoip: https://edge-a.example.com:9443/linkray/rules/geoip.dat", text)
        self.assertIn("geosite: https://edge-a.example.com:9443/linkray/rules/geosite.dat", text)
        self.assertIn("mmdb: https://edge-a.example.com:9443/linkray/rules/country.mmdb", text)
        self.assertIn("asn: https://edge-a.example.com:9443/linkray/rules/GeoLite2-ASN.mmdb", text)
        self.assertIn("rule-providers:", text)
        self.assertIn("url: https://edge-a.example.com:9443/linkray/rules/mihomo/geosite-cn.mrs", text)
        self.assertIn("url: https://edge-a.example.com:9443/linkray/rules/mihomo/geoip-cn.mrs", text)
        self.assertEqual(text.count("proxy: DIRECT"), 2)
        self.assertIn("url: https://www.gstatic.com/generate_204", text)
        self.assertIn("lazy: true", text)
        self.assertIn("timeout: 10000", text)
        self.assertIn("RULE-SET,linkray-cn-domain,国内站点", text)
        self.assertIn("RULE-SET,linkray-cn-ip,国内站点", text)
        self.assertNotIn("/api/linkray/health", text)
        self.assertNotIn("https://cp.cloudflare.com/generate_204", text)
        self.assertNotIn("https://dns.google/dns-query", text)
        self.assertNotIn("raw.githubusercontent.com", text)
        self.assertNotIn("github.com/MetaCubeX", text)

    def test_build_clash_meta_yaml_includes_vless_xhttp_reality(self):
        payload = encoded_subscription(
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:18088?encryption=none&security=reality&type=xhttp&sni=www.microsoft.com&host=ca.example.com&path=/vless-xhttp&pbk=abc&sid=1234#ca-VLESS_XHTTP_Reality",
            "ss://YWVzLTEyOC1nY206cGFzcw@ca.example.com:8388#ca-Shadowsocks",
        )

        text = build_clash_meta_yaml(payload)

        self.assertIn("name: ca-VLESS_XHTTP_Reality", text)
        self.assertIn("network: xhttp", text)
        self.assertIn("xhttp-opts:", text)
        self.assertIn("path: /vless-xhttp", text)
        self.assertIn("host: ca.example.com", text)
        self.assertIn("servername: www.microsoft.com", text)
        self.assertIn("name: ca-Shadowsocks", text)

    def test_build_clash_meta_yaml_routes_relayed_tls_nodes_directly_to_cert_domain(self):
        payload = encoded_subscription(
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:18180?encryption=none&security=tls&fp=chrome&type=tcp&sni=la.example.com&flow=xtls-rprx-vision#la-VLESS_TLS_Vision",
            vmess_link(
                {
                    "ps": "la-VMess_TLS",
                    "add": "ca.example.com",
                    "port": "18184",
                    "id": "22222222-2222-2222-2222-222222222222",
                    "aid": "0",
                    "scy": "auto",
                    "net": "tcp",
                    "tls": "tls",
                    "sni": "la.example.com",
                    "host": "la.example.com",
                }
            ),
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:18181?encryption=none&security=reality&fp=chrome&type=tcp&sni=www.microsoft.com&pbk=abc&sid=1234#la-VLESS_Reality_Vision",
        )

        text = build_clash_meta_yaml(payload)

        self.assertRegex(
            text,
            r"name: la-VLESS_TLS_Vision\n\s+type: vless\n\s+server: la\.example\.com\n\s+port: 18080",
        )
        self.assertRegex(
            text,
            r"name: la-VMess_TLS\n\s+type: vmess\n\s+server: la\.example\.com\n\s+port: 18084",
        )
        self.assertRegex(
            text,
            r"name: la-VLESS_Reality_Vision\n\s+type: vless\n\s+server: ca\.example\.com\n\s+port: 18181",
        )

    def test_build_clash_meta_yaml_converts_vmess_httpupgrade_for_mihomo_clients(self):
        payload = encoded_subscription(
            vmess_link(
                {
                    "ps": "ca-VMess_HTTPUpgrade_TLS",
                    "add": "ca.example.com",
                    "port": "18090",
                    "id": "22222222-2222-2222-2222-222222222222",
                    "aid": "0",
                    "scy": "auto",
                    "net": "httpupgrade",
                    "host": "ca.example.com",
                    "path": "/vmess-httpupgrade",
                    "tls": "tls",
                    "sni": "ca.example.com",
                }
            ),
            "trojan://secret@ca.example.com:8443?security=tls&type=tcp&sni=ca.example.com#ca-Trojan_TLS",
        )

        text = build_clash_meta_yaml(payload)

        self.assertIn("name: ca-VMess_HTTPUpgrade_TLS", text)
        self.assertIn("network: ws", text)
        self.assertIn("ws-opts:", text)
        self.assertIn("path: /vmess-httpupgrade", text)
        self.assertIn("Host: ca.example.com", text)
        self.assertIn("v2ray-http-upgrade: true", text)
        self.assertIn("name: ca-Trojan_TLS", text)

    def test_build_clash_meta_yaml_uses_sni_for_trojan_nodes(self):
        payload = encoded_subscription(
            "trojan://secret@ca.example.com:18083?security=tls&type=tcp&sni=ca.example.com#ca-Trojan_TLS",
            "trojan://secret@ca.example.com:18091?security=tls&type=grpc&sni=ca.example.com&serviceName=trojan-grpc#ca-Trojan_gRPC_TLS",
        )

        text = build_clash_meta_yaml(payload, public_only=True)

        self.assertRegex(
            text,
            r"name: ca-Trojan_TLS\n\s+type: trojan\n\s+server: ca\.example\.com\n\s+port: 18083[\s\S]+sni: ca\.example\.com",
        )
        self.assertRegex(
            text,
            r"name: ca-Trojan_gRPC_TLS\n\s+type: trojan\n\s+server: ca\.example\.com\n\s+port: 18091[\s\S]+network: grpc",
        )
        trojan_tcp_block = text.split("name: ca-Trojan_TLS", 1)[1].split("name: ca-Trojan_gRPC_TLS", 1)[0]
        self.assertIn("sni: ca.example.com", trojan_tcp_block)
        self.assertNotIn("servername:", trojan_tcp_block)

    def test_build_clash_meta_yaml_public_only_filters_grpc_fallback_nodes(self):
        payload = encoded_subscription(
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:443?encryption=none&security=tls&fp=chrome&type=tcp&sni=ca.example.com&flow=xtls-rprx-vision#ca-VLESS_TLS_Vision",
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:18087?encryption=none&security=tls&fp=chrome&type=grpc&sni=ca.example.com&serviceName=grpc#ca-VLESS_gRPC_TLS",
            "trojan://secret@ca.example.com:18091?security=tls&type=grpc&sni=ca.example.com&serviceName=trojan-grpc#ca-Trojan_gRPC_TLS",
            "trojan://secret@ca.example.com:18083?security=tls&type=tcp&sni=ca.example.com#ca-Trojan_TLS",
        )

        text = build_clash_meta_yaml(payload, public_only=True)

        self.assertIn("name: ca-VLESS_TLS_Vision", text)
        self.assertIn("name: ca-VLESS_gRPC_TLS", text)
        self.assertIn("name: ca-Trojan_gRPC_TLS", text)
        self.assertIn("network: grpc", text)
        self.assertIn("name: ca-Trojan_TLS", text)

    def test_build_clash_meta_yaml_public_only_keeps_mihomo_supported_protocols(self):
        payload = encoded_subscription(
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:443?encryption=none&security=tls&fp=chrome&type=tcp&sni=ca.example.com&flow=xtls-rprx-vision#ca-VLESS_TLS_Vision",
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:18081?encryption=none&security=reality&fp=chrome&type=tcp&sni=www.microsoft.com&pbk=abc&sid=1234#ca-VLESS_Reality_Vision",
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:18082?encryption=none&security=reality&fp=chrome&type=grpc&sni=www.microsoft.com&pbk=abc&sid=1234&serviceName=grpc#ca-VLESS_Reality_gRPC",
            "trojan://secret@ca.example.com:18083?security=tls&type=tcp&sni=ca.example.com#ca-Trojan_TLS",
            "vmess://eyJwcyI6ImNhLVZNZXNzX1RMUyIsImFkZCI6ImNhLmV4YW1wbGUuY29tIiwicG9ydCI6IjE4MDg0IiwiaWQiOiIyMjIyMjIyMi0yMjIyLTIyMjItMjIyMi0yMjIyMjIyMjIyMjIiLCJhaWQiOiIwIiwic2N5IjoiYXV0byIsIm5ldCI6InRjcCIsInRscyI6InRscyIsInNuaSI6ImNhLmV4YW1wbGUuY29tIn0=",
            "ss://YWVzLTEyOC1nY206cGFzcw@ca.example.com:18085#ca-Shadowsocks",
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:443?encryption=none&security=tls&fp=chrome&type=ws&sni=ca.example.com&host=ca.example.com&path=/vless-ws#ca-VLESS_WS_TLS",
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:18087?encryption=none&security=tls&fp=chrome&type=grpc&sni=ca.example.com&serviceName=grpc#ca-VLESS_gRPC_TLS",
            "vmess://eyJwcyI6ImNhLVZNZXNzX1dTX1RMUyIsImFkZCI6ImNhLmV4YW1wbGUuY29tIiwicG9ydCI6IjQ0MyIsImlkIjoiMjIyMjIyMjItMjIyMi0yMjIyLTIyMjItMjIyMjIyMjIyMjIyIiwiYWlkIjoiMCIsInNjeSI6ImF1dG8iLCJuZXQiOiJ3cyIsInR5cGUiOiJub25lIiwiaG9zdCI6ImNhLmV4YW1wbGUuY29tIiwicGF0aCI6Ii92bWVzcy13cyIsInRscyI6InRscyIsInNuaSI6ImNhLmV4YW1wbGUuY29tIn0=",
            "trojan://secret@ca.example.com:18091?security=tls&type=grpc&sni=ca.example.com&serviceName=trojan-grpc#ca-Trojan_gRPC_TLS",
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:18088?encryption=none&security=reality&type=xhttp&sni=www.microsoft.com&host=ca.example.com&path=/vless-xhttp&pbk=abc&sid=1234#ca-VLESS_XHTTP_Reality",
            vmess_link(
                {
                    "ps": "ca-VMess_HTTPUpgrade_TLS",
                    "add": "ca.example.com",
                    "port": "443",
                    "id": "22222222-2222-2222-2222-222222222222",
                    "aid": "0",
                    "scy": "auto",
                    "net": "httpupgrade",
                    "host": "ca.example.com",
                    "path": "/vmess-httpupgrade",
                    "tls": "tls",
                    "sni": "ca.example.com",
                }
            ),
        )

        text = build_clash_meta_yaml(payload, public_only=True)

        for name in (
            "ca-VLESS_TLS_Vision",
            "ca-VLESS_Reality_Vision",
            "ca-VLESS_Reality_gRPC",
            "ca-Trojan_TLS",
            "ca-VMess_TLS",
            "ca-Shadowsocks",
            "ca-VLESS_WS_TLS",
            "ca-VLESS_gRPC_TLS",
            "ca-VLESS_XHTTP_Reality",
            "ca-VMess_WS_TLS",
            "ca-VMess_HTTPUpgrade_TLS",
            "ca-Trojan_gRPC_TLS",
        ):
            self.assertIn(f"name: {name}", text)

    def test_build_clash_meta_yaml_skips_legacy_marzban_placeholder_node(self):
        payload = encoded_subscription(
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:443?encryption=none&security=tls&fp=chrome&type=tcp&sni=ca.example.com#ca-VLESS_TLS_Vision",
            "vless://11111111-1111-1111-1111-111111111111@203.0.113.10:18080?encryption=none&security=tls&fp=chrome&type=tcp&sni=edge-a.example.com#%F0%9F%9A%80%20Marz%20%28sampleadmin%29%20%5BVLESS%20-%20tcp%5D",
        )

        text = build_clash_meta_yaml(payload, public_only=True)

        self.assertIn("name: ca-VLESS_TLS_Vision", text)
        self.assertNotIn("Marz (sampleadmin)", text)

    def test_build_clash_meta_yaml_pins_proxy_server_domains_to_public_hosts(self):
        payload = encoded_subscription(
            "trojan://secret@ca.example.com:8443?security=tls&type=tcp&sni=ca.example.com#ca-Trojan_TLS",
            "trojan://secret@la.example.com:8443?security=tls&type=tcp&sni=la.example.com#la-Trojan_TLS",
        )

        def fake_getaddrinfo(host, *args, **kwargs):
            addresses = {"ca.example.com": "203.0.113.10", "la.example.com": "198.51.100.20"}
            address = addresses.get(host, host)
            port = args[0] if args else 0
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port or 0))]

        with patch("linkray.clash.socket.getaddrinfo", side_effect=fake_getaddrinfo):
            text = build_clash_meta_yaml(payload, config=LinkRayConfig(domain="ca.example.com"))

        self.assertIn("hosts:", text)
        self.assertIn("ca.example.com: 203.0.113.10", text)
        self.assertIn("la.example.com: 198.51.100.20", text)
        self.assertIn("- ca.example.com", text)
        self.assertIn("- la.example.com", text)
        self.assertIn("ca.example.com: 223.5.5.5", text)
        self.assertIn("la.example.com: 223.5.5.5", text)

    def test_build_clash_meta_yaml_public_only_uses_origin_ip_as_proxy_server(self):
        payload = encoded_subscription(
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:443?encryption=none&security=tls&fp=chrome&type=tcp&sni=ca.example.com#ca-VLESS_TLS_Vision",
            "vless://11111111-1111-1111-1111-111111111111@la.example.com:443?encryption=none&security=tls&fp=chrome&type=ws&sni=la.example.com&host=la.example.com&path=/vless-ws#la-VLESS_WS_TLS",
        )

        def fake_getaddrinfo(host, *args, **kwargs):
            addresses = {"ca.example.com": "203.0.113.10", "la.example.com": "198.51.100.20"}
            address = addresses.get(host, host)
            port = args[0] if args else 0
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port or 0))]

        with patch("linkray.clash.socket.getaddrinfo", side_effect=fake_getaddrinfo):
            text = build_clash_meta_yaml(payload, config=LinkRayConfig(domain="ca.example.com"), public_only=True)

        self.assertRegex(
            text,
            r"name: ca-VLESS_TLS_Vision\n\s+type: vless\n\s+server: 203\.0\.113\.10\n\s+port: 443\n\s+uuid:",
        )
        self.assertRegex(
            text,
            r"name: la-VLESS_WS_TLS\n\s+type: vless\n\s+server: 203\.0\.113\.10\n\s+port: 18180\n\s+uuid:",
        )
        self.assertIn("servername: ca.example.com", text)
        self.assertIn("servername: la.example.com", text)
        self.assertIn("Host: la.example.com", text)

    def test_build_clash_meta_yaml_public_only_relays_secondary_node_via_master(self):
        payload = encoded_subscription(
            "vless://11111111-1111-1111-1111-111111111111@la.example.com:443?encryption=none&security=tls&fp=chrome&type=tcp&sni=la.example.com&flow=xtls-rprx-vision#la-VLESS_TLS_Vision",
            "vless://11111111-1111-1111-1111-111111111111@la.example.com:18081?encryption=none&security=reality&fp=chrome&type=tcp&sni=www.microsoft.com&pbk=abc&sid=1234#la-VLESS_Reality_Vision",
        )

        def fake_getaddrinfo(host, *args, **kwargs):
            addresses = {"ca.example.com": "203.0.113.10", "la.example.com": "198.51.100.20"}
            address = addresses.get(host, host)
            return [(None, None, None, "", (address, 0))]

        with patch("linkray.clash.socket.getaddrinfo", side_effect=fake_getaddrinfo):
            text = build_clash_meta_yaml(payload, config=LinkRayConfig(domain="ca.example.com"), public_only=True)

        self.assertRegex(
            text,
            r"name: la-VLESS_TLS_Vision\n\s+type: vless\n\s+server: 203\.0\.113\.10\n\s+port: 18180\n\s+uuid:",
        )
        self.assertRegex(
            text,
            r"name: la-VLESS_Reality_Vision\n\s+type: vless\n\s+server: 203\.0\.113\.10\n\s+port: 18181\n\s+uuid:",
        )
        self.assertIn("servername: la.example.com", text)
        self.assertIn("servername: www.microsoft.com", text)

    def test_clash_adapter_passes_server_domain_for_secondary_relay(self):
        payload = encoded_subscription(
            "vless://11111111-1111-1111-1111-111111111111@la.example.com:443?encryption=none&security=tls&fp=chrome&type=tcp&sni=la.example.com&flow=xtls-rprx-vision#la-VLESS_TLS_Vision",
        )

        class UpstreamHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/sub/token":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                return

        def fake_getaddrinfo(host, *args, **kwargs):
            addresses = {"ca.example.com": "203.0.113.10", "la.example.com": "198.51.100.20"}
            address = addresses.get(host, host)
            port = args[0] if args else 0
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port or 0))]

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
        upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        upstream_thread.start()
        adapter = make_clash_server(
            "127.0.0.1",
            0,
            f"http://127.0.0.1:{upstream.server_address[1]}",
            server_domain="ca.example.com",
        )
        adapter_thread = threading.Thread(target=adapter.serve_forever, daemon=True)
        adapter_thread.start()
        try:
            with patch("linkray.clash.socket.getaddrinfo", side_effect=fake_getaddrinfo):
                with urlopen(f"http://127.0.0.1:{adapter.server_address[1]}/sub/token/clash-meta", timeout=3) as response:
                    text = response.read().decode("utf-8")
        finally:
            adapter.shutdown()
            adapter.server_close()
            upstream.shutdown()
            upstream.server_close()

        self.assertRegex(
            text,
            r"name: la-VLESS_TLS_Vision\n\s+type: vless\n\s+server: 203\.0\.113\.10\n\s+port: 18180\n\s+uuid:",
        )
        self.assertIn("servername: la.example.com", text)

    def test_build_clash_meta_yaml_public_only_excludes_origin_ips_from_tun_routes(self):
        payload = encoded_subscription(
            "vless://11111111-1111-1111-1111-111111111111@ca.example.com:443?encryption=none&security=tls&fp=chrome&type=tcp&sni=ca.example.com#ca-VLESS_TLS_Vision",
            "vless://11111111-1111-1111-1111-111111111111@la.example.com:443?encryption=none&security=tls&fp=chrome&type=ws&sni=la.example.com&host=la.example.com&path=/vless-ws#la-VLESS_WS_TLS",
        )

        def fake_getaddrinfo(host, *args, **kwargs):
            addresses = {"ca.example.com": "203.0.113.10", "la.example.com": "198.51.100.20"}
            return [(None, None, None, "", (addresses[host], 0))]

        with patch("linkray.clash.socket.getaddrinfo", side_effect=fake_getaddrinfo):
            text = build_clash_meta_yaml(payload, config=LinkRayConfig(domain="ca.example.com"), public_only=True)

        self.assertIn("tun:", text)
        self.assertIn("route-exclude-address:", text)
        self.assertIn("- 203.0.113.10/32", text)
        self.assertNotIn("- 198.51.100.20/32", text)

    def test_build_clash_meta_yaml_ignores_fake_ip_host_resolution(self):
        payload = encoded_subscription(
            "trojan://secret@ca.example.com:8443?security=tls&type=tcp&sni=ca.example.com#ca-Trojan_TLS"
        )

        with patch(
            "linkray.clash.socket.getaddrinfo",
            return_value=[(None, None, None, "", ("198.18.0.31", 0))],
        ):
            text = build_clash_meta_yaml(payload, config=LinkRayConfig(domain="ca.example.com"))

        self.assertNotIn("hosts:", text)
        self.assertIn("- ca.example.com", text)
        self.assertIn("ca.example.com: 223.5.5.5", text)

    def test_build_clash_meta_yaml_does_not_append_snell_v5_node(self):
        user = credential_for_token("subscription-token", "server-secret", name="sample-user", port=40123)
        payload = encoded_subscription(
            "trojan://secret@ca.example.com:8443?security=tls&type=tcp&sni=ca.example.com#ca-Trojan_TLS"
        )

        text = build_clash_meta_yaml(
            payload,
            config=LinkRayConfig(domain="edge-a.example.com"),
            snell_user=user,
        )

        self.assertNotIn("sample-user-Snell", text)
        self.assertNotIn("type: snell", text)
        self.assertNotIn("version: 5", text)
        self.assertIn("name: ca-Trojan_TLS", text)

        filtered = build_clash_meta_yaml(
            payload,
            config=LinkRayConfig(domain="edge-a.example.com"),
            snell_user=user,
            protocol_preferences=ProtocolPreferences(users={"sample-user": {"tuic"}}),
        )
        self.assertNotIn("sample-user-Snell", filtered)


if __name__ == "__main__":
    unittest.main()
