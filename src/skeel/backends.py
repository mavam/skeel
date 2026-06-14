from __future__ import annotations

import json
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


@dataclass(frozen=True)
class BackendOptions:
    agent: str | None = None
    scope: str = "project"
    directory: Path | None = None


class Backend(Protocol):
    name: str

    def install_steps(
        self,
        source: SourceSpec,
        options: BackendOptions,
    ) -> list[InstallStep]: ...

    def update_steps(self) -> list[InstallStep]: ...


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


def manual_install_steps(source: SourceSpec) -> list[InstallStep]:
    label = source.source or ", ".join(skill.name for skill in source.skills)
    return [InstallStep(label=label, command=list(command)) for command in source.install]


class GhSkillBackend:
    name = "gh"

    def install_steps(
        self,
        source: SourceSpec,
        options: BackendOptions,
    ) -> list[InstallStep]:
        if not source.source:
            raise ValueError("gh backend sources must define source")

        steps: list[InstallStep] = []
        skills: tuple[SkillSpec | None, ...] = (None,) if source.install_all else source.skills
        for skill in skills:
            command = ["gh", "skill", "install", source.source]
            label = f"{source.source}/*"
            pin = source.pin
            if skill:
                command.append(skill.spec)
                label = f"{source.source}/{skill.spec}"
                pin = skill.pin
            else:
                command.append("--all")
            command.extend(target_args(options))
            command.append("--force")
            if pin:
                command.extend(["--pin", pin])
            steps.append(InstallStep(label=f"{label} ({target_label(options)})", command=command))
        return steps

    def update_steps(self) -> list[InstallStep]:
        return [
            InstallStep(
                label="gh skill update",
                command=["gh", "skill", "update", "--all"],
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


def project_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        return Path.cwd()
    return Path(result.stdout.strip())


def universal_skills_dir(scope: str) -> Path:
    if scope == "user":
        return Path.home() / ".agents" / "skills"
    return project_root() / ".agents" / "skills"


def target_directory(options: BackendOptions) -> Path | None:
    if options.directory:
        return options.directory
    if options.agent is None:
        return universal_skills_dir(options.scope)
    return None


def target_args(options: BackendOptions) -> list[str]:
    directory = target_directory(options)
    if directory:
        return ["--dir", str(directory)]
    if not options.agent:
        raise ValueError("backend options must define an agent or directory")
    return ["--agent", options.agent, "--scope", options.scope]


def target_label(options: BackendOptions) -> str:
    directory = target_directory(options)
    if directory:
        return str(directory)
    return f"{options.agent}/{options.scope}"


def installed_skill_names(options: BackendOptions) -> set[str]:
    directory = target_directory(options)
    if directory and not directory.exists():
        return set()

    names: set[str] = set()
    command = [
        "gh",
        "skill",
        "list",
        "--json",
        "skillName",
    ]
    command.extend(target_args(options))
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "gh skill list failed"
        raise RuntimeError(message)
    entries = json.loads(result.stdout or "[]")
    if not isinstance(entries, list):
        raise RuntimeError("gh skill list returned invalid JSON")
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("skillName"), str):
            raise RuntimeError("gh skill list returned invalid skill entries")
        names.add(entry["skillName"])
    return names


def desired_skill_names(manifest: Manifest) -> set[str]:
    return manifest.desired_skill_names
