from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from .gh import (
    GhOptions,
    InstalledSkill,
    SkillStep,
    desired_aliases,
    desired_label,
    install_steps,
    manual_install_steps,
    source_skill_label,
)
from .manifest import DesiredSkill, Manifest, SkillSpec, SourceSpec, parse_skill


@dataclass(frozen=True)
class ApplySelector:
    source: str
    skill: str | None = None


@dataclass(frozen=True)
class RemoveTarget:
    source: str
    skill: str | None = None


class AmbiguousRemoveTarget(Exception):
    def __init__(self, target: str, candidates: Sequence[RemoveTarget]) -> None:
        self.target = target
        self.candidates = tuple(candidates)
        labels = ", ".join(
            source_skill_label(candidate.source, candidate.skill or "*")
            for candidate in self.candidates
        )
        super().__init__(
            f'"{target}" is ambiguous; it matches {labels}. '
            "Disambiguate with: skeel remove <skill> --source <source>."
        )


def resolve_remove_target(
    manifest: Manifest,
    skill: str | None,
    *,
    source: str | None = None,
) -> RemoveTarget | None:
    """Resolve a remove request to a concrete source and optional skill.

    An explicit ``source`` removes either that whole source or the selected skill
    from it. Without ``source``, ``skill`` must unambiguously name a single
    manifest skill.
    """
    if source is not None:
        selector = ApplySelector(source=source, skill=skill)
        if not selector_matches_manifest(manifest, selector):
            return None
        return RemoveTarget(source=source, skill=skill)

    if skill is None:
        return None

    candidates: list[RemoveTarget] = []
    for manifest_source in manifest.sources:
        for spec in manifest_source.skills:
            if spec.name == skill:
                candidates.append(RemoveTarget(source=manifest_source.source, skill=spec.name))

    if not candidates:
        return None
    if len(candidates) > 1:
        raise AmbiguousRemoveTarget(skill, candidates)
    return candidates[0]


@dataclass(frozen=True)
class SkillDiff:
    missing: tuple[DesiredSkill, ...]
    extra: tuple[InstalledSkill, ...]

    @property
    def in_sync(self) -> bool:
        return not self.missing and not self.extra


@dataclass(frozen=True)
class ListedSkill:
    scope: str
    manifest_path: Path
    name: str
    source: str
    label: str
    status: str
    path: Path | None = None
    version: str | None = None
    dynamic: bool = False

    def json(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "scope": self.scope,
            "manifest": str(self.manifest_path),
            "name": self.name,
            "source": self.source,
            "label": self.label,
            "status": self.status,
        }
        if self.path is not None:
            payload["path"] = str(self.path)
        if self.version:
            payload["version"] = self.version
        if self.dynamic:
            payload["dynamic"] = True
        return payload


def diff_installed_skills(
    manifest: Manifest,
    installed: Sequence[InstalledSkill],
) -> SkillDiff:
    desired = {skill.name: skill for skill in manifest.desired_skills}
    installed_names = {skill.name for skill in installed}
    installed_aliases = installed_names | {Path(name).name for name in installed_names}
    dynamic_sources = tuple(source for source in manifest.sources if source.install_all)
    extra = tuple(
        skill
        for skill in installed
        if skill.name not in desired
        and skill.basename not in desired
        and not any(
            installed_skill_matches_dynamic_source(skill, source) for source in dynamic_sources
        )
    )
    missing_names = set(desired) - installed_aliases
    missing = [skill for skill in manifest.desired_skills if skill.name in missing_names]
    missing.extend(
        DesiredSkill(name="*", spec="*", source=source.source)
        for source in dynamic_sources
        if not dynamic_source_installed(source, installed)
    )
    return SkillDiff(
        missing=tuple(missing),
        extra=tuple(sorted(extra, key=lambda skill: skill.name)),
    )


def list_manifest_skills(
    manifest: Manifest,
    installed: Sequence[InstalledSkill],
    *,
    scope: str,
) -> tuple[ListedSkill, ...]:
    rows: list[ListedSkill] = []
    installed_index = installed_skill_index(installed)
    for source in manifest.sources:
        if source.install_all:
            matches = matching_dynamic_source_skills(source, installed)
            if matches:
                rows.extend(
                    ListedSkill(
                        scope=scope,
                        manifest_path=manifest.path,
                        name=match.basename,
                        source=source.source,
                        label=source_skill_label(source.source, match.basename),
                        status="installed",
                        path=match.path,
                        version=match.version_label,
                        dynamic=True,
                    )
                    for match in matches
                )
            else:
                rows.append(
                    ListedSkill(
                        scope=scope,
                        manifest_path=manifest.path,
                        name="*",
                        source=source.source,
                        label=source_skill_label(source.source, "*"),
                        status="missing",
                        dynamic=True,
                    )
                )
            continue

        for skill in source.skills:
            desired = DesiredSkill(name=skill.name, spec=skill.spec, source=source.source)
            match = matching_installed_skill(desired, installed_index)
            rows.append(
                ListedSkill(
                    scope=scope,
                    manifest_path=manifest.path,
                    name=desired.name,
                    source=desired.source,
                    label=desired_label(desired),
                    status="installed" if match else "missing",
                    path=match.path if match else None,
                    version=match.version_label if match else None,
                )
            )
    return tuple(rows)


def apply_plan(
    manifest: Manifest,
    options: GhOptions,
    installed: Sequence[InstalledSkill],
    *,
    reinstall: bool = False,
    selector: ApplySelector | None = None,
) -> list[SkillStep]:
    selected_manifest = filter_manifest(manifest, selector)
    if reinstall:
        return list(iter_install_plan(selected_manifest, options))

    diff = diff_installed_skills(selected_manifest, installed)
    steps = [
        *iter_install_plan(
            selected_manifest,
            options,
            missing={skill.name for skill in diff.missing},
            installed=installed,
        ),
    ]
    if selector is None:
        steps.extend(remove_steps(diff.extra, options))
    return steps


def filter_manifest(
    manifest: Manifest,
    selector: ApplySelector | None,
) -> Manifest:
    if selector is None:
        return manifest

    sources: list[SourceSpec] = []
    for source in manifest.sources:
        if source.source != selector.source:
            continue
        if filtered_source := filter_source(source, selector.skill):
            sources.append(filtered_source)
    return Manifest(path=manifest.path, sources=tuple(sources))


def selector_label(selector: ApplySelector) -> str:
    return source_skill_label(
        selector.source,
        parse_skill(selector.skill).name if selector.skill else "*",
    )


def selector_matches_manifest(manifest: Manifest, selector: ApplySelector) -> bool:
    return bool(filter_manifest(manifest, selector).sources)


def filter_source(source: SourceSpec, skill: str | None) -> SourceSpec | None:
    if skill is None:
        return source

    selected = parse_skill(skill, source_pin=source.pin if "@" not in skill else None)
    if source.install_all:
        return SourceSpec(source=source.source, skills=(selected,), pin=source.pin)

    skills = tuple(
        current for current in source.skills if skill_matches_selector(current, selected)
    )
    if not skills:
        return None
    return SourceSpec(
        source=source.source,
        skills=skills,
        pin=source.pin,
        install=source.install,
    )


def skill_matches_selector(skill: SkillSpec, selected: SkillSpec) -> bool:
    return skill.name == selected.name or skill.spec == selected.spec


def iter_install_plan(
    manifest: Manifest,
    options: GhOptions,
    *,
    missing: set[str] | None = None,
    installed: Sequence[InstalledSkill] = (),
) -> Iterator[SkillStep]:
    for source in manifest.sources:
        if missing is not None and not source.install_all and not source.install:
            skills = tuple(skill for skill in source.skills if skill.name in missing)
            if not skills:
                continue
            source = SourceSpec(source=source.source, skills=skills, pin=source.pin)
        if (
            missing is not None
            and source.install_all
            and dynamic_source_installed(source, installed)
        ):
            continue
        if source.install:
            if missing is not None and not any(skill.name in missing for skill in source.skills):
                continue
            yield from manual_install_steps(source)
            continue
        yield from install_steps(source, options)


def installed_skill_index(installed: Sequence[InstalledSkill]) -> dict[str, InstalledSkill]:
    index: dict[str, InstalledSkill] = {}
    for skill in installed:
        for alias in {skill.name, skill.basename, skill.path.name}:
            index.setdefault(alias, skill)
    return index


def matching_installed_skill(
    desired: DesiredSkill,
    index: dict[str, InstalledSkill],
) -> InstalledSkill | None:
    for alias in desired_aliases(desired):
        if skill := index.get(alias):
            return skill
    return None


def update_installed_skills(
    manifest: Manifest,
    installed: Sequence[InstalledSkill],
    selector: ApplySelector | None,
) -> tuple[InstalledSkill, ...]:
    if selector is None:
        return tuple(installed)

    selected: list[InstalledSkill] = []
    seen_paths: set[Path] = set()
    installed_index = installed_skill_index(installed)
    for source in filter_manifest(manifest, selector).sources:
        if source.install_all:
            matches = matching_dynamic_source_skills(source, installed)
        else:
            matches = tuple(
                match
                for skill in source.skills
                if (
                    match := matching_installed_skill(
                        DesiredSkill(
                            name=skill.name,
                            spec=skill.spec,
                            source=source.source,
                        ),
                        installed_index,
                    )
                )
            )
        for match in matches:
            if match.path in seen_paths:
                continue
            seen_paths.add(match.path)
            selected.append(match)
    return tuple(selected)


def dynamic_source_installed(source: SourceSpec, installed: Sequence[InstalledSkill]) -> bool:
    return matching_dynamic_source_skill(source, installed) is not None


def matching_dynamic_source_skills(
    source: SourceSpec,
    installed: Sequence[InstalledSkill],
) -> tuple[InstalledSkill, ...]:
    return tuple(
        sorted(
            (skill for skill in installed if installed_skill_matches_dynamic_source(skill, source)),
            key=lambda skill: skill.basename,
        )
    )


def matching_dynamic_source_skill(
    source: SourceSpec,
    installed: Sequence[InstalledSkill],
) -> InstalledSkill | None:
    return next(iter(matching_dynamic_source_skills(source, installed)), None)


def installed_skill_matches_dynamic_source(skill: InstalledSkill, source: SourceSpec) -> bool:
    repo_name = Path(source.source).name
    return (
        skill.github_source == source.source
        or skill.basename == repo_name
        or skill.path.name == repo_name
    )


def remove_steps(extra: Sequence[InstalledSkill], options: GhOptions) -> list[SkillStep]:
    root = options.directory.resolve()
    steps: list[SkillStep] = []
    for skill in extra:
        path = skill.path.resolve()
        if path != root and not path.is_relative_to(root):
            raise ValueError(f"refusing to remove skill outside target directory: {skill.path}")
        steps.append(
            SkillStep(
                label=skill.label,
                command=["rm", "-rf", str(skill.path)],
                remove_path=skill.path,
                kind="remove",
                parallel=False,
            )
        )
    return steps
