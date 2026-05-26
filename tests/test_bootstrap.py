import tempfile
import unittest
import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from linkray.bootstrap import RecordingRunner, bootstrap_master, bootstrap_node
from linkray.cli import main
from linkray.config import LinkRayConfig, NodeHost


class BootstrapTests(unittest.TestCase):
    def test_bootstrap_master_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            actions = bootstrap_master(
                LinkRayConfig(domain="edge-a.example.com"),
                root=root,
                apply=False,
                nodes=[NodeHost("edge-a", "edge-a.example.com"), NodeHost("edge-b", "edge-b.example.com")],
                runtime=True,
            )

            self.assertFalse((root / "opt/marzban/.env").exists())
            self.assertTrue(any("docker compose up -d" in action.detail for action in actions))
            self.assertTrue(any("sqlite3 /var/lib/marzban/db.sqlite3" in action.detail for action in actions))
            self.assertTrue(all(action.ok for action in actions))

    def test_bootstrap_master_apply_requires_real_admin_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            actions = bootstrap_master(
                LinkRayConfig(domain="edge-a.example.com"),
                root=Path(tmp),
                apply=True,
                runtime=False,
            )

            self.assertTrue(any(not action.ok and "admin password" in action.detail for action in actions))
            self.assertFalse((Path(tmp) / "opt/marzban/.env").exists())

    def test_bootstrap_master_apply_writes_files_and_runs_runtime_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = RecordingRunner()
            actions = bootstrap_master(
                LinkRayConfig(
                    domain="edge-a.example.com",
                    admin_password="strong-password",
                ),
                root=root,
                apply=True,
                nodes=[NodeHost("edge-a", "edge-a.example.com"), NodeHost("edge-b", "edge-b.example.com")],
                runtime=True,
                runner=runner,
            )

            self.assertTrue((root / "opt/marzban/.env").exists())
            self.assertTrue((root / "var/lib/marzban/linkray/hosts.sql").exists())
            self.assertTrue((root / "var/lib/marzban/linkray/patches/clash.py").exists())
            self.assertTrue((root / "etc/systemd/system/linkray-api.service").exists())
            self.assertTrue((root / "etc/systemd/system/linkray-egern.service").exists())
            self.assertTrue((root / "etc/systemd/system/linkray-sub-auto.service").exists())
            self.assertTrue((root / "etc/systemd/system/linkray-relay.service").exists())
            self.assertTrue(any("Xray-linux-64.zip" in command for command in runner.commands))
            self.assertTrue(any("systemctl enable --now linkray-api" in command for command in runner.commands))
            self.assertTrue(any("systemctl enable --now linkray-egern" in command for command in runner.commands))
            self.assertTrue(any("systemctl enable --now linkray-sub-auto" in command for command in runner.commands))
            self.assertTrue(any("systemctl enable --now linkray-relay" in command for command in runner.commands))
            self.assertTrue(any("rm -f /etc/cron.d/linkray-port-status" in command for command in runner.commands))
            self.assertFalse(any("linkray ports" in command for command in runner.commands))
            self.assertTrue(any("docker compose up -d" in command for command in runner.commands))
            self.assertTrue(any("sqlite3 /var/lib/marzban/db.sqlite3" in command for command in runner.commands))
            self.assertTrue(any("nginx -t" in command for command in runner.commands))
            self.assertTrue(all(action.ok for action in actions))

    def test_bootstrap_master_apply_generates_reality_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_master(
                LinkRayConfig(
                    domain="edge-a.example.com",
                    admin_password="strong-password",
                ),
                root=root,
                apply=True,
                runtime=False,
            )

            data = json.loads((root / "var/lib/marzban/xray_config.json").read_text())
            reality = data["inbounds"][1]["streamSettings"]["realitySettings"]
            self.assertNotIn("REPLACE", reality["privateKey"])
            self.assertNotIn("REPLACE", reality["shortIds"][0])
            self.assertEqual(len(reality["privateKey"]), 43)
            self.assertEqual(len(reality["shortIds"][0]), 16)

    def test_bootstrap_master_issue_cert_adds_acme_commands(self):
        actions = bootstrap_master(
            LinkRayConfig(domain="edge-a.example.com"),
            root=Path("/tmp/linkray-unused"),
            apply=False,
            runtime=True,
            issue_cert=True,
            cf_token_env="CF_Token",
        )

        details = "\n".join(action.detail for action in actions)
        self.assertIn("get.acme.sh", details)
        self.assertIn("--dns dns_cf -d edge-a.example.com", details)
        self.assertIn("CF_Token", details)
        self.assertNotIn("'${CF_Token", details)
        self.assertIn('CF_Token="${CF_Token:?missing Cloudflare token env CF_Token}"', details)

    def test_bootstrap_node_apply_writes_compose_and_runs_container(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cert = root / "var/lib/marzban-node/ssl_client_cert.pem"
            cert.parent.mkdir(parents=True)
            cert.write_text("certificate")
            runner = RecordingRunner()
            actions = bootstrap_node(root=root, apply=True, runtime=True, runner=runner)

            self.assertTrue((root / "opt/marzban-node/docker-compose.yml").exists())
            self.assertTrue(any("docker compose up -d" in command for command in runner.commands))
            self.assertTrue(all(action.ok for action in actions))

    def test_bootstrap_node_apply_requires_node_certificate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            actions = bootstrap_node(root=root, apply=True, runtime=False)

            self.assertTrue(any(not action.ok and "ssl_client_cert.pem" in action.detail for action in actions))
            self.assertFalse((root / "opt/marzban-node/docker-compose.yml").exists())

    def test_bootstrap_master_cli_dry_run(self):
        stdout = StringIO()

        with redirect_stdout(stdout):
            code = main(
                [
                    "bootstrap",
                    "master",
                    "--domain",
                    "edge-a.example.com",
                    "--node",
                    "edge-a=edge-a.example.com",
                ]
            )

        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertIn("DRY-RUN: master bootstrap", text)
        self.assertIn("docker compose up -d", text)
        self.assertIn("No files were written", text)


if __name__ == "__main__":
    unittest.main()
