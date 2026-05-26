from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .config import DEFAULT_PORTS


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


def runtime_checks(role: str, runner: Runner) -> list[Check]:
    checks: list[Check] = []
    ss_result = runner.run(["ss", "-lntup"])
    ss_output = ss_result.stdout
    ps_result = runner.run(["ps", "-eo", "pid,ppid,cmd"])
    ps_output = ps_result.stdout

    checks.append(service_check("nginx", "active", runner))
    checks.append(service_check("xray", "inactive", runner))
    if role == "master":
        checks.append(service_check("linkray-api", "active", runner))
        checks.append(service_check("linkray-egern", "active", runner))
        checks.append(service_check("linkray-sub-auto", "active", runner))
        checks.append(service_check("linkray-relay", "active", runner))
    checks.append(
        Check(
            "PASS" if has_process(ps_output, "/usr/local/bin/xray run -config stdin:") else "FAIL",
            "Marzban-managed Xray",
            "running" if has_process(ps_output, "/usr/local/bin/xray run -config stdin:") else "not found",
        )
    )
    expected_ports = list(DEFAULT_PORTS.values())
    if role == "master":
        expected_ports = [8000, 9443, 61990, *expected_ports]
        checks.append(docker_check("marzban-marzban-1", runner))
    else:
        expected_ports = [62050, 62051, *expected_ports]
        checks.append(docker_check("marzban-node-marzban-node-1", runner))

    for port in expected_ports:
        checks.append(
            Check(
                "PASS" if has_listening_port(ss_output, port) else "FAIL",
                f"port {port}",
                "listening" if has_listening_port(ss_output, port) else "not listening",
            )
        )

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
            "etc/systemd/system/linkray-sub-auto.service",
            "etc/systemd/system/linkray-relay.service",
        ]
        recommended = ["var/lib/marzban/linkray/hosts.sql"]
    else:
        required = ["opt/marzban-node/docker-compose.yml"]
        recommended = []
    checks = [check_file(root, item) for item in required]
    checks.extend(check_file(root, item, missing_status="WARN") for item in recommended)
    return checks


def run_doctor(
    role: str,
    root: Path = Path("/"),
    runtime: bool = True,
    runner: Runner | None = None,
) -> list[Check]:
    checks = file_checks(role, root)
    if runtime:
        checks.extend(runtime_checks(role, runner or SubprocessRunner()))
    return checks


def exit_code(checks: list[Check]) -> int:
    return 1 if any(check.status == "FAIL" for check in checks) else 0
