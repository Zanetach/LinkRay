import tempfile
import json
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

from linkray.config import LinkRayConfig
from linkray.snell_runtime import (
    SNELL_DEFAULT_PORTS,
    SnellUser,
    credential_for_token,
    ensure_runtime_user,
    load_users,
    parse_nft_port_bytes,
    server_config_text,
    make_snell_usage_server,
    snell_usage_deltas,
    snell_clash_proxy,
    snell_shadowrocket_line,
    save_users,
    write_server_config,
)


class SnellRuntimeTests(unittest.TestCase):
    def test_server_config_text_contains_v5_listen_and_psk(self):
        config = LinkRayConfig(domain="edge-a.example.com", snell_psk="snell-secret")

        text = server_config_text(config)

        self.assertIn("[snell-server]", text)
        self.assertIn(f"listen = ::0:{SNELL_DEFAULT_PORTS['snell']}", text)
        self.assertIn("psk = snell-secret", text)
        self.assertIn("ipv6 = true", text)

    def test_server_config_uses_custom_port(self):
        config = LinkRayConfig(
            domain="edge-a.example.com",
            snell_psk="snell-secret",
            snell_inbound_ports=(("snell", 29180),),
        )

        self.assertIn("listen = ::0:29180", server_config_text(config))

    def test_write_server_config_creates_parent_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp) / "snell"
            config = LinkRayConfig(domain="edge-a.example.com", snell_psk="snell-secret")

            first = write_server_config(runtime_dir, config)
            second = write_server_config(runtime_dir, config)

            self.assertTrue(first)
            self.assertFalse(second)
            self.assertEqual((runtime_dir / "snell-server.conf").stat().st_mode & 0o777, 0o600)

    def test_ensure_runtime_user_persists_per_user_psk_and_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            config = LinkRayConfig(domain="edge-a.example.com")

            user, changed = ensure_runtime_user(
                "subscription-token",
                config,
                runtime_dir,
                secret="server-secret",
                name="cyclelink",
            )
            same_user, second_changed = ensure_runtime_user(
                "subscription-token",
                config,
                runtime_dir,
                secret="server-secret",
                name="cyclelink",
            )

            self.assertTrue(changed)
            self.assertFalse(second_changed)
            self.assertEqual(same_user, user)
            self.assertEqual(load_users(runtime_dir), [user])
            self.assertEqual(user.name, "cyclelink")
            self.assertTrue(40000 <= user.port <= 49999)
            user_config = (runtime_dir / "users" / f"{user.instance}.conf").read_text()
            self.assertIn(f"listen = ::0:{user.port}", user_config)
            self.assertIn(f"psk = {user.psk}", user_config)
            self.assertNotIn("subscription-token", (runtime_dir / "users.json").read_text())

    def test_snell_subscription_builders_use_user_credentials(self):
        config = LinkRayConfig(domain="edge-a.example.com")
        user = credential_for_token("subscription-token", "server-secret", name="cyclelink", port=40123)

        shadowrocket = snell_shadowrocket_line(config, user)
        clash = snell_clash_proxy(config, user)

        self.assertIn("cyclelink-Snell = snell,edge-a.example.com,40123", shadowrocket)
        self.assertIn(f"psk={user.psk}", shadowrocket)
        self.assertIn("version=5", shadowrocket)
        self.assertEqual(clash["name"], "cyclelink-Snell")
        self.assertEqual(clash["type"], "snell")
        self.assertEqual(clash["server"], "edge-a.example.com")
        self.assertEqual(clash["port"], 40123)
        self.assertEqual(clash["psk"], user.psk)
        self.assertEqual(clash["version"], 5)

    def test_parse_nft_port_bytes_sums_sport_and_dport_counters(self):
        data = {
            "nftables": [
                {
                    "rule": {
                        "expr": [
                            {"match": {"left": {"payload": {"protocol": "tcp", "field": "dport"}}, "op": "==", "right": 40123}},
                            {"counter": {"packets": 4, "bytes": 600}},
                            {"comment": "linkray-snell:40123:in"},
                        ]
                    }
                },
                {
                    "rule": {
                        "expr": [
                            {"match": {"left": {"payload": {"protocol": "tcp", "field": "sport"}}, "op": "==", "right": 40123}},
                            {"counter": {"packets": 3, "bytes": 700}},
                            {"comment": "linkray-snell:40123:out"},
                        ]
                    }
                },
                {
                    "rule": {
                        "expr": [
                            {"match": {"left": {"payload": {"protocol": "tcp", "field": "dport"}}, "op": "==", "right": 443}},
                            {"counter": {"packets": 100, "bytes": 9999}},
                        ]
                    }
                },
            ]
        }

        self.assertEqual(parse_nft_port_bytes(data), {40123: 1300, 443: 9999})

    def test_snell_usage_deltas_maps_user_ports_and_persists_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            save_users(
                runtime_dir,
                [
                    SnellUser("cyclelink", "hash-a", "lr-a", "psk-a", 40123),
                    SnellUser("lichen", "hash-b", "lr-b", "psk-b", 40124),
                ],
            )
            (runtime_dir / "usage-snapshot.json").write_text(
                '{"version": 1, "ports": {"40123": 1000, "40124": 500}}\n',
                encoding="utf-8",
            )

            deltas = snell_usage_deltas(runtime_dir, {40123: 1600, 40124: 100, 49999: 9000})

            self.assertEqual(deltas, {"cyclelink": 600})
            snapshot = (runtime_dir / "usage-snapshot.json").read_text(encoding="utf-8")
            self.assertIn('"40123": 1600', snapshot)
            self.assertIn('"40124": 100', snapshot)
            self.assertNotIn("49999", snapshot)

    def test_snell_usage_server_collects_usage_deltas(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            server = make_snell_usage_server("127.0.0.1", 0, runtime_dir)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.shutdown)
            self.addCleanup(server.server_close)
            base = f"http://127.0.0.1:{server.server_address[1]}"

            with urlopen(f"{base}/health", timeout=3) as response:
                health = json.loads(response.read().decode("utf-8"))

            with patch("linkray.snell_runtime.collect_snell_usage", return_value={"cyclelink": 900}):
                request = Request(f"{base}/usage/collect", data=b"", method="POST")
                with urlopen(request, timeout=3) as response:
                    usage = json.loads(response.read().decode("utf-8"))

            self.assertEqual(health, {"status": "ok"})
            self.assertEqual(usage, {"usage": {"cyclelink": 900}, "total": 900})


if __name__ == "__main__":
    unittest.main()
