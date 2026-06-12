from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .config import DEFAULT_PORTS, LINKRAY_XRAY_API_PORT
from .snell_runtime import SNELL_DEFAULT_PORTS
from .singbox_runtime import SINGBOX_DEFAULT_PORTS, SINGBOX_STATS_PORT


@dataclass(frozen=True)
class CommandResult:
    code: int
    stdout: str
    stderr: str = ""


class Runner(Protocol):
    def run(self, command: list[str]) -> CommandResult:
        ...


class SubprocessRunner:
    def run(self, command: list[str]) -> CommandResult:
        completed = subprocess.run(command, text=True, capture_output=True)
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


@dataclass(frozen=True)
class Check:
    status: str
    name: str
    detail: str

    def line(self) -> str:
        return f"{self.status}: {self.name} - {self.detail}"


def has_listening_port(ss_output: str, port: int) -> bool:
    return re.search(rf":{port}(?:\s|$)", ss_output) is not None


def has_process(ps_output: str, pattern: str) -> bool:
    return pattern in ps_output


def docker_has_container(output: str, name: str) -> bool:
    for line in output.splitlines():
        parts = line.split("|", 1)
        if parts and parts[0] == name:
            return True
    return False


def check_file(root: Path, relative: str, missing_status: str = "FAIL") -> Check:
    path = root / relative
    if path.exists():
        return Check("PASS", f"file {relative}", "exists")
    return Check(missing_status, f"file {relative}", "missing")


def manifest_check(role: str, root: Path) -> Check:
    if role != "master":
        return Check("PASS", "manifest", "not required for node role")
    path = root / "var/lib/marzban/linkray/linkray-manifest.json"
    if not path.exists():
        return Check("FAIL", "manifest", "missing")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return Check("FAIL", "manifest", f"invalid: {exc}")
    actual_role = data.get("role")
    domain = data.get("config", {}).get("domain") if isinstance(data.get("config"), dict) else None
    commit = data.get("commit") or "unknown"
    if actual_role != role:
        return Check("FAIL", "manifest", f"expected role={role}, got role={actual_role}")
    return Check("PASS", "manifest", f"role={actual_role} domain={domain or 'unknown'} commit={commit}")


def service_check(name: str, expected: str, runner: Runner) -> Check:
    result = runner.run(["systemctl", "is-active", name])
    actual = result.stdout.strip() or result.stderr.strip() or f"exit={result.code}"
    if actual == expected:
        return Check("PASS", f"systemd {name}", actual)
    return Check("FAIL", f"systemd {name}", f"expected {expected}, got {actual}")


def docker_check(container: str, runner: Runner) -> Check:
    result = runner.run(["docker", "ps", "--format", "{{.Names}}|{{.Status}}"])
    if result.code != 0:
        return Check("FAIL", "docker ps", result.stderr.strip() or "command failed")
    if docker_has_container(result.stdout, container):
        return Check("PASS", f"container {container}", "running")
    return Check("FAIL", f"container {container}", "not running")


def rendered_xray_ports(root: Path) -> list[int]:
    path = root / "var/lib/marzban/xray_config.json"
    if not path.exists():
        return list(DEFAULT_PORTS.values())
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return list(DEFAULT_PORTS.values())
    ports = []
    for inbound in data.get("inbounds", []):
        port = inbound.get("port") if isinstance(inbound, dict) else None
        if isinstance(port, int):
            ports.append(port)
    return ports or list(DEFAULT_PORTS.values())


def rendered_xray_runtime_mode(root: Path) -> str:
    path = root / "var/lib/marzban/linkray/linkray-manifest.json"
    if not path.exists():
        return "marzban"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "marzban"
    config = data.get("config")
    if not isinstance(config, dict):
        return "marzban"
    mode = config.get("xray_runtime_mode")
    return mode if mode in {"marzban", "linkray"} else "marzban"


def rendered_snell_ports(root: Path) -> list[int]:
    path = root / "var/lib/marzban/linkray/snell/snell-server.conf"
    if not path.exists():
        return list(SNELL_DEFAULT_PORTS.values())
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return list(SNELL_DEFAULT_PORTS.values())
    match = re.search(r"^\s*listen\s*=\s*(?:\S+:)?(?P<port>\d+)\s*$", text, flags=re.MULTILINE)
    if not match:
        return list(SNELL_DEFAULT_PORTS.values())
    return [int(match.group("port"))]


def runtime_checks(role: str, runner: Runner, root: Path = Path("/")) -> list[Check]:
    checks: list[Check] = []
    ss_result = runner.run(["ss", "-lntup"])
    ss_output = ss_result.stdout
    ps_result = runner.run(["ps", "-eo", "pid,ppid,cmd"])
    ps_output = ps_result.stdout
    xray_runtime_mode = rendered_xray_runtime_mode(root)

    checks.append(service_check("nginx", "active", runner))
    checks.append(service_check("xray", "inactive", runner))
    if role == "master":
        if xray_runtime_mode == "linkray":
            checks.append(service_check("linkray-xray", "active", runner))
        checks.append(service_check("linkray-api", "active", runner))
        checks.append(service_check("linkray-clash", "active", runner))
        checks.append(service_check("linkray-egern", "active", runner))
        checks.append(service_check("linkray-shadowrocket", "active", runner))
        checks.append(service_check("linkray-singbox", "active", runner))
        checks.append(service_check("linkray-singbox-runtime", "active", runner))
        checks.append(service_check("linkray-snell-runtime", "active", runner))
        checks.append(service_check("linkray-snell-usage", "active", runner))
        checks.append(service_check("linkray-sub-auto", "active", runner))
        checks.append(service_check("linkray-rules-update.timer", "active", runner))
        checks.append(service_check("linkray-relay", "active", runner))
    if role == "master" and xray_runtime_mode == "linkray":
        pattern = "/var/lib/marzban/linkray/bin/xray run -config /var/lib/marzban/linkray/xray/runtime.json"
        checks.append(
            Check(
                "PASS" if has_process(ps_output, pattern) else "FAIL",
                "LinkRay-managed Xray",
                "running" if has_process(ps_output, pattern) else "not found",
            )
        )
    else:
        checks.append(
            Check(
                "PASS" if has_process(ps_output, "/usr/local/bin/xray run -config stdin:") else "FAIL",
                "Marzban-managed Xray",
                "running" if has_process(ps_output, "/usr/local/bin/xray run -config stdin:") else "not found",
            )
        )
    expected_ports = rendered_xray_ports(root)
    if role == "master":
        expected_ports = [
            8000,
            9443,
            61990,
            61991,
            61992,
            61993,
            61994,
            61995,
            61997,
            SINGBOX_STATS_PORT,
            *SINGBOX_DEFAULT_PORTS.values(),
            *rendered_snell_ports(root),
            *expected_ports,
        ]
        if xray_runtime_mode == "linkray":
            expected_ports.append(LINKRAY_XRAY_API_PORT)
        checks.append(docker_check("linkray", runner))
    else:
        expected_ports = [62050, 62051, *expected_ports]
        checks.append(docker_check("linkray-node", runner))

    for port in expected_ports:
        listening = has_listening_port(ss_output, port)
        checks.append(Check("PASS" if listening else "FAIL", f"port {port}", "listening" if listening else "not listening"))

    return checks


def file_checks(role: str, root: Path) -> list[Check]:
    if role == "master":
        required = [
            "opt/marzban/docker-compose.yml",
            "opt/marzban/.env",
            "var/lib/marzban/xray_config.json",
            "var/lib/marzban/templates/clash/default.yml",
            "etc/nginx/conf.d/marzban-panel.conf",
            "etc/systemd/system/linkray-api.service",
            "etc/systemd/system/linkray-egern.service",
            "etc/systemd/system/linkray-shadowrocket.service",
            "etc/systemd/system/linkray-singbox.service",
            "etc/systemd/system/linkray-singbox-runtime.service",
            "etc/systemd/system/linkray-snell-runtime.service",
            "etc/systemd/system/linkray-snell@.service",
            "etc/systemd/system/linkray-snell-usage.service",
            "etc/systemd/system/linkray-sub-auto.service",
            "etc/systemd/system/linkray-rules-update.service",
            "etc/systemd/system/linkray-rules-update.timer",
            "etc/systemd/system/linkray-relay.service",
            "var/lib/marzban/linkray/rules/cn-domains.txt",
            "var/lib/marzban/linkray/rules/cn-ip-cidrs.txt",
            "var/lib/marzban/linkray/singbox/config.json",
            "var/lib/marzban/linkray/singbox/users.json",
            "var/lib/marzban/linkray/xray/runtime.json",
            "var/lib/marzban/linkray/snell/snell-server.conf",
            "var/lib/marzban/linkray/patches/0_xray_core.py",
            "var/lib/marzban/linkray/patches/xray_init.py",
            "var/lib/marzban/linkray/jobs/linkray_singbox_usages.py",
        ]
        if rendered_xray_runtime_mode(root) == "linkray":
            required.append("etc/systemd/system/linkray-xray.service")
        recommended = ["var/lib/marzban/linkray/hosts.sql"]
    else:
        required = ["opt/marzban-node/docker-compose.yml"]
        recommended = []
    checks = [check_file(root, item) for item in required]
    checks.extend(check_file(root, item, missing_status="WARN") for item in recommended)
    if role == "master":
        checks.append(manifest_check(role, root))
    return checks


def run_doctor(
    role: str,
    root: Path = Path("/"),
    runtime: bool = True,
    runner: Runner | None = None,
) -> list[Check]:
    checks = file_checks(role, root)
    if runtime:
        checks.extend(runtime_checks(role, runner or SubprocessRunner(), root=root))
    return checks


def exit_code(checks: list[Check]) -> int:
    return 1 if any(check.status == "FAIL" for check in checks) else 0
