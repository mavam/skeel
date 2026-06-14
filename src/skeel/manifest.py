from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_MANIFEST = ".agents/skills.yaml"


@dataclass(frozen=True)
class SkillSpec:
    spec: str
    name: str
    pin: str | None = None


@dataclass(frozen=True)
class SourceSpec:
    source: str
    skills: tuple[SkillSpec, ...]
    install_all: bool = False
    pin: str | None = None
    install: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class DesiredSkill:
    name: str
    spec: str
    source: str


@dataclass(frozen=True)
class Manifest:
    path: Path
    sources: tuple[SourceSpec, ...]

    @property
    def desired_skill_names(self) -> set[str]:
        return {skill.name for skill in self.desired_skills}

    @property
    def desired_skills(self) -> tuple[DesiredSkill, ...]:
        return tuple(
            DesiredSkill(
                name=skill.name,
                spec=skill.spec,
                source=source.source,
            )
            for source in self.sources
            for skill in source.skills
        )

    @property
    def has_dynamic_sources(self) -> bool:
        return any(source.install_all for source in self.sources)


@dataclass(frozen=True)
class ManifestUpdate:
    manifest: Manifest
    changed: bool


def manifest_path(value: str | None = None, *, base: Path | None = None) -> Path:
    if value:
        return Path(value).expanduser()
    if env_value := os.environ.get("SKEEL_MANIFEST"):
        return Path(env_value).expanduser()
    path = Path(DEFAULT_MANIFEST)
    return base / path if base is not None else path


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


def parse_source(source: Any, value: Any) -> SourceSpec:
    if not isinstance(source, str) or not source:
        raise ValueError("manifest source keys must be non-empty strings")

    if value is None:
        return SourceSpec(source=source, skills=(), install_all=True)
    if isinstance(value, list):
        skills = tuple(parse_skill(skill) for skill in value)
        if not skills:
            raise ValueError(f"source {source} has no skills")
        return SourceSpec(source=source, skills=skills)
    if not isinstance(value, dict):
        raise ValueError(f"source {source} must be empty, a skill list, or an options mapping")

    if "source" in value or "github" in value:
        raise ValueError("source entries use mapping keys, not source/github fields")
    if "backend" in value:
        raise ValueError("manifest backends are not supported; skeel always uses gh skill")

    install = tuple(parse_command(command) for command in value.get("install") or [])
    source_pin = value.get("pin")
    pin = str(source_pin) if source_pin else None
    skills_value = value.get("skills") or []
    if not isinstance(skills_value, list):
        raise ValueError(f"source {source} skills must be a list")
    skills = tuple(parse_skill(skill, source_pin=pin) for skill in skills_value)
    install_all = bool(not skills and not install)
    if not skills and not install_all:
        raise ValueError(f"source {source} has no skills")
    return SourceSpec(
        source=source,
        skills=skills,
        install_all=install_all,
        pin=str(source_pin) if source_pin else None,
        install=install,
    )


class _ManifestDumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> Any:
        del indentless
        return super().increase_indent(flow, False)


def _represent_none(dumper: yaml.SafeDumper, data: None) -> yaml.nodes.ScalarNode:
    del data
    return dumper.represent_scalar("tag:yaml.org,2002:null", "")


_ManifestDumper.add_representer(type(None), _represent_none)


def manifest_yaml(data: dict[str, Any]) -> str:
    return yaml.dump(data, Dumper=_ManifestDumper, sort_keys=False).rstrip() + "\n"


def load_manifest_data(path: Path, *, missing_ok: bool = True) -> dict[str, Any]:
    if not path.exists():
        if not missing_ok:
            raise FileNotFoundError(path)
        return {"sources": {}}

    data = yaml.safe_load(path.read_text())
    if data is None:
        return {"sources": []}
    if not isinstance(data, dict):
        raise ValueError(f"manifest must be a YAML mapping: {path}")
    return dict(data)


def parse_manifest_data(data: dict[str, Any], path: Path) -> Manifest:
    sources_value = data.get("sources") or {}
    if not isinstance(sources_value, dict):
        raise ValueError("manifest sources must be a mapping")
    sources = tuple(parse_source(source, value) for source, value in sources_value.items())

    return Manifest(
        path=path,
        sources=sources,
    )


def load_manifest(path: Path) -> Manifest:
    return parse_manifest_data(load_manifest_data(path, missing_ok=False), path)


def save_manifest_data(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest_yaml(data))


def upsert_manifest_source(
    path: Path,
    source: str,
    skill: str | None = None,
    *,
    dry_run: bool = False,
) -> ManifestUpdate:
    data = load_manifest_data(path)
    changed = upsert_source(data, source, skill)
    manifest = parse_manifest_data(data, path)
    if changed and not dry_run:
        save_manifest_data(path, data)
    return ManifestUpdate(manifest=manifest, changed=changed)


def remove_manifest_source(
    path: Path,
    source: str,
    skill: str | None = None,
    *,
    dry_run: bool = False,
) -> ManifestUpdate:
    data = load_manifest_data(path)
    changed = remove_source(data, source, skill)
    manifest = parse_manifest_data(data, path)
    if changed and not dry_run:
        save_manifest_data(path, data)
    return ManifestUpdate(manifest=manifest, changed=changed)


def upsert_source(data: dict[str, Any], source: str, skill: str | None = None) -> bool:
    if not source.strip():
        raise ValueError("source is required")
    if skill is not None and not skill.strip():
        raise ValueError("skill is required")

    sources = manifest_sources(data)
    if source not in sources:
        sources[source] = [skill] if skill else None
        return True

    if skill is None:
        return select_all_skills(sources, source)

    return upsert_source_skill(sources, source, skill)


def remove_source(data: dict[str, Any], source: str, skill: str | None = None) -> bool:
    if not source.strip():
        raise ValueError("source is required")
    if skill is not None and not skill.strip():
        raise ValueError("skill is required")

    sources = manifest_sources(data)
    if source not in sources:
        return False
    if skill is None:
        del sources[source]
        return True
    return remove_source_skill(sources, source, skill)


def manifest_sources(data: dict[str, Any]) -> dict[Any, Any]:
    sources = data.setdefault("sources", {})
    if not isinstance(sources, dict):
        raise ValueError("manifest sources must be a mapping")
    return sources


def select_all_skills(sources: dict[Any, Any], source: str) -> bool:
    current = sources[source]
    if current is None:
        return False
    next_value: dict[Any, Any] | None
    if isinstance(current, dict):
        if current.get("install"):
            raise ValueError(f"source {source} uses custom install commands; add skills explicitly")
        next_value = dict(current)
        next_value.pop("skills", None)
        next_value = next_value or None
    elif isinstance(current, list):
        next_value = None
    else:
        raise ValueError(f"source {source} must be empty, a skill list, or an options mapping")
    if next_value == current:
        return False
    sources[source] = next_value
    return True


def upsert_source_skill(sources: dict[Any, Any], source: str, skill: str) -> bool:
    current = sources[source]
    if current is None:
        sources[source] = [skill]
        return True
    if isinstance(current, list):
        skills = list(current)
        changed = upsert_skill(skills, skill)
        if changed:
            sources[source] = skills
        return changed
    if isinstance(current, dict):
        skills_value = current.get("skills") or []
        if not isinstance(skills_value, list):
            raise ValueError(f"source {source} skills must be a list")
        skills = list(skills_value)
        changed = upsert_skill(skills, skill)
        if changed or "skills" not in current:
            next_value = dict(current)
            next_value["skills"] = skills
            sources[source] = next_value
            return True
        return False
    raise ValueError(f"source {source} must be empty, a skill list, or an options mapping")


def remove_source_skill(sources: dict[Any, Any], source: str, skill: str) -> bool:
    current = sources[source]
    if current is None:
        raise ValueError(f"source {source} selects all skills; remove the source instead")
    if isinstance(current, list):
        skills = list(current)
        changed = remove_skill(skills, skill)
        if not changed:
            return False
        if skills:
            sources[source] = skills
        else:
            del sources[source]
        return True
    if isinstance(current, dict):
        skills_value = current.get("skills") or []
        if not isinstance(skills_value, list):
            raise ValueError(f"source {source} skills must be a list")
        if not skills_value:
            raise ValueError(f"source {source} selects all skills; remove the source instead")
        skills = list(skills_value)
        changed = remove_skill(skills, skill)
        if not changed:
            return False
        if skills:
            next_value = dict(current)
            next_value["skills"] = skills
            sources[source] = next_value
        else:
            del sources[source]
        return True
    raise ValueError(f"source {source} must be empty, a skill list, or an options mapping")


def upsert_skill(skills: list[Any], skill: str) -> bool:
    desired = parse_skill(skill)
    for index, current in enumerate(skills):
        if parse_skill(current).name == desired.name:
            if current == skill:
                return False
            skills[index] = skill
            return True
    skills.append(skill)
    return True


def remove_skill(skills: list[Any], skill: str) -> bool:
    desired = parse_skill(skill)
    for index, current in enumerate(skills):
        if parse_skill(current).name == desired.name:
            del skills[index]
            return True
    return False
