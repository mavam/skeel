from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_MANIFEST = "~/.agents/skills.yaml"


@dataclass(frozen=True)
class SkillSpec:
    spec: str
    name: str
    pin: str | None = None


@dataclass(frozen=True)
class SourceSpec:
    source: str | None
    skills: tuple[SkillSpec, ...]
    backend: str = "gh"
    install_all: bool = False
    pin: str | None = None
    install: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class Manifest:
    path: Path
    sources: tuple[SourceSpec, ...]

    @property
    def desired_skill_names(self) -> set[str]:
        return {skill.name for source in self.sources for skill in source.skills}

    @property
    def has_dynamic_sources(self) -> bool:
        return any(source.install_all for source in self.sources)


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


def parse_command(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(shlex.split(value))
    if isinstance(value, list) and all(isinstance(part, str) for part in value):
        return tuple(value)
    raise ValueError(f"invalid command entry: {value!r}")


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


def parse_shorthand_source(value: str) -> SourceSpec:
    if "@" not in value:
        return SourceSpec(source=value, skills=(), install_all=True)

    source, skill = value.split("@", 1)
    if not source or not skill:
        raise ValueError(f"invalid source shorthand: {value!r}")
    if "@" in skill:
        raise ValueError(
            f"source shorthand uses @ as the skill selector; use mapping form for pins: {value!r}"
        )
    return SourceSpec(source=source, skills=(parse_skill(skill),))


def parse_source(value: Any) -> SourceSpec:
    if isinstance(value, str):
        return parse_shorthand_source(value)
    if not isinstance(value, dict):
        raise ValueError(f"invalid source entry: {value!r}")

    if "source" in value and "github" in value and value["source"] != value["github"]:
        raise ValueError(f"source entry cannot define both source and github: {value!r}")

    source_value = value.get("github") or value.get("source")
    source = str(source_value) if source_value else None
    install = tuple(parse_command(command) for command in value.get("install") or [])
    if not source and not install:
        raise ValueError(f"source entry missing source or install commands: {value!r}")
    backend = str(value.get("backend") or "gh")
    source_pin = value.get("pin")
    pin = str(source_pin) if source_pin else None
    skills = tuple(parse_skill(skill, source_pin=pin) for skill in value.get("skills") or [])
    install_all = bool(source and not skills and not install)
    if not skills and not install_all:
        label = source or "manual source"
        raise ValueError(f"source {label} has no skills")
    return SourceSpec(
        source=source,
        skills=skills,
        backend=backend,
        install_all=install_all,
        pin=str(source_pin) if source_pin else None,
        install=install,
    )


def load_manifest(path: Path) -> Manifest:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"manifest must be a YAML mapping: {path}")

    sources = tuple(parse_source(source) for source in data.get("sources") or [])
    if not sources:
        raise ValueError("manifest must define at least one source")

    return Manifest(
        path=path,
        sources=sources,
    )
