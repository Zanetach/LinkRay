import unittest
from pathlib import Path


class InstallerTests(unittest.TestCase):
    def test_install_script_creates_linkray_command(self):
        script = Path("install.sh").read_text()

        self.assertIn("LINKRAY_INSTALL_DIR:-/opt/linkray", script)
        self.assertIn("/usr/local/bin/linkray", script)
        self.assertIn("tmp_venv_check", script)
        self.assertIn("python3 -m venv \"${tmp_venv_check}/venv\"", script)
        self.assertIn('exec "${INSTALL_DIR}/venv/bin/linkray" "\\$@"', script)

    def test_deploy_rendered_master_script_matches_current_rendered_files(self):
        script = Path("scripts/deploy-rendered-master.sh").read_text()

        self.assertIn("index.linkray.js", script)
        self.assertNotIn("index.linkray.20260518061008.js", script)
        self.assertIn("var/lib/marzban/linkray/hosts.sql", script)
        self.assertIn("var/lib/marzban/linkray/patches/clash.py", script)
        self.assertIn("var/lib/marzban/templates/subscription/index.html", script)
        self.assertIn("etc/systemd/system/linkray-api.service", script)
        self.assertIn("etc/systemd/system/linkray-egern.service", script)
        self.assertIn("etc/systemd/system/linkray-shadowrocket.service", script)
        self.assertIn("etc/systemd/system/linkray-sub-auto.service", script)
        self.assertIn("etc/systemd/system/linkray-relay.service", script)
        self.assertIn("etc/systemd/system/linkray-rules-update.service", script)
        self.assertIn("etc/systemd/system/linkray-rules-update.timer", script)
        self.assertIn("var/lib/marzban/linkray/rules/cn-domains.txt", script)
        self.assertIn("var/lib/marzban/linkray/rules/cn-ip-cidrs.txt", script)
        self.assertIn("systemctl enable --now linkray-api", script)
        self.assertIn("systemctl enable --now linkray-egern", script)
        self.assertIn("systemctl enable --now linkray-shadowrocket", script)
        self.assertIn("systemctl enable --now linkray-sub-auto", script)
        self.assertIn("systemctl enable --now linkray-relay", script)
        self.assertIn("systemctl enable --now linkray-rules-update.timer", script)


if __name__ == "__main__":
    unittest.main()
