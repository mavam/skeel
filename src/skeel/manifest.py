from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_MANIFEST = "~/.agents/.skill.yaml"
DEFAULT_SHARED_DIR = "~/.agents/skills"
DEFAULT_CLAUDE_DIR = "~/.claude/skills"


@dataclass(frozen=True)
class SkillSpec:
    spec: str
    name: str
    pin: str | None = None


@dataclass(frozen=True)
class SourceSpec:
    source: str
    skills: tuple[SkillSpec, ...]
    backend: str = "gh"
    allow_hidden_dirs: bool = False
    private: bool = False
    pin: str | None = None


@dataclass(frozen=True)
class Manifest:
    path: Path
    agents: tuple[str, ...]
    sources: tuple[SourceSpec, ...]
    shared_dir: Path = field(default_factory=lambda: Path(DEFAULT_SHARED_DIR).expanduser())
    claude_dir: Path = field(default_factory=lambda: Path(DEFAULT_CLAUDE_DIR).expanduser())

    @property
    def desired_skill_names(self) -> set[str]:
        return {skill.name for source in self.sources for skill in source.skills}


def manifest_path(value: str | None = None) -> Path:
    if value:
        return Path(value).expanduser()
    return Path(os.environ.get("SKEEL_MANIFEST", DEFAULT_MANIFEST)).expanduser()


def infer_skill_name(spec: str) -> str:
    spec = spec.split("@", 1)[0].rstrip("/")
    if spec == "*":
        raise ValueError("wildcard skills are not supported; list desired skills explicitly")
    if spec.endswith("/SKILL.md"):
        return Path(spec).parent.name
    if spec == "SKILL.md":
        raise ValueError("root SKILL.md entries require an explicit name")
    return Path(spec).name


def parse_skill(value: Any, *, source_pin: str | None = None) -> SkillSpec:
    if isinstance(value, str):
        return SkillSpec(spec=value, name=infer_skill_name(value), pin=source_pin)
    if not isinstance(value, dict):
        raise ValueError(f"invalid skill entry: {value!r}")

    spec = str(value.get("spec") or value.get("path") or value.get("name") or "")
    if not spec:
        raise ValueError(f"skill entry missing name/spec/path: {value!r}")
    name = str(value.get("name") or infer_skill_name(spec))
    pin = value.get("pin", source_pin)
    return SkillSpec(spec=spec, name=name, pin=str(pin) if pin else None)


def parse_source(value: Any) -> SourceSpec:
    if not isinstance(value, dict):
        raise ValueError(f"invalid source entry: {value!r}")
    source = str(value.get("source") or "")
    if not source:
        raise ValueError(f"source entry missing source: {value!r}")
    backend = str(value.get("backend") or "gh")
    source_pin = value.get("pin")
    pin = str(source_pin) if source_pin else None
    skills = tuple(parse_skill(skill, source_pin=pin) for skill in value.get("skills") or [])
    if not skills:
        raise ValueError(f"source {source} has no skills")
    return SourceSpec(
        source=source,
        skills=skills,
        backend=backend,
        allow_hidden_dirs=bool(value.get("allow_hidden_dirs") or value.get("allow-hidden-dirs")),
        private=bool(value.get("private")),
        pin=str(source_pin) if source_pin else None,
    )


def load_manifest(path: Path) -> Manifest:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"manifest must be a YAML mapping: {path}")

    agents = tuple(str(agent) for agent in data.get("agents") or [])
    if not agents:
        raise ValueError("manifest must define at least one agent")

    sources = tuple(parse_source(source) for source in data.get("sources") or [])
    if not sources:
        raise ValueError("manifest must define at least one source")

    return Manifest(
        path=path,
        agents=agents,
        sources=sources,
        shared_dir=Path(str(data.get("shared_dir") or DEFAULT_SHARED_DIR)).expanduser(),
        claude_dir=Path(str(data.get("claude_dir") or DEFAULT_CLAUDE_DIR)).expanduser(),
    )
