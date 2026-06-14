from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .manifest import Manifest, SkillSpec, SourceSpec

Command = list[str]


@dataclass(frozen=True)
class InstallStep:
    label: str
    command: Command


class Backend(Protocol):
    name: str

    def install_steps(
        self,
        manifest: Manifest,
        source: SourceSpec,
        skill: SkillSpec,
    ) -> list[InstallStep]: ...

    def update_steps(self, manifest: Manifest) -> list[InstallStep]: ...


def quote_command(command: Command) -> str:
    return " ".join(shlex.quote(part) for part in command)


class Runner:
    def __init__(self, *, dry_run: bool = False) -> None:
        self.dry_run = dry_run

    def run(self, step: InstallStep, *, keep_going: bool = False) -> int:
        print(quote_command(step.command))
        if self.dry_run:
            return 0
        result = subprocess.run(step.command, check=False)
        if result.returncode and not keep_going:
            raise SystemExit(result.returncode)
        return result.returncode


class GhSkillBackend:
    name = "gh"

    def install_steps(
        self,
        manifest: Manifest,
        source: SourceSpec,
        skill: SkillSpec,
    ) -> list[InstallStep]:
        command = [
            "gh",
            "skill",
            "install",
            source.source,
            skill.spec,
            "--dir",
            str(manifest.shared_dir),
            "--force",
        ]
        if source.allow_hidden_dirs:
            command.append("--allow-hidden-dirs")
        if skill.pin:
            command.extend(["--pin", skill.pin])
        return [InstallStep(label=f"{source.source}/{skill.spec}", command=command)]

    def update_steps(self, manifest: Manifest) -> list[InstallStep]:
        return [
            InstallStep(
                label="gh skill update",
                command=["gh", "skill", "update", "--all", "--dir", str(manifest.shared_dir)],
            )
        ]


_BACKENDS: dict[str, Backend] = {
    GhSkillBackend.name: GhSkillBackend(),
}


def get_backend(name: str) -> Backend:
    try:
        return _BACKENDS[name]
    except KeyError as error:
        supported = ", ".join(sorted(_BACKENDS))
        message = f"unsupported backend {name!r}; supported backends: {supported}"
        raise ValueError(message) from error


def symlink_step(manifest: Manifest, skill: SkillSpec) -> InstallStep | None:
    if "claude-code" not in manifest.agents:
        return None
    source = manifest.shared_dir / skill.name
    target = manifest.claude_dir / skill.name
    rel = os.path.relpath(source, start=target.parent)
    return InstallStep(
        label=f"link claude-code/{skill.name}",
        command=["ln", "-sfn", rel, str(target)],
    )


def ensure_claude_symlink(manifest: Manifest, skill: SkillSpec) -> None:
    if "claude-code" not in manifest.agents:
        return
    source = manifest.shared_dir / skill.name
    target = manifest.claude_dir / skill.name
    if not source.exists():
        raise SystemExit(f"cannot link missing skill: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    rel = os.path.relpath(source, start=target.parent)
    if target.is_symlink() or target.exists():
        if target.is_dir() and not target.is_symlink():
            subprocess.run(["rm", "-rf", str(target)], check=True)
        else:
            target.unlink()
    target.symlink_to(rel, target_is_directory=True)


def installed_skill_names(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {item.name for item in path.iterdir() if item.is_dir() and (item / "SKILL.md").exists()}
