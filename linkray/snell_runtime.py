from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from .config import SNELL_DEFAULT_PORTS, LinkRayConfig


DEFAULT_RUNTIME_DIR = Path("/var/lib/marzban/linkray/snell")
USAGE_SNAPSHOT_FILE = "usage-snapshot.json"
USER_PORT_BASE = 40000
USER_PORT_COUNT = 10000
USER_STORE_LOCK = threading.RLock()


@dataclass(frozen=True)
class SnellUser:
    name: str
    token_hash: str
    instance: str
    psk: str
    port: int


def b64url(raw: bytes, length: int = 32) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")[:length]


def digest(secret: str, token: str, label: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), f"{label}:{token}".encode("utf-8"), hashlib.sha256).digest()


def preferred_user_port(token_hash: str, used_ports: set[int] | None = None) -> int:
    used = used_ports or set()
    start = int(token_hash[:8], 16) % USER_PORT_COUNT
    for offset in range(USER_PORT_COUNT):
        port = USER_PORT_BASE + ((start + offset) % USER_PORT_COUNT)
        if port not in used:
            return port
    raise ValueError("no Snell user ports available")


def credential_for_token(
    token: str,
    secret: str,
    name: str | None = None,
    port: int | None = None,
    used_ports: set[int] | None = None,
) -> SnellUser:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    user_port = port if port is not None else preferred_user_port(token_hash, used_ports)
    return SnellUser(
        name=name or f"lr-{token_hash[:12]}",
        token_hash=token_hash,
        instance=f"lr-{token_hash[:12]}",
        psk=b64url(digest(secret, token, "snell"), length=43),
        port=user_port,
    )


def read_secret(runtime_dir: Path) -> str:
    path = runtime_dir / "secret"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    secret = b64url(os.urandom(32), length=43)
    path.write_text(secret + "\n", encoding="utf-8")
    path.chmod(0o600)
    return secret


def load_users(runtime_dir: Path) -> list[SnellUser]:
    path = runtime_dir / "users.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [SnellUser(**item) for item in data.get("users", [])]


def write_text_atomic(path: Path, content: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        if mode is not None:
            os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def save_users(runtime_dir: Path, users: list[SnellUser]) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    data = {"version": 1, "users": [asdict(user) for user in users]}
    write_text_atomic(runtime_dir / "users.json", json.dumps(data, ensure_ascii=False, indent=2) + "\n", mode=0o600)


def server_config_text(config: LinkRayConfig) -> str:
    ports = config.snell_port_map()
    return user_server_config_text(config.snell_psk, ports["snell"])


def user_server_config_text(psk: str, port: int) -> str:
    return "\n".join(
        [
            "[snell-server]",
            f"listen = ::0:{port}",
            f"psk = {psk}",
            "ipv6 = true",
            "",
        ]
    )


def write_server_config(runtime_dir: Path, config: LinkRayConfig) -> bool:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    path = runtime_dir / "snell-server.conf"
    content = server_config_text(config)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    write_text_atomic(path, content, mode=0o600)
    return True


def write_user_config(runtime_dir: Path, user: SnellUser) -> bool:
    users_dir = runtime_dir / "users"
    users_dir.mkdir(parents=True, exist_ok=True)
    path = users_dir / f"{user.instance}.conf"
    content = user_server_config_text(user.psk, user.port)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    write_text_atomic(path, content, mode=0o600)
    return True


def run_reload_command(reload_command: str, user: SnellUser) -> None:
    command = reload_command.format(instance=user.instance, name=user.name, port=user.port)
    subprocess.run(command, shell=True, check=False)


def ensure_runtime_user(
    token: str,
    config: LinkRayConfig,
    runtime_dir: Path = DEFAULT_RUNTIME_DIR,
    secret: str | None = None,
    reload_command: str | None = None,
    name: str | None = None,
) -> tuple[SnellUser, bool]:
    with USER_STORE_LOCK:
        effective_secret = secret or read_secret(runtime_dir)
        users = load_users(runtime_dir)
        by_hash = {item.token_hash: item for item in users}
        existing = by_hash.get(hashlib.sha256(token.encode("utf-8")).hexdigest())
        used_ports = {item.port for item in users if existing is None or item.token_hash != existing.token_hash}
        user = credential_for_token(
            token,
            effective_secret,
            name=name,
            port=existing.port if existing else None,
            used_ports=used_ports,
        )
        changed = existing != user
        by_hash[user.token_hash] = user
        ordered = sorted(by_hash.values(), key=lambda item: item.name)
        if changed:
            save_users(runtime_dir, ordered)
        config_changed = write_user_config(runtime_dir, user)
        should_reload = changed or config_changed
    if should_reload and reload_command:
        run_reload_command(reload_command, user)
    return user, should_reload


def snell_display_name(user: SnellUser) -> str:
    return f"{user.name}-Snell"


def snell_shadowrocket_line(config: LinkRayConfig, user: SnellUser) -> str:
    return ",".join(
        [
            f"{snell_display_name(user)} = snell",
            config.domain,
            str(user.port),
            f"psk={user.psk}",
            "version=5",
            "reuse=true",
            "udp-relay=true",
        ]
    )


def snell_clash_proxy(config: LinkRayConfig, user: SnellUser) -> dict[str, object]:
    return {
        "name": snell_display_name(user),
        "type": "snell",
        "server": config.domain,
        "port": user.port,
        "psk": user.psk,
        "version": 5,
        "udp": True,
        "reuse": True,
    }


def _int_value(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _payload_field(match: dict[str, object]) -> str | None:
    left = match.get("left")
    if not isinstance(left, dict):
        return None
    payload = left.get("payload")
    if not isinstance(payload, dict):
        return None
    field = payload.get("field")
    return field if isinstance(field, str) else None


def parse_nft_port_bytes(data: dict[str, object]) -> dict[int, int]:
    ports: dict[int, int] = {}
    nftables = data.get("nftables")
    if not isinstance(nftables, list):
        return ports

    for item in nftables:
        if not isinstance(item, dict):
            continue
        rule = item.get("rule")
        if not isinstance(rule, dict):
            continue
        expr = rule.get("expr")
        if not isinstance(expr, list):
            continue

        port: int | None = None
        byte_count = 0
        for expression in expr:
            if not isinstance(expression, dict):
                continue
            match = expression.get("match")
            if isinstance(match, dict) and _payload_field(match) in {"sport", "dport"}:
                port = _int_value(match.get("right"))
            counter = expression.get("counter")
            if isinstance(counter, dict):
                byte_count += _int_value(counter.get("bytes")) or 0

        if port is not None and byte_count:
            ports[port] = ports.get(port, 0) + byte_count
    return ports


def read_usage_snapshot(runtime_dir: Path) -> dict[int, int]:
    path = runtime_dir / USAGE_SNAPSHOT_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    ports = data.get("ports")
    if not isinstance(ports, dict):
        return {}
    parsed: dict[int, int] = {}
    for port, value in ports.items():
        parsed_port = _int_value(port)
        parsed_value = _int_value(value)
        if parsed_port is not None and parsed_value is not None:
            parsed[parsed_port] = parsed_value
    return parsed


def write_usage_snapshot(runtime_dir: Path, port_bytes: dict[int, int]) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "updated_at": int(time.time()),
        "ports": {str(port): int(value) for port, value in sorted(port_bytes.items())},
    }
    write_text_atomic(runtime_dir / USAGE_SNAPSHOT_FILE, json.dumps(data, indent=2, sort_keys=True) + "\n", mode=0o600)


def snell_usage_deltas(runtime_dir: Path, current_port_bytes: dict[int, int]) -> dict[str, int]:
    users = load_users(runtime_dir)
    previous = read_usage_snapshot(runtime_dir)
    tracked_ports = {user.port for user in users}
    snapshot = {port: int(current_port_bytes.get(port, 0)) for port in tracked_ports}
    deltas: dict[str, int] = {}
    for user in users:
        current = snapshot.get(user.port, 0)
        old = previous.get(user.port, 0)
        delta = current - old
        if delta > 0:
            deltas[user.name] = deltas.get(user.name, 0) + delta
    write_usage_snapshot(runtime_dir, snapshot)
    return deltas


def nft_ruleset_port_bytes(check_output: Callable[[list[str]], bytes] | None = None) -> dict[int, int]:
    runner = check_output or subprocess.check_output
    raw = runner(["nft", "-j", "list", "ruleset"])
    text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    return parse_nft_port_bytes(json.loads(text))


def _rule_comment(port: int, direction: str) -> str:
    return f"linkray-snell:{port}:{direction}"


def _nft_comments(data: dict[str, object]) -> set[str]:
    comments: set[str] = set()
    nftables = data.get("nftables")
    if not isinstance(nftables, list):
        return comments
    for item in nftables:
        if not isinstance(item, dict):
            continue
        rule = item.get("rule")
        if not isinstance(rule, dict):
            continue
        comment = rule.get("comment")
        if isinstance(comment, str):
            comments.add(comment)
        expr = rule.get("expr")
        if isinstance(expr, list):
            for expression in expr:
                if isinstance(expression, dict) and isinstance(expression.get("comment"), str):
                    comments.add(expression["comment"])
    return comments


def ensure_accounting_rules(
    runtime_dir: Path,
    check_output: Callable[[list[str]], bytes] | None = None,
    run_command: Callable[[str], object] | None = None,
) -> None:
    users = load_users(runtime_dir)
    if not users:
        return

    runner = check_output or subprocess.check_output
    try:
        raw = runner(["nft", "-j", "list", "ruleset"])
        data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        data = {"nftables": []}
    comments = _nft_comments(data)
    command_runner = run_command or (lambda command: subprocess.run(command, shell=True, check=False))

    command_runner("nft add table inet linkray_snell 2>/dev/null || true")
    command_runner(
        "nft 'add chain inet linkray_snell input { type filter hook input priority 0; policy accept; }' "
        "2>/dev/null || true"
    )
    command_runner(
        "nft 'add chain inet linkray_snell output { type filter hook output priority 0; policy accept; }' "
        "2>/dev/null || true"
    )
    for user in users:
        inbound_comment = _rule_comment(user.port, "in")
        outbound_comment = _rule_comment(user.port, "out")
        if inbound_comment not in comments:
            command_runner(
                f"nft add rule inet linkray_snell input tcp dport {user.port} counter comment "
                f"'{inbound_comment}' 2>/dev/null || true"
            )
        if outbound_comment not in comments:
            command_runner(
                f"nft add rule inet linkray_snell output tcp sport {user.port} counter comment "
                f"'{outbound_comment}' 2>/dev/null || true"
            )


def collect_snell_usage(
    runtime_dir: Path = DEFAULT_RUNTIME_DIR,
    check_output: Callable[[list[str]], bytes] | None = None,
    run_command: Callable[[str], object] | None = None,
) -> dict[str, int]:
    ensure_accounting_rules(runtime_dir, check_output=check_output, run_command=run_command)
    try:
        current = nft_ruleset_port_bytes(check_output=check_output)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        current = {}
    return snell_usage_deltas(runtime_dir, current)


class SnellUsageHandler(BaseHTTPRequestHandler):
    runtime_dir: Path
    lock: threading.Lock

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_json(self, status: int, data: dict[str, object]) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json(200, {"status": "ok"})
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/usage/collect":
            self.send_json(404, {"error": "not found"})
            return
        with self.lock:
            usage = collect_snell_usage(self.runtime_dir)
        self.send_json(200, {"usage": usage, "total": sum(usage.values())})


def make_snell_usage_server(listen: str, port: int, runtime_dir: Path = DEFAULT_RUNTIME_DIR) -> ThreadingHTTPServer:
    class Handler(SnellUsageHandler):
        pass

    Handler.runtime_dir = runtime_dir
    Handler.lock = threading.Lock()
    return ThreadingHTTPServer((listen, port), Handler)


def serve_snell_usage(args) -> int:
    server = make_snell_usage_server(args.listen, args.port, args.runtime_dir)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0
