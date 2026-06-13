from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import subprocess
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import LinkRayConfig, SINGBOX_DEFAULT_PORTS


SINGBOX_STATS_PORT = 61996
DEFAULT_RUNTIME_DIR = Path("/var/lib/marzban/linkray/singbox")


@dataclass(frozen=True)
class SingBoxUser:
    name: str
    token_hash: str
    uuid: str
    hysteria2_password: str
    tuic_password: str
    anytls_password: str


def b64url(raw: bytes, length: int = 32) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")[:length]


def digest(secret: str, token: str, label: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), f"{label}:{token}".encode("utf-8"), hashlib.sha256).digest()


def credential_for_token(token: str, secret: str, name: str | None = None) -> SingBoxUser:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    uuid_bytes = digest(secret, token, "uuid")[:16]
    return SingBoxUser(
        name=name or f"lr-{token_hash[:12]}",
        token_hash=token_hash,
        uuid=str(uuid.UUID(bytes=uuid_bytes)),
        hysteria2_password=b64url(digest(secret, token, "hysteria2")),
        tuic_password=b64url(digest(secret, token, "tuic")),
        anytls_password=b64url(digest(secret, token, "anytls")),
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


def load_users(runtime_dir: Path) -> list[SingBoxUser]:
    path = runtime_dir / "users.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [SingBoxUser(**item) for item in data.get("users", [])]


def save_users(runtime_dir: Path, users: list[SingBoxUser]) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    data = {"version": 1, "users": [asdict(user) for user in users]}
    (runtime_dir / "users.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def tls_server_config(config: LinkRayConfig) -> dict[str, Any]:
    return {
        "enabled": True,
        "certificate_path": config.cert_file,
        "key_path": config.key_file,
    }


def tls_client_config(config: LinkRayConfig, *, utls: bool = True) -> dict[str, Any]:
    tls: dict[str, Any] = {
        "enabled": True,
        "server_name": config.domain,
    }
    if utls:
        tls["utls"] = {"enabled": True, "fingerprint": "chrome"}
    return tls


def server_config(config: LinkRayConfig, users: list[SingBoxUser]) -> dict[str, Any]:
    ports = config.singbox_port_map()
    return {
        "log": {"level": "warning"},
        "inbounds": [
            {
                "type": "hysteria2",
                "tag": "Hysteria2",
                "listen": "0.0.0.0",
                "listen_port": ports["hysteria2"],
                "up_mbps": 1000,
                "down_mbps": 1000,
                "users": [{"name": user.name, "password": user.hysteria2_password} for user in users],
                "tls": tls_server_config(config),
            },
            {
                "type": "tuic",
                "tag": "TUIC",
                "listen": "0.0.0.0",
                "listen_port": ports["tuic"],
                "users": [{"name": user.name, "uuid": user.uuid, "password": user.tuic_password} for user in users],
                "congestion_control": "bbr",
                "tls": tls_server_config(config),
            },
            {
                "type": "anytls",
                "tag": "AnyTLS",
                "listen": "0.0.0.0",
                "listen_port": ports["anytls"],
                "users": [{"name": user.name, "password": user.anytls_password} for user in users],
                "tls": tls_server_config(config),
            },
        ],
        "outbounds": [
            {"type": "direct", "tag": "direct"},
            {"type": "block", "tag": "block"},
        ],
        "route": {"final": "direct"},
        "experimental": {
            "v2ray_api": {
                "listen": f"127.0.0.1:{SINGBOX_STATS_PORT}",
                "stats": {
                    "enabled": True,
                    "inbounds": ["Hysteria2", "TUIC", "AnyTLS"],
                    "users": [user.name for user in users],
                },
            }
        },
    }


def singbox_user_outbounds(config: LinkRayConfig, user: SingBoxUser) -> list[dict[str, Any]]:
    ports = config.singbox_port_map()
    return [
        {
            "type": "hysteria2",
            "tag": "Hysteria2",
            "server": config.domain,
            "server_port": ports["hysteria2"],
            "password": user.hysteria2_password,
            "tls": tls_client_config(config, utls=False),
        },
        {
            "type": "tuic",
            "tag": "TUIC",
            "server": config.domain,
            "server_port": ports["tuic"],
            "uuid": user.uuid,
            "password": user.tuic_password,
            "congestion_control": "bbr",
            "udp_relay_mode": "native",
            "tls": tls_client_config(config, utls=False),
        },
        {
            "type": "anytls",
            "tag": "AnyTLS",
            "server": config.domain,
            "server_port": ports["anytls"],
            "password": user.anytls_password,
            "tls": tls_client_config(config),
        },
    ]


def write_server_config(runtime_dir: Path, config: LinkRayConfig, users: list[SingBoxUser]) -> bool:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    path = runtime_dir / "config.json"
    content = json.dumps(server_config(config, users), ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def ensure_runtime_user(
    token: str,
    config: LinkRayConfig,
    runtime_dir: Path = DEFAULT_RUNTIME_DIR,
    secret: str | None = None,
    reload_command: str | None = None,
    name: str | None = None,
) -> tuple[SingBoxUser, bool]:
    effective_secret = secret or read_secret(runtime_dir)
    user = credential_for_token(token, effective_secret, name=name)
    users = load_users(runtime_dir)
    by_hash = {item.token_hash: item for item in users}
    changed = by_hash.get(user.token_hash) != user
    by_hash[user.token_hash] = user
    ordered = sorted(by_hash.values(), key=lambda item: item.name)
    if changed:
        save_users(runtime_dir, ordered)
    config_changed = write_server_config(runtime_dir, config, ordered)
    should_reload = changed or config_changed
    if should_reload and reload_command:
        subprocess.run(reload_command, shell=True, check=False)
    return user, should_reload


def reconcile_runtime_users(
    active_usernames: set[str],
    config: LinkRayConfig,
    runtime_dir: Path = DEFAULT_RUNTIME_DIR,
    reload_command: str | None = None,
) -> bool:
    users = load_users(runtime_dir)
    kept = [user for user in users if user.name in active_usernames]
    changed = kept != users
    if changed:
        save_users(runtime_dir, kept)
    config_changed = write_server_config(runtime_dir, config, kept)
    should_reload = changed or config_changed
    if should_reload and reload_command:
        subprocess.run(reload_command, shell=True, check=False)
    return should_reload
