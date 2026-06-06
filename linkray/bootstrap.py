from __future__ import annotations

import shlex
import subprocess
import base64
import os
import secrets
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from .config import LinkRayConfig, NodeHost
from .install import install_master, install_node
from .render import default_nodes


@dataclass(frozen=True)
class BootstrapAction:
    kind: str
    detail: str
    ok: bool = True

    def describe(self) -> str:
        status = "OK" if self.ok else "FAIL"
        return f"{status}: {self.kind} - {self.detail}"


class ShellRunner(Protocol):
    def run(self, command: str) -> BootstrapAction:
        ...


class SubprocessShellRunner:
    def run(self, command: str) -> BootstrapAction:
        completed = subprocess.run(command, shell=True, text=True, capture_output=True)
        output = completed.stdout.strip() or completed.stderr.strip() or f"exit={completed.returncode}"
        return BootstrapAction("command", f"{command}: {output}", ok=completed.returncode == 0)


class RecordingRunner:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def run(self, command: str) -> BootstrapAction:
        self.commands.append(command)
        return BootstrapAction("command", command)


def shell_quote(value: str) -> str:
    return shlex.quote(value)


def command_action(command: str, apply: bool, runner: ShellRunner) -> BootstrapAction:
    if not apply:
        return BootstrapAction("command", command)
    return runner.run(command)


def dependency_commands() -> list[str]:
    return [
        "apt-get update",
        "DEBIAN_FRONTEND=noninteractive apt-get install -y curl ca-certificates gnupg nginx sqlite3 socat cron unzip",
        "command -v docker >/dev/null 2>&1 || curl -fsSL https://get.docker.com | sh",
        "systemctl enable --now docker",
        "systemctl enable --now nginx",
    ]


def xray_binary_commands(version: str = "v25.3.6") -> list[str]:
    binary = "/var/lib/marzban/linkray/bin/xray"
    archive = f"https://github.com/XTLS/Xray-core/releases/download/{version}/Xray-linux-64.zip"
    return [
        "mkdir -p /var/lib/marzban/linkray/bin",
        (
            f"test -x {binary} || "
            f"tmp=$(mktemp -d) && "
            f"curl -fL {shell_quote(archive)} -o \"$tmp/xray.zip\" && "
            f"unzip -p \"$tmp/xray.zip\" xray > {binary} && "
            f"chmod 755 {binary} && "
            f"rm -rf \"$tmp\""
        ),
        f"{binary} version | head -1",
    ]


def node_flags(nodes: list[NodeHost]) -> str:
    return " ".join(f"--node {shell_quote(f'{node.name}={node.domain}')}" for node in nodes)


def linkray_api_commands() -> list[str]:
    return [
        "rm -f /etc/cron.d/linkray-port-status",
        "rm -f /var/lib/marzban/linkray/public/ports.html /var/lib/marzban/linkray/public/ports.json",
        "systemctl daemon-reload",
        "systemctl enable --now linkray-api",
        "systemctl enable --now linkray-egern",
        "systemctl enable --now linkray-shadowrocket",
        "systemctl enable --now linkray-singbox",
        "systemctl enable --now linkray-sub-auto",
        "systemctl enable --now linkray-rules-update.timer",
        "systemctl start linkray-rules-update.service || true",
        "systemctl enable --now linkray-relay",
        "systemctl restart linkray-api",
        "systemctl restart linkray-egern",
        "systemctl restart linkray-shadowrocket",
        "systemctl restart linkray-singbox",
        "systemctl restart linkray-sub-auto",
        "systemctl restart linkray-relay",
    ]


def cert_commands(config: LinkRayConfig, cf_token_env: str) -> list[str]:
    token = f'"${{{cf_token_env}:?missing Cloudflare token env {cf_token_env}}}"'
    domain = shell_quote(config.domain)
    cert_file = shell_quote(config.cert_file)
    key_file = shell_quote(config.key_file)
    cert_dir = shell_quote(str(Path(config.cert_file).parent))
    email = shell_quote(f"admin@{config.domain}")
    return [
        f"test -x /root/.acme.sh/acme.sh || curl https://get.acme.sh | sh -s email={email}",
        f"mkdir -p {cert_dir}",
        (
            f"test -s {cert_file} -a -s {key_file} || "
            f"CF_Token={token} /root/.acme.sh/acme.sh --issue --dns dns_cf "
            f"-d {domain} --server letsencrypt --keylength ec-256"
        ),
        (
            f"CF_Token={token} /root/.acme.sh/acme.sh --install-cert -d {domain} --ecc "
            f"--fullchain-file {cert_file} --key-file {key_file} "
            f"--reloadcmd 'systemctl reload nginx || true'"
        ),
    ]


def master_runtime_commands(
    issue_cert: bool,
    config: LinkRayConfig,
    cf_token_env: str,
    nodes: list[NodeHost] | None = None,
) -> list[str]:
    commands = dependency_commands()
    if issue_cert:
        commands.extend(cert_commands(config, cf_token_env))
    commands.extend(xray_binary_commands())
    commands.extend(
        [
            "cd /opt/marzban && docker compose up -d --force-recreate marzban",
            "sqlite3 /var/lib/marzban/db.sqlite3 < /var/lib/marzban/linkray/hosts.sql",
            "nginx -t",
            "systemctl reload nginx",
        ]
    )
    commands.extend(linkray_api_commands())
    commands.append("linkray doctor --role master")
    return commands


def node_runtime_commands() -> list[str]:
    return [
        *dependency_commands(),
        "cd /opt/marzban-node && docker compose up -d",
        "linkray doctor --role node",
    ]


def install_actions_to_bootstrap(actions) -> list[BootstrapAction]:
    return [BootstrapAction("file", action.describe()) for action in actions]


def placeholder_admin_password(config: LinkRayConfig) -> bool:
    return config.admin_password.startswith("REPLACE_")


def generated_reality_private_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")


def generated_short_id() -> str:
    return secrets.token_hex(8)


def config_with_generated_secrets(config: LinkRayConfig) -> LinkRayConfig:
    updates: dict[str, str] = {}
    if config.reality_private_key.startswith("REPLACE_"):
        updates["reality_private_key"] = generated_reality_private_key()
    if config.reality_short_id.startswith("REPLACE_"):
        updates["reality_short_id"] = generated_short_id()
    if not updates:
        return config
    return replace(config, **updates)


def bootstrap_master(
    config: LinkRayConfig,
    root: Path = Path("/"),
    apply: bool = False,
    nodes: list[NodeHost] | None = None,
    runtime: bool | None = None,
    runner: ShellRunner | None = None,
    issue_cert: bool = False,
    cf_token_env: str = "CF_Token",
) -> list[BootstrapAction]:
    effective_runtime = root == Path("/") if runtime is None else runtime
    actions: list[BootstrapAction] = []

    if apply and placeholder_admin_password(config):
        return [
            BootstrapAction(
                "precheck",
                "admin password is required for directly usable bootstrap; pass --admin-password",
                ok=False,
            )
        ]

    effective_config = config_with_generated_secrets(config) if apply else config
    actions.extend(install_actions_to_bootstrap(install_master(effective_config, root=root, apply=apply, nodes=nodes)))
    if effective_runtime:
        shell_runner = runner or SubprocessShellRunner()
        for command in master_runtime_commands(issue_cert, config, cf_token_env, nodes=nodes):
            action = command_action(command, apply, shell_runner)
            actions.append(action)
            if apply and not action.ok:
                break
    return actions


def bootstrap_node(
    root: Path = Path("/"),
    apply: bool = False,
    runtime: bool | None = None,
    runner: ShellRunner | None = None,
) -> list[BootstrapAction]:
    effective_runtime = root == Path("/") if runtime is None else runtime
    cert_path = root / "var/lib/marzban-node/ssl_client_cert.pem"
    if apply and not cert_path.exists():
        return [
            BootstrapAction(
                "precheck",
                f"Marzban node certificate is required at {cert_path}",
                ok=False,
            )
        ]
    actions = install_actions_to_bootstrap(install_node(root=root, apply=apply))
    if effective_runtime:
        shell_runner = runner or SubprocessShellRunner()
        for command in node_runtime_commands():
            action = command_action(command, apply, shell_runner)
            actions.append(action)
            if apply and not action.ok:
                break
    return actions
