import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from linkray.cli import build_parser
from linkray.shadowrocket import serve_shadowrocket
from linkray.singbox import serve_singbox


class FakeServer:
    def __init__(self) -> None:
        self.closed = False

    def serve_forever(self) -> None:
        raise KeyboardInterrupt

    def server_close(self) -> None:
        self.closed = True


class CLITests(unittest.TestCase):
    def test_subscription_sidecars_accept_protocol_preferences_path(self):
        parser = build_parser()

        shadowrocket = parser.parse_args(
            [
                "shadowrocket",
                "--protocol-preferences-path",
                "/tmp/linkray-protocols.json",
            ]
        )
        singbox = parser.parse_args(
            [
                "sing-box",
                "--protocol-preferences-path",
                "/tmp/linkray-protocols.json",
            ]
        )

        self.assertEqual(shadowrocket.protocol_preferences_path, Path("/tmp/linkray-protocols.json"))
        self.assertEqual(singbox.protocol_preferences_path, Path("/tmp/linkray-protocols.json"))

    def test_shadowrocket_serve_passes_protocol_preferences_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "protocols.json"
            fake = FakeServer()
            args = Namespace(
                listen="127.0.0.1",
                port=0,
                marzban_url="http://127.0.0.1:8000",
                server_domain="edge-a.example.com",
                snell_runtime_dir=Path(tmp) / "snell",
                snell_reload_command="",
                protocol_preferences_path=path,
            )

            with patch("linkray.shadowrocket.make_shadowrocket_server", return_value=fake) as make_server:
                self.assertEqual(serve_shadowrocket(args), 130)

            self.assertTrue(fake.closed)
            self.assertEqual(make_server.call_args.kwargs["protocol_preferences_path"], path)

    def test_singbox_serve_passes_protocol_preferences_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "protocols.json"
            fake = FakeServer()
            args = Namespace(
                listen="127.0.0.1",
                port=0,
                marzban_url="http://127.0.0.1:8000",
                server_domain="edge-a.example.com",
                advanced_domain=None,
                runtime_dir=Path(tmp) / "singbox",
                reload_command="",
                sync_command="",
                singbox_inbound=None,
                protocol_preferences_path=path,
                rules_base_url="",
            )

            with patch("linkray.singbox.make_singbox_server", return_value=fake) as make_server:
                self.assertEqual(serve_singbox(args), 130)

            self.assertTrue(fake.closed)
            self.assertEqual(make_server.call_args.kwargs["protocol_preferences_path"], path)


if __name__ == "__main__":
    unittest.main()
