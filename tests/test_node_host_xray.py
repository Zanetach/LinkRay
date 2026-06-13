import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class NodeHostXrayTests(unittest.TestCase):
    def load_xray_module(self, *, node_domain: str):
        config = types.ModuleType("config")
        config.DEBUG = False
        config.INBOUNDS = []
        config.LINKRAY_NODE_DOMAIN = node_domain
        config.SSL_CERT_FILE = "/var/lib/marzban-node/ssl_cert.pem"
        config.SSL_KEY_FILE = "/var/lib/marzban-node/ssl_key.pem"
        config.XRAY_API_HOST = "0.0.0.0"
        config.XRAY_API_PORT = 62051
        config.XRAY_TLS_CERT_FILE = "/var/lib/marzban/certs/linkray/fullchain.cer"
        config.XRAY_TLS_KEY_FILE = "/var/lib/marzban/certs/linkray/linkray.key"

        logger = types.ModuleType("logger")
        logger.logger = types.SimpleNamespace(
            debug=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
            warning=lambda *args, **kwargs: None,
        )

        module_path = Path(__file__).resolve().parents[1] / "linkray/assets/marzban-node-host/xray.py"
        module_name = f"node_host_xray_{abs(hash(node_domain))}"
        old_config = sys.modules.get("config")
        old_logger = sys.modules.get("logger")
        sys.modules["config"] = config
        sys.modules["logger"] = logger
        try:
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module)
            return module
        finally:
            if old_config is None:
                sys.modules.pop("config", None)
            else:
                sys.modules["config"] = old_config
            if old_logger is None:
                sys.modules.pop("logger", None)
            else:
                sys.modules["logger"] = old_logger

    def test_node_host_rewrites_master_tls_to_node_certificate(self):
        module = self.load_xray_module(node_domain="edge-b.example.com")
        config = {
            "inbounds": [
                {
                    "tag": "VLESS GRPC TLS",
                    "protocol": "vless",
                    "streamSettings": {
                        "network": "grpc",
                        "security": "tls",
                        "tlsSettings": {
                            "serverName": "edge-a.example.com",
                            "certificates": [{"certificate": ["inline"], "key": ["inline"]}],
                        },
                    },
                    "settings": {"clients": []},
                }
            ],
            "routing": {"rules": []},
        }

        rewritten = module.XRayConfig(json.dumps(config), "192.0.2.10")
        inbound = next(item for item in rewritten["inbounds"] if item["tag"] == "VLESS GRPC TLS")
        tls = inbound["streamSettings"]["tlsSettings"]

        self.assertEqual(tls["serverName"], "edge-b.example.com")
        self.assertEqual(
            tls["certificates"],
            [
                {
                    "certificateFile": "/var/lib/marzban/certs/linkray/fullchain.cer",
                    "keyFile": "/var/lib/marzban/certs/linkray/linkray.key",
                }
            ],
        )

    def test_node_host_keeps_master_tls_when_node_domain_is_unset(self):
        module = self.load_xray_module(node_domain="")
        config = {
            "inbounds": [
                {
                    "tag": "VLESS TCP TLS",
                    "protocol": "vless",
                    "streamSettings": {
                        "security": "tls",
                        "tlsSettings": {"serverName": "edge-a.example.com"},
                    },
                }
            ],
            "routing": {"rules": []},
        }

        rewritten = module.XRayConfig(json.dumps(config), "192.0.2.10")
        inbound = next(item for item in rewritten["inbounds"] if item["tag"] == "VLESS TCP TLS")

        self.assertEqual(inbound["streamSettings"]["tlsSettings"]["serverName"], "edge-a.example.com")

    def test_external_restart_skips_systemd_when_config_is_unchanged(self):
        module = self.load_xray_module(node_domain="edge-b.example.com")
        config = module.XRayConfig(json.dumps({"inbounds": [], "routing": {"rules": []}}), "192.0.2.10")

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(module.subprocess, "check_output", return_value=b"Xray 25.3.6\n"):
                core = module.XRayCore()
            core.external = True
            core.runtime_config = str(Path(tmpdir) / "runtime.json")
            Path(core.runtime_config).write_text(core._external_config_text(config), encoding="utf-8")
            core._external_active = lambda: True
            actions = []
            core._external_systemctl = actions.append

            core.restart(config)

            self.assertEqual(actions, [])

    def test_external_restart_restarts_systemd_when_config_changes(self):
        module = self.load_xray_module(node_domain="edge-b.example.com")
        config = module.XRayConfig(json.dumps({"inbounds": [], "routing": {"rules": []}}), "192.0.2.10")

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(module.subprocess, "check_output", return_value=b"Xray 25.3.6\n"):
                core = module.XRayCore()
            core.external = True
            core.runtime_config = str(Path(tmpdir) / "runtime.json")
            Path(core.runtime_config).write_text('{"old": true}\n', encoding="utf-8")
            core._external_active = lambda: True
            actions = []
            core._external_systemctl = actions.append

            core.restart(config)

            self.assertEqual(actions, ["restart"])
            self.assertEqual(Path(core.runtime_config).read_text(encoding="utf-8"), core._external_config_text(config))

    def test_external_start_is_idempotent_when_service_is_already_active(self):
        module = self.load_xray_module(node_domain="edge-b.example.com")
        config = module.XRayConfig(json.dumps({"inbounds": [], "routing": {"rules": []}}), "192.0.2.10")

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(module.subprocess, "check_output", return_value=b"Xray 25.3.6\n"):
                core = module.XRayCore()
            core.external = True
            core.runtime_config = str(Path(tmpdir) / "runtime.json")
            Path(core.runtime_config).write_text(core._external_config_text(config), encoding="utf-8")
            core._external_active = lambda: True
            actions = []
            core._external_systemctl = actions.append

            core.start(config)

            self.assertEqual(actions, [])

    def test_external_stop_keeps_systemd_service_running_by_default(self):
        module = self.load_xray_module(node_domain="edge-b.example.com")

        with patch.object(module.subprocess, "check_output", return_value=b"Xray 25.3.6\n"):
            core = module.XRayCore()
        core.external = True
        core.external_stop_allowed = False
        core._external_active = lambda: True
        actions = []
        core._external_systemctl = actions.append

        core.stop()

        self.assertEqual(actions, [])


if __name__ == "__main__":
    unittest.main()
