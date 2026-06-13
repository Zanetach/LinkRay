import json
import tempfile
import unittest
from pathlib import Path

from linkray.config import LinkRayConfig
from linkray.singbox_runtime import (
    SINGBOX_DEFAULT_PORTS,
    credential_for_token,
    ensure_runtime_user,
    load_users,
    reconcile_runtime_users,
    server_config,
    singbox_user_outbounds,
)


class SingBoxRuntimeTests(unittest.TestCase):
    def test_server_config_contains_advanced_inbounds_and_stats(self):
        config = LinkRayConfig(domain="edge-a.example.com")
        user = credential_for_token("token-a", "secret-a")
        data = server_config(config, [user])
        by_tag = {inbound["tag"]: inbound for inbound in data["inbounds"]}

        self.assertEqual(by_tag["Hysteria2"]["type"], "hysteria2")
        self.assertEqual(SINGBOX_DEFAULT_PORTS, {"hysteria2": 443, "tuic": 8443, "anytls": 8444})
        self.assertEqual(by_tag["Hysteria2"]["listen_port"], 443)
        self.assertEqual(by_tag["TUIC"]["listen_port"], 8443)
        self.assertEqual(by_tag["AnyTLS"]["listen_port"], 8444)
        self.assertEqual(by_tag["Hysteria2"]["users"][0]["password"], user.hysteria2_password)
        self.assertEqual(by_tag["TUIC"]["type"], "tuic")
        self.assertEqual(by_tag["TUIC"]["users"][0]["uuid"], user.uuid)
        self.assertEqual(by_tag["AnyTLS"]["type"], "anytls")
        self.assertEqual(by_tag["AnyTLS"]["users"][0]["name"], user.name)
        self.assertEqual(by_tag["AnyTLS"]["users"][0]["password"], user.anytls_password)

        for inbound in by_tag.values():
            self.assertEqual(inbound["tls"]["certificate_path"], config.cert_file)
            self.assertEqual(inbound["tls"]["key_path"], config.key_file)

        stats = data["experimental"]["v2ray_api"]["stats"]
        self.assertEqual(stats["enabled"], True)
        self.assertEqual(set(stats["inbounds"]), {"Hysteria2", "TUIC", "AnyTLS"})
        self.assertIn(user.name, stats["users"])

    def test_singbox_user_outbounds_match_server_credentials(self):
        config = LinkRayConfig(domain="edge-a.example.com")
        user = credential_for_token("token-a", "secret-a")
        outbounds = {item["tag"]: item for item in singbox_user_outbounds(config, user)}

        self.assertEqual(outbounds["Hysteria2"]["type"], "hysteria2")
        self.assertEqual(outbounds["Hysteria2"]["password"], user.hysteria2_password)
        self.assertEqual(outbounds["TUIC"]["type"], "tuic")
        self.assertEqual(outbounds["TUIC"]["uuid"], user.uuid)
        self.assertEqual(outbounds["AnyTLS"]["type"], "anytls")
        self.assertEqual(outbounds["AnyTLS"]["password"], user.anytls_password)
        self.assertEqual(outbounds["AnyTLS"]["tls"]["server_name"], "edge-a.example.com")
        self.assertNotIn("utls", outbounds["Hysteria2"]["tls"])
        self.assertNotIn("utls", outbounds["TUIC"]["tls"])
        self.assertIn("utls", outbounds["AnyTLS"]["tls"])

    def test_credentials_can_use_marzban_username_for_stats_attribution(self):
        user = credential_for_token("token-a", "secret-a", name="sample-user")

        self.assertEqual(user.name, "sample-user")
        self.assertEqual(user.token_hash, credential_for_token("token-a", "secret-a").token_hash)
        self.assertNotIn("token-a", json.dumps(user.__dict__))

    def test_ensure_runtime_user_persists_user_and_config_without_raw_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            user, changed = ensure_runtime_user(
                "subscription-token",
                LinkRayConfig(domain="edge-a.example.com"),
                runtime_dir,
                secret="server-secret",
                name="sample-user",
            )

            self.assertTrue(changed)
            store_text = (runtime_dir / "users.json").read_text()
            self.assertNotIn("subscription-token", store_text)
            self.assertIn(user.name, store_text)
            data = json.loads((runtime_dir / "config.json").read_text())
            self.assertEqual(data["inbounds"][0]["users"][0]["password"], user.hysteria2_password)

            same_user, second_changed = ensure_runtime_user(
                "subscription-token",
                LinkRayConfig(domain="edge-a.example.com"),
                runtime_dir,
                secret="server-secret",
                name="sample-user",
            )
            self.assertEqual(same_user, user)
            self.assertFalse(second_changed)

    def test_reconcile_runtime_users_prunes_non_active_marzban_users(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            config = LinkRayConfig(domain="edge-a.example.com")
            keep_user, _ = ensure_runtime_user("token-a", config, runtime_dir, secret="server-secret", name="active-user")
            remove_user, _ = ensure_runtime_user("token-b", config, runtime_dir, secret="server-secret", name="expired-user")

            changed = reconcile_runtime_users({"active-user"}, config, runtime_dir)

            self.assertTrue(changed)
            self.assertEqual(load_users(runtime_dir), [keep_user])
            config_text = (runtime_dir / "config.json").read_text()
            self.assertIn(keep_user.hysteria2_password, config_text)
            self.assertNotIn(remove_user.hysteria2_password, config_text)

            second_changed = reconcile_runtime_users({"active-user"}, config, runtime_dir)
            self.assertFalse(second_changed)


if __name__ == "__main__":
    unittest.main()
