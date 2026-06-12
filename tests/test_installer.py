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
        self.assertIn("var/lib/marzban/linkray/linkray-manifest.json", script)
        self.assertIn("var/lib/marzban/linkray/source-patches/marzban-dashboard/linkray-dashboard.patch", script)
        self.assertIn("var/lib/marzban/linkray/patches/clash.py", script)
        self.assertIn("var/lib/marzban/templates/subscription/index.html", script)
        self.assertIn("etc/systemd/system/linkray-api.service", script)
        self.assertIn("etc/systemd/system/linkray-clash.service", script)
        self.assertIn("etc/systemd/system/linkray-egern.service", script)
        self.assertIn("etc/systemd/system/linkray-shadowrocket.service", script)
        self.assertIn("etc/systemd/system/linkray-singbox.service", script)
        self.assertIn("etc/systemd/system/linkray-singbox-runtime.service", script)
        self.assertIn("etc/systemd/system/linkray-snell-runtime.service", script)
        self.assertIn("etc/systemd/system/linkray-snell@.service", script)
        self.assertIn("etc/systemd/system/linkray-snell-usage.service", script)
        self.assertIn("etc/systemd/system/linkray-sub-auto.service", script)
        self.assertIn("etc/systemd/system/linkray-relay.service", script)
        self.assertIn("etc/systemd/system/linkray-rules-update.service", script)
        self.assertIn("etc/systemd/system/linkray-rules-update.timer", script)
        self.assertIn("var/lib/marzban/linkray/rules/cn-domains.txt", script)
        self.assertIn("var/lib/marzban/linkray/rules/cn-ip-cidrs.txt", script)
        self.assertIn("var/lib/marzban/linkray/singbox/config.json", script)
        self.assertIn("var/lib/marzban/linkray/singbox/users.json", script)
        self.assertIn("var/lib/marzban/linkray/xray/runtime.json", script)
        self.assertIn("var/lib/marzban/linkray/snell/snell-server.conf", script)
        self.assertIn("etc/sysctl.d/99-linkray-network.conf", script)
        self.assertIn("etc/modules-load.d/linkray-bbr.conf", script)
        self.assertIn("modprobe tcp_bbr", script)
        self.assertIn("tc qdisc replace dev", script)
        self.assertIn("var/lib/marzban/linkray/patches/0_xray_core.py", script)
        self.assertIn("var/lib/marzban/linkray/patches/xray_init.py", script)
        self.assertIn("var/lib/marzban/linkray/jobs/linkray_singbox_usages.py", script)
        self.assertIn("systemctl enable --now linkray-api", script)
        self.assertIn("systemctl enable --now linkray-clash", script)
        self.assertIn("systemctl enable --now linkray-egern", script)
        self.assertIn("systemctl enable --now linkray-shadowrocket", script)
        self.assertIn("systemctl enable --now linkray-singbox", script)
        self.assertIn("systemctl enable --now linkray-singbox-runtime", script)
        self.assertIn("systemctl enable --now linkray-snell-runtime", script)
        self.assertIn("systemctl enable --now linkray-snell-usage", script)
        self.assertIn("systemctl enable --now linkray-sub-auto", script)
        self.assertIn("systemctl enable --now linkray-relay", script)
        self.assertIn("systemctl enable --now linkray-rules-update.timer", script)
        self.assertIn('if [[ -f "$src/etc/systemd/system/linkray-xray.service" ]]', script)
        self.assertIn("systemctl enable --now linkray-xray", script)
        self.assertIn("systemctl restart linkray-xray", script)
        self.assertIn("docker tag gozargah/marzban:latest linkray:latest", script)
        self.assertIn("docker rmi gozargah/marzban:latest", script)
        self.assertIn("docker rm -f marzban-marzban-1", script)
        self.assertIn("docker compose up -d --force-recreate --remove-orphans linkray", script)

    def test_deploy_rendered_node_script_supports_advanced_runtime_files(self):
        script = Path("scripts/deploy-rendered-node.sh").read_text()

        self.assertIn("opt/linkray-node-app/current/main.py", script)
        self.assertIn("etc/systemd/system/linkray-node.service", script)
        self.assertIn("etc/systemd/system/linkray-xray.service", script)
        self.assertIn("python3 -m venv /opt/linkray-node-app/venv", script)
        self.assertIn("pip install -r /opt/linkray-node-app/current/requirements.txt", script)
        self.assertIn("systemctl enable linkray-xray", script)
        self.assertIn("systemctl enable --now linkray-node", script)
        self.assertIn("docker update --restart=no linkray-node", script)
        self.assertNotIn("get.docker.com", script)
        self.assertNotIn("systemctl enable --now docker", script)
        self.assertNotIn("docker compose up", script)
        self.assertNotIn("docker compose up -d --force-recreate --remove-orphans linkray-node", script)
        self.assertIn("etc/systemd/system/linkray-singbox-runtime.service", script)
        self.assertIn("etc/systemd/system/linkray-snell-runtime.service", script)
        self.assertIn("etc/systemd/system/linkray-snell@.service", script)
        self.assertIn("etc/systemd/system/linkray-snell-usage.service", script)
        self.assertIn("var/lib/marzban/linkray/singbox/config.json", script)
        self.assertIn("var/lib/marzban/linkray/singbox/users.json", script)
        self.assertIn("var/lib/marzban/linkray/snell/snell-server.conf", script)
        self.assertIn("etc/sysctl.d/99-linkray-network.conf", script)
        self.assertIn("etc/modules-load.d/linkray-bbr.conf", script)
        self.assertIn("modprobe tcp_bbr", script)
        self.assertIn("tc qdisc replace dev", script)
        self.assertIn("systemctl enable --now linkray-singbox-runtime", script)
        self.assertIn("systemctl enable --now linkray-snell-runtime", script)
        self.assertIn("systemctl enable --now linkray-snell-usage", script)

    def test_deployment_doc_master_service_commands_are_complete(self):
        doc = Path("docs/DEPLOYMENT.md").read_text()

        self.assertIn("Only the `master` role installs Docker", doc)
        self.assertIn("`linkray bootstrap node` must not install Docker", doc)
        self.assertIn("must not start a container", doc)
        self.assertIn("BBR/fq network acceleration", doc)
        self.assertIn("/etc/sysctl.d/99-linkray-network.conf", doc)
        self.assertIn("tc qdisc replace dev <default-iface> root fq", doc)

        for service in [
            "linkray-api",
            "linkray-clash",
            "linkray-egern",
            "linkray-shadowrocket",
            "linkray-singbox",
            "linkray-singbox-runtime",
            "linkray-snell-runtime",
            "linkray-snell-usage",
            "linkray-sub-auto",
            "linkray-relay",
        ]:
            self.assertIn(f"systemctl enable --now {service}", doc)
            self.assertIn(f"systemctl restart {service}", doc)
        self.assertIn("systemctl enable --now linkray-rules-update.timer", doc)
        self.assertIn("etc/systemd/system/linkray-clash.service", doc)
        self.assertIn("etc/systemd/system/linkray-snell-usage.service", doc)


if __name__ == "__main__":
    unittest.main()
