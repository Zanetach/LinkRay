from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ADVANCED_PROTOCOL_KEYS = ("hysteria2", "tuic", "anytls", "snell")
SINGBOX_PROTOCOL_KEYS = ("hysteria2", "tuic", "anytls")
DEFAULT_PROTOCOL_PREFS_PATH = Path("/var/lib/marzban/linkray/protocols/users.json")


@dataclass(frozen=True)
class ProtocolPreferences:
    users: dict[str, set[str]]


def normalize_protocols(values: Iterable[object]) -> set[str]:
    allowed = set(ADVANCED_PROTOCOL_KEYS)
    return {str(value).strip().lower() for value in values if str(value).strip().lower() in allowed}


def enabled_protocols_for_user(prefs: ProtocolPreferences | None, username: str) -> set[str]:
    if prefs is None or username not in prefs.users:
        return set(ADVANCED_PROTOCOL_KEYS)
    return normalize_protocols(prefs.users[username])


def load_protocol_preferences(path: Path = DEFAULT_PROTOCOL_PREFS_PATH) -> ProtocolPreferences:
    if not path.exists():
        return ProtocolPreferences(users={})
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_users = data.get("users", {})
    users: dict[str, set[str]] = {}
    if isinstance(raw_users, dict):
        for username, protocols in raw_users.items():
            if isinstance(username, str) and isinstance(protocols, list):
                users[username] = normalize_protocols(protocols)
    return ProtocolPreferences(users=users)


def save_protocol_preferences(path: Path, prefs: ProtocolPreferences) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "users": {username: sorted(normalize_protocols(protocols)) for username, protocols in sorted(prefs.users.items())},
    }
    fd, tmp_name = tempfile.mkstemp(prefix=".users.", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
        path.chmod(0o600)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def set_user_protocols(path: Path, username: str, protocols: Iterable[object]) -> ProtocolPreferences:
    clean_username = username.strip()
    if not clean_username:
        raise ValueError("username is required")
    prefs = load_protocol_preferences(path)
    users = dict(prefs.users)
    users[clean_username] = normalize_protocols(protocols)
    updated = ProtocolPreferences(users=users)
    save_protocol_preferences(path, updated)
    return updated
