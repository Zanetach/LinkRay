import tempfile
import unittest
from pathlib import Path

from linkray.config import DEFAULT_PORTS, LinkRayConfig, parse_inbound_ports
from linkray.doctor import CommandResult, docker_has_container, exit_code, has_listening_port, run_doctor
from linkray.install import install_master, install_node


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
        output = "marzban-marzban-1|Up 1 hour\nother|Up 1 hour\n"
        self.assertTrue(docker_has_container(output, "marzban-marzban-1"))
        self.assertFalse(docker_has_container(output, "marzban-node-marzban-node-1"))

    def test_file_doctor_master_against_rendered_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_master(LinkRayConfig(domain="edge-a.example.com"), root=root, apply=True)
            checks = run_doctor("master", root=root, runtime=False)
            self.assertEqual(exit_code(checks), 0)

    def test_file_doctor_node_against_rendered_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_node(root=root, apply=True)
            checks = run_doctor("node", root=root, runtime=False)
            self.assertEqual(exit_code(checks), 0)

    def test_runtime_doctor_master_detects_healthy_runtime(self):
        ss_ports = "\n".join(
            f'tcp LISTEN 0 4096 *:{port} *:* users:(("xray",pid=1,fd=3))'
            for port in [8000, 9443, 61990, *DEFAULT_PORTS.values()]
        )
        runner = FakeRunner(
            {
                ("ss", "-lntup"): CommandResult(0, ss_ports),
                ("ps", "-eo", "pid,ppid,cmd"): CommandResult(0, "1 0 /usr/local/bin/xray run -config stdin:\n"),
                ("systemctl", "is-active", "nginx"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "xray"): CommandResult(3, "inactive\n"),
                ("systemctl", "is-active", "linkray-api"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-egern"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-sub-auto"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-rules-update.timer"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-relay"): CommandResult(0, "active\n"),
                ("docker", "ps", "--format", "{{.Names}}|{{.Status}}"): CommandResult(0, "marzban-marzban-1|Up 1 hour\n"),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_master(LinkRayConfig(domain="edge-a.example.com"), root=root, apply=True)
            checks = run_doctor("master", root=root, runtime=True, runner=runner)
        self.assertEqual(exit_code(checks), 0)

    def test_runtime_doctor_master_uses_rendered_custom_xray_ports(self):
        custom_ports = parse_inbound_ports(["vless_tls=32080", "trojan_grpc_tls=32091"])
        expected_ports = {**DEFAULT_PORTS, **dict(custom_ports)}
        ss_ports = "\n".join(
            f'tcp LISTEN 0 4096 *:{port} *:* users:(("xray",pid=1,fd=3))'
            for port in [8000, 9443, 61990, *expected_ports.values()]
        )
        runner = FakeRunner(
            {
                ("ss", "-lntup"): CommandResult(0, ss_ports),
                ("ps", "-eo", "pid,ppid,cmd"): CommandResult(0, "1 0 /usr/local/bin/xray run -config stdin:\n"),
                ("systemctl", "is-active", "nginx"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "xray"): CommandResult(3, "inactive\n"),
                ("systemctl", "is-active", "linkray-api"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-egern"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-sub-auto"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-rules-update.timer"): CommandResult(0, "active\n"),
                ("systemctl", "is-active", "linkray-relay"): CommandResult(0, "active\n"),
                ("docker", "ps", "--format", "{{.Names}}|{{.Status}}"): CommandResult(0, "marzban-marzban-1|Up 1 hour\n"),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_master(LinkRayConfig(domain="edge-a.example.com", inbound_ports=custom_ports), root=root, apply=True)
            checks = run_doctor("master", root=root, runtime=True, runner=runner)
        self.assertEqual(exit_code(checks), 0)

if __name__ == "__main__":
    unittest.main()
