from __future__ import annotations

import filecmp
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import LinkRayConfig, NodeHost
from .render import render_master, render_node


@dataclass(frozen=True)
class InstallAction:
    kind: str
    source: Path | None
    target: Path
    backup: Path | None = None

    def describe(self) -> str:
        if self.kind == "mkdir":
            return f"mkdir {self.target}"
        if self.kind == "skip":
            return f"skip unchanged {self.target}"
        if self.backup:
            return f"copy {self.source} -> {self.target} (backup {self.backup})"
        return f"copy {self.source} -> {self.target}"


def target_path(root: Path, rendered_file: Path, rendered_root: Path) -> Path:
    relative = rendered_file.relative_to(rendered_root)
    if root == Path("/"):
        return Path("/") / relative
    return root / relative


def copy_with_backup(source: Path, target: Path, apply: bool, stamp: str) -> InstallAction:
    target.parent.mkdir(parents=True, exist_ok=True) if apply else None
    if target.exists() and filecmp.cmp(source, target, shallow=False):
        return InstallAction("skip", source, target)
    backup = None
    if target.exists():
        backup = target.with_name(f"{target.name}.linkray.bak-{stamp}")
        if apply:
            shutil.copy2(target, backup)
    if apply:
        shutil.copy2(source, target)
    return InstallAction("copy", source, target, backup)


def install_rendered(rendered_root: Path, root: Path, apply: bool) -> list[InstallAction]:
    actions: list[InstallAction] = []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    for source in sorted(path for path in rendered_root.rglob("*") if path.is_file()):
        target = target_path(root, source, rendered_root)
        actions.append(copy_with_backup(source, target, apply, stamp))
    return actions


def install_master(
    config: LinkRayConfig,
    root: Path,
    apply: bool,
    nodes: list[NodeHost] | None = None,
) -> list[InstallAction]:
    with tempfile.TemporaryDirectory(prefix="linkray-master-") as tmp:
        rendered = Path(tmp)
        render_master(config, rendered, nodes=nodes)
        return install_rendered(rendered, root, apply)


def install_node(root: Path, apply: bool, config: LinkRayConfig | None = None) -> list[InstallAction]:
    with tempfile.TemporaryDirectory(prefix="linkray-node-") as tmp:
        rendered = Path(tmp)
        render_node(rendered, config=config)
        return install_rendered(rendered, root, apply)
