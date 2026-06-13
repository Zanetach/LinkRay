import tempfile
import unittest
from pathlib import Path

from linkray.config import DEFAULT_PORTS, LINKRAY_XRAY_API_PORT, LinkRayConfig, parse_inbound_ports
from linkray.doctor import CommandResult, docker_has_container, exit_code, has_listening_port, run_doctor
from linkray.install import install_master, install_node
from linkray.snell_runtime import SNELL_DEFAULT_PORTS
from linkray.singbox_runtime import SINGBOX_DEFAULT_PORTS, SINGBOX_STATS_PORT


class FakeRunner:
    def __init__(self, responses):
        self.responses = responses

    def run(self, command):
        key = tuple(command)
        return self.responses.get(key, CommandResult(1, "", "missing fake response"))


class DoctorTests(unittest.TestCase):
    def test_has_listening_port(self):
        output = "tcp LISTEN 0 4096 *:18080 *:* users:((\"xray\",pid=1,fd=3))"
        self.assertTrue(has_listening_port(output, 18080))
        self.assertFalse(has_listening_port(output, 18081))

    def test_docker_has_container(self):
        output = "linkray|Up 1 hour\nother|Up 1 hour\n"
        self.assertTrue(docker_has_container(output, "linkray"))
        self.assertFalse(docker_has_container(output, "linkray-node"))

    def test_file_doctor_master_against_rendered_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_master(LinkRayConfig(domain="edge-a.example.com"), root=root, apply=True)
            checks = run_doctor("master", root=root, runtime=False)
            self.assertEqual(exit_code(checks), 0)
            manifest_checks = [check for check in checks if check.name == "manifest"]
            self.assertEqual(len(manifest_checks), 1)
            self.assertIn("role=master", manifest_checks[0].detail)
            self.assertIn("domain=edge-a.example.com", manifest_checks[0].detail)

    def test_file_doctor_node_against_rendered_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_node(root=root, apply=True)
            checks = run_doctor("node", root=root, runtime=False)
            self.assertEqual(exit_code(checks), 0)

    def test_runtime_doctor_node_with_advanced_runtime(self):
        ss_ports = "\n".join(
            f'tcp LISTEN 0 4096 *:{port} *:* users:(("linkray",pid=1,fd=3))'
            for port in [
                62050,
                62051,
                61997,
                SINGBOX_STATS_PORT,
                *SINGBOX_DEFAULT_PORTS.values(),
                *SNELL_DEFAULT_PORTS.values(),
                *DEFAULT_PORTS.values(),
            ]
        )
        runner = FakeRunner(
            {
                ("ss", "-lntup"): CommandResult(0, ss_ports),
                ("ps", "-eo", "pid,ppid,cmd"): CommandResult(
                    0,
                    "1 0 /var/lib/marzban/linkray/bin/xray run -config /var/lib/marzban/linkray/xray/runtime.json\n",
                ),
                ("systemctl", "is-active", "nginx"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "xray"): CommandResult(3, "inactive\n"),
                ("systemctl", "is-active", "linkray-node"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-xray"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-singbox-runtime"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-snell-runtime"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-snell-usage"): CommandResult(0, "active\n"),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_node(root=root, apply=True, config=LinkRayConfig(domain="edge-b.example.com"))
            checks = run_doctor("node", root=root, runtime=True, runner=runner)

        check_names = {check.name for check in checks}
        self.assertIn("systemd linkray-node", check_names)
        self.assertIn("systemd linkray-xray", check_names)
        self.assertIn("systemd linkray-singbox-runtime", check_names)
        self.assertIn("systemd linkray-snell-runtime", check_names)
        self.assertIn("systemd linkray-snell-usage", check_names)
        self.assertIn("port 443", check_names)
        self.assertIn("port 19180", check_names)
        self.assertEqual(exit_code(checks), 0)

    def test_runtime_doctor_master_detects_healthy_runtime(self):
        ss_ports = "\n".join(
            f'tcp LISTEN 0 4096 *:{port} *:* users:(("xray",pid=1,fd=3))'
            for port in [
                8000, 9443, 61990, 61991, 61992, 61993, 61994, 61995, 61997,
                SINGBOX_STATS_PORT,
                *SINGBOX_DEFAULT_PORTS.values(),
                *SNELL_DEFAULT_PORTS.values(),
                LINKRAY_XRAY_API_PORT,
                *DEFAULT_PORTS.values(),
            ]
        )
        runner = FakeRunner(
            {
                ("ss", "-lntup"): CommandResult(0, ss_ports),
                ("ps", "-eo", "pid,ppid,cmd"): CommandResult(0, "1 0 /usr/local/bin/xray run -config stdin:\n"),
                ("systemctl", "is-active", "nginx"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "xray"): CommandResult(3, "inactive\n"),
                ("systemctl", "is-active", "linkray-api"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-clash"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-egern"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-shadowrocket"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-singbox"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-singbox-runtime"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-snell-runtime"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-snell-usage"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-sub-auto"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-rules-update.timer"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-relay"): CommandResult(0, "active\n"),
                ("docker", "ps", "--format", "{{.Names}}|{{.Status}}"): CommandResult(0, "linkray|Up 1 hour\n"),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_master(LinkRayConfig(domain="edge-a.example.com"), root=root, apply=True)
            checks = run_doctor("master", root=root, runtime=True, runner=runner)
        check_names = {check.name for check in checks}
        self.assertIn("systemd linkray-snell-usage", check_names)
        self.assertIn("port 61997", check_names)
        self.assertEqual(exit_code(checks), 0)

    def test_runtime_doctor_master_uses_rendered_custom_xray_ports(self):
        custom_ports = parse_inbound_ports(["vless_tls=28080", "trojan_grpc_tls=28091"])
        expected_ports = {**DEFAULT_PORTS, **dict(custom_ports)}
        ss_ports = "\n".join(
            f'tcp LISTEN 0 4096 *:{port} *:* users:(("xray",pid=1,fd=3))'
            for port in [
                8000, 9443, 61990, 61991, 61992, 61993, 61994, 61995, 61997,
                SINGBOX_STATS_PORT,
                *SINGBOX_DEFAULT_PORTS.values(),
                *SNELL_DEFAULT_PORTS.values(),
                *expected_ports.values(),
            ]
        )
        runner = FakeRunner(
            {
                ("ss", "-lntup"): CommandResult(0, ss_ports),
                ("ps", "-eo", "pid,ppid,cmd"): CommandResult(0, "1 0 /usr/local/bin/xray run -config stdin:\n"),
                ("systemctl", "is-active", "nginx"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "xray"): CommandResult(3, "inactive\n"),
                ("systemctl", "is-active", "linkray-api"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-clash"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-egern"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-shadowrocket"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-singbox"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-singbox-runtime"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-snell-runtime"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-snell-usage"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-sub-auto"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-rules-update.timer"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-relay"): CommandResult(0, "active\n"),
                ("docker", "ps", "--format", "{{.Names}}|{{.Status}}"): CommandResult(0, "linkray|Up 1 hour\n"),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_master(LinkRayConfig(domain="edge-a.example.com", inbound_ports=custom_ports), root=root, apply=True)
            checks = run_doctor("master", root=root, runtime=True, runner=runner)
        self.assertEqual(exit_code(checks), 0)

    def test_runtime_doctor_master_accepts_linkray_managed_xray(self):
        ss_ports = "\n".join(
            f'tcp LISTEN 0 4096 *:{port} *:* users:(("xray",pid=1,fd=3))'
            for port in [
                8000, 9443, 61990, 61991, 61992, 61993, 61994, 61995, 61997,
                SINGBOX_STATS_PORT,
                *SINGBOX_DEFAULT_PORTS.values(),
                *SNELL_DEFAULT_PORTS.values(),
                LINKRAY_XRAY_API_PORT,
                *DEFAULT_PORTS.values(),
            ]
        )
        runner = FakeRunner(
            {
                ("ss", "-lntup"): CommandResult(0, ss_ports),
                ("ps", "-eo", "pid,ppid,cmd"): CommandResult(
                    0,
                    "1 0 /var/lib/marzban/linkray/bin/xray run -config /var/lib/marzban/linkray/xray/runtime.json\n",
                ),
                ("systemctl", "is-active", "nginx"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "xray"): CommandResult(3, "inactive\n"),
                ("systemctl", "is-active", "linkray-xray"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-api"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-clash"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-egern"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-shadowrocket"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-singbox"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-singbox-runtime"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-snell-runtime"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-snell-usage"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-sub-auto"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-rules-update.timer"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-relay"): CommandResult(0, "active\n"),
                ("docker", "ps", "--format", "{{.Names}}|{{.Status}}"): CommandResult(0, "linkray|Up 1 hour\n"),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_master(
                LinkRayConfig(domain="edge-a.example.com", xray_runtime_mode="linkray"),
                root=root,
                apply=True,
            )
            checks = run_doctor("master", root=root, runtime=True, runner=runner)
        self.assertEqual(exit_code(checks), 0)

if __name__ == "__main__":
    unittest.main()
