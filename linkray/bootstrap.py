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


DEFAULT_NODE_REMOTE_CERT_PATH = "/var/lib/marzban/ssl_client_cert.pem"
NODE_CERT_PATH = Path("var/lib/marzban-node/ssl_client_cert.pem")


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


def dependency_commands(include_docker: bool = True) -> list[str]:
    commands = [
        "apt-get update",
        "DEBIAN_FRONTEND=noninteractive apt-get install -y curl ca-certificates gnupg nginx sqlite3 socat cron unzip openssh-client git build-essential tar nftables python3 python3-venv python3-pip",
    ]
    if include_docker:
        commands.extend(
            [
                "command -v docker >/dev/null 2>&1 || curl -fsSL https://get.docker.com | sh",
                "systemctl enable --now docker",
            ]
        )
    commands.append("systemctl enable --now nginx")
    return commands


def node_app_commands() -> list[str]:
    return [
        "test -f /opt/linkray-node-app/current/requirements.txt",
        "python3 -m venv /opt/linkray-node-app/venv",
        "/opt/linkray-node-app/venv/bin/python -m pip install --upgrade pip",
        "/opt/linkray-node-app/venv/bin/python -m pip install -r /opt/linkray-node-app/current/requirements.txt",
    ]


def node_docker_cleanup_commands() -> list[str]:
    return [
        "if command -v docker >/dev/null 2>&1; then docker update --restart=no linkray-node 2>/dev/null || true; fi",
        "if command -v docker >/dev/null 2>&1; then docker stop linkray-node 2>/dev/null || true; fi",
        "if command -v docker >/dev/null 2>&1; then docker rm -f marzban-node-marzban-node-1 2>/dev/null || true; fi",
    ]


def master_image_alias_commands() -> list[str]:
    return [
        (
            "if ! docker image inspect linkray:latest >/dev/null 2>&1; then "
            "docker image inspect gozargah/marzban:latest >/dev/null 2>&1 || docker pull gozargah/marzban:latest; "
            "docker tag gozargah/marzban:latest linkray:latest; "
            "docker rmi gozargah/marzban:latest >/dev/null 2>&1 || true; "
            "fi"
        ),
    ]


def xray_binary_commands(version: str = "v25.3.6") -> list[str]:
    binary = "/var/lib/marzban/linkray/bin/xray"
    geoip = "/var/lib/marzban/linkray/bin/geoip.dat"
    geosite = "/var/lib/marzban/linkray/bin/geosite.dat"
    archive = f"https://github.com/XTLS/Xray-core/releases/download/{version}/Xray-linux-64.zip"
    return [
        "mkdir -p /var/lib/marzban/linkray/bin",
        (
            f"if ! test -x {binary} -a -s {geoip} -a -s {geosite}; then "
            f"tmp=$(mktemp -d) && "
            f"curl -fL {shell_quote(archive)} -o \"$tmp/xray.zip\" && "
            f"unzip -p \"$tmp/xray.zip\" xray > {binary} && "
            f"unzip -p \"$tmp/xray.zip\" geoip.dat > {geoip} && "
            f"unzip -p \"$tmp/xray.zip\" geosite.dat > {geosite} && "
            f"chmod 755 {binary} && "
            f"chmod 644 {geoip} {geosite} && "
            f"rm -rf \"$tmp\"; "
            "fi"
        ),
        f"{binary} version | head -1",
    ]


def go_toolchain_install_command(version: str = "1.23.12") -> str:
    archive = f"https://go.dev/dl/go{version}.linux-amd64.tar.gz"
    return (
        f"if ! (test -x /usr/local/go/bin/go && /usr/local/go/bin/go version | grep -q 'go{version}'); then "
        f"go_tmp=$(mktemp -d) && "
        f"curl -fL {shell_quote(archive)} -o \"$go_tmp/go.tar.gz\" && "
        f"rm -rf /usr/local/go && "
        f"tar -C /usr/local -xzf \"$go_tmp/go.tar.gz\" && "
        f"rm -rf \"$go_tmp\"; "
        "fi"
    )


def go_toolchain_commands(version: str = "1.23.12") -> list[str]:
    return [
        go_toolchain_install_command(version),
        "/usr/local/go/bin/go version",
    ]


def singbox_binary_commands(version: str = "v1.12.0") -> list[str]:
    binary = "/usr/local/bin/sing-box"
    marker = f"/usr/local/share/linkray/sing-box-with-v2ray-api-quic-utls-clash-api-{version}"
    prebuilt_url = (
        f"https://github.com/Zanetach/LinkRay/releases/download/sing-box-{version}/"
        f"sing-box-{version}-linux-${{linkray_arch}}.tar.gz"
    )
    return [
        (
            f"if ! test -f {marker} -a -x {binary}; then "
            "arch=$(uname -m) && "
            "case \"$arch\" in x86_64|amd64) linkray_arch=amd64 ;; aarch64|arm64) linkray_arch=aarch64 ;; *) echo unsupported arch \"$arch\"; exit 1 ;; esac && "
            f"tmp=$(mktemp -d) && "
            f"mkdir -p /usr/local/share/linkray && "
            f"prebuilt_url=\"${{LINKRAY_SING_BOX_URL:-{prebuilt_url}}}\" && "
            "if curl -fsL \"$prebuilt_url\" -o \"$tmp/sing-box.tar.gz\" && "
            "tar -xzf \"$tmp/sing-box.tar.gz\" -C \"$tmp\" && "
            "prebuilt_bin=$(find \"$tmp\" -type f -name sing-box | head -1) && "
            "test -n \"$prebuilt_bin\" && "
            "\"$prebuilt_bin\" version | grep -q with_v2ray_api; then "
            f"install -m 0755 \"$prebuilt_bin\" {binary}; "
            "else "
            f"{go_toolchain_install_command()} && "
            f"GOBIN=\"$tmp/bin\" /usr/local/go/bin/go install -trimpath -tags 'with_v2ray_api with_quic with_utls with_clash_api' "
            f"github.com/sagernet/sing-box/cmd/sing-box@{version} && "
            f"install -m 0755 \"$tmp/bin/sing-box\" {binary}; "
            "fi && "
            f"{binary} version | grep -q with_v2ray_api && "
            f"touch {marker} && "
            f"rm -rf \"$tmp\"; "
            "fi"
        ),
        f"{binary} version | head -1",
    ]


def snell_binary_commands(version: str = "v5.0.1") -> list[str]:
    binary = "/usr/local/bin/snell-server"
    marker = f"/usr/local/share/linkray/snell-server-{version}"
    return [
        (
            f"if ! test -f {marker} -a -x {binary}; then "
            "arch=$(uname -m) && "
            "case \"$arch\" in x86_64|amd64) snell_arch=amd64 ;; aarch64|arm64) snell_arch=aarch64 ;; *) echo unsupported arch \"$arch\"; exit 1 ;; esac && "
            "tmp=$(mktemp -d) && "
            "mkdir -p /usr/local/share/linkray && "
            f"curl -fL https://dl.nssurge.com/snell/snell-server-{version}-linux-${{snell_arch}}.zip -o \"$tmp/snell-server.zip\" && "
            f"unzip -p \"$tmp/snell-server.zip\" snell-server > {binary} && "
            f"chmod 755 {binary} && "
            f"touch {marker} && "
            "rm -rf \"$tmp\"; "
            "fi"
        ),
        f"{binary} -version 2>&1 | head -1",
    ]


def node_flags(nodes: list[NodeHost]) -> str:
    return " ".join(f"--node {shell_quote(f'{node.name}={node.domain}')}" for node in nodes)


def linkray_api_commands(xray_runtime_mode: str = "marzban") -> list[str]:
    commands = [
        "rm -f /etc/cron.d/linkray-port-status",
        "rm -f /var/lib/marzban/linkray/public/ports.html /var/lib/marzban/linkray/public/ports.json",
        "systemctl daemon-reload",
        "systemctl enable --now linkray-api",
        "systemctl enable --now linkray-clash",
        "systemctl enable --now linkray-egern",
        "systemctl enable --now linkray-shadowrocket",
        "systemctl enable --now linkray-singbox",
        "systemctl enable --now linkray-singbox-runtime",
        "systemctl enable --now linkray-snell-runtime",
        "systemctl enable --now linkray-snell-usage",
        "systemctl enable --now linkray-sub-auto",
        "systemctl enable --now linkray-rules-update.timer",
        "systemctl start linkray-rules-update.service || true",
        "systemctl enable --now linkray-relay",
        "systemctl restart linkray-api",
        "systemctl restart linkray-clash",
        "systemctl restart linkray-egern",
        "systemctl restart linkray-shadowrocket",
        "systemctl restart linkray-singbox",
        "systemctl restart linkray-singbox-runtime",
        "systemctl restart linkray-snell-runtime",
        "systemctl restart linkray-snell-usage",
        "systemctl restart linkray-sub-auto",
        "systemctl restart linkray-relay",
    ]
    if xray_runtime_mode == "linkray":
        commands.insert(3, "systemctl enable --now linkray-xray")
        commands.append("systemctl restart linkray-xray")
    return commands


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
    return [
        *master_preinstall_runtime_commands(issue_cert, config, cf_token_env),
        *master_postinstall_runtime_commands(config),
    ]


def master_preinstall_runtime_commands(
    issue_cert: bool,
    config: LinkRayConfig,
    cf_token_env: str,
) -> list[str]:
    commands = dependency_commands()
    if issue_cert:
        commands.extend(cert_commands(config, cf_token_env))
    commands.extend(xray_binary_commands())
    commands.extend(singbox_binary_commands())
    commands.extend(snell_binary_commands())
    return commands


def master_postinstall_runtime_commands(config: LinkRayConfig) -> list[str]:
    commands = [
        *master_image_alias_commands(),
        "docker rm -f marzban-marzban-1 2>/dev/null || true",
        "cd /opt/marzban && docker compose up -d --force-recreate --remove-orphans linkray",
        "sqlite3 /var/lib/marzban/db.sqlite3 < /var/lib/marzban/linkray/hosts.sql",
        "nginx -t",
        "systemctl reload nginx",
    ]
    commands.extend(linkray_api_commands(config.xray_runtime_mode))
    commands.append(
        "tmp=$(mktemp) && "
        "for i in $(seq 1 30); do "
        "if linkray doctor --role master >\"$tmp\" 2>&1; then cat \"$tmp\"; rm -f \"$tmp\"; exit 0; fi; "
        "sleep 2; "
        "done; "
        "cat \"$tmp\"; rm -f \"$tmp\"; exit 1"
    )
    return commands


def pull_node_cert_commands(pull_cert_from: str, remote_cert_path: str, local_cert_path: Path) -> list[str]:
    source = f"{pull_cert_from}:{remote_cert_path}"
    return [
        f"mkdir -p {shell_quote(str(local_cert_path.parent))}",
        f"scp -q -o StrictHostKeyChecking=accept-new {shell_quote(source)} {shell_quote(str(local_cert_path))}",
        f"chmod 600 {shell_quote(str(local_cert_path))}",
    ]


def node_runtime_commands(
    pull_cert_from: str | None = None,
    remote_cert_path: str = DEFAULT_NODE_REMOTE_CERT_PATH,
    local_cert_path: Path = Path("/") / NODE_CERT_PATH,
    advanced_runtime: bool = False,
) -> list[str]:
    commands = dependency_commands(include_docker=False)
    if pull_cert_from:
        commands.extend(pull_node_cert_commands(pull_cert_from, remote_cert_path, local_cert_path))
    commands.extend(xray_binary_commands())
    commands.extend(node_app_commands())
    if advanced_runtime:
        commands.extend(singbox_binary_commands())
        commands.extend(snell_binary_commands())
    commands.extend(
        [
            *node_docker_cleanup_commands(),
            "systemctl daemon-reload",
            "systemctl enable linkray-xray",
            "systemctl enable --now linkray-node",
            "systemctl restart linkray-node",
        ]
    )
    if advanced_runtime:
        commands.extend(
            [
                "systemctl enable --now linkray-singbox-runtime",
                "systemctl enable --now linkray-snell-runtime",
                "systemctl enable --now linkray-snell-usage",
                "systemctl restart linkray-singbox-runtime",
                "systemctl restart linkray-snell-runtime",
                "systemctl restart linkray-snell-usage",
            ]
        )
    commands.append("linkray doctor --role node")
    return commands


def install_actions_to_bootstrap(actions) -> list[BootstrapAction]:
    return [BootstrapAction("file", action.describe()) for action in actions]


def placeholder_admin_password(config: LinkRayConfig) -> bool:
    return config.admin_password.startswith("REPLACE_")


def generated_reality_private_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")


def generated_short_id() -> str:
    return secrets.token_hex(8)


def generated_snell_psk() -> str:
    return secrets.token_urlsafe(32)


def config_with_generated_secrets(config: LinkRayConfig) -> LinkRayConfig:
    updates: dict[str, str] = {}
    if config.reality_private_key.startswith("REPLACE_"):
        updates["reality_private_key"] = generated_reality_private_key()
    if config.reality_short_id.startswith("REPLACE_"):
        updates["reality_short_id"] = generated_short_id()
    if config.snell_psk.startswith("REPLACE_"):
        updates["snell_psk"] = generated_snell_psk()
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

    if effective_runtime and apply:
        shell_runner = runner or SubprocessShellRunner()
        for command in master_preinstall_runtime_commands(issue_cert, effective_config, cf_token_env):
            action = command_action(command, apply, shell_runner)
            actions.append(action)
            if not action.ok:
                return actions

    actions.extend(install_actions_to_bootstrap(install_master(effective_config, root=root, apply=apply, nodes=nodes)))
    if effective_runtime:
        shell_runner = runner or SubprocessShellRunner()
        if apply:
            commands = master_postinstall_runtime_commands(effective_config)
        else:
            commands = master_runtime_commands(issue_cert, effective_config, cf_token_env, nodes=nodes)
        for command in commands:
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
    pull_cert_from: str | None = None,
    remote_cert_path: str = DEFAULT_NODE_REMOTE_CERT_PATH,
    config: LinkRayConfig | None = None,
) -> list[BootstrapAction]:
    effective_runtime = root == Path("/") if runtime is None else runtime
    cert_path = root / NODE_CERT_PATH
    if apply and not cert_path.exists() and not pull_cert_from:
        return [
            BootstrapAction(
                "precheck",
                f"Marzban node certificate is required at {cert_path}",
                ok=False,
            )
        ]
    effective_config = config_with_generated_secrets(config) if apply and config else config
    actions = install_actions_to_bootstrap(install_node(root=root, apply=apply, config=effective_config))
    if effective_runtime:
        shell_runner = runner or SubprocessShellRunner()
        for command in node_runtime_commands(
            pull_cert_from,
            remote_cert_path,
            cert_path,
            advanced_runtime=effective_config is not None,
        ):
            action = command_action(command, apply, shell_runner)
            actions.append(action)
            if apply and not action.ok:
                break
    return actions
