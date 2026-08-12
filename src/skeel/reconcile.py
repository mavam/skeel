from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from .gh import (
    InstalledSkill,
    SkillStep,
    desired_aliases,
    desired_label,
    install_steps,
    installed_source_matches,
    manual_install_steps,
    source_skill_label,
)
from .manifest import DesiredSkill, Manifest, SkillSpec, SourceSpec, parse_skill
from .targets import SkillTarget


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


@dataclass(frozen=True)
class SkillShadowWarning:
    name: str
    shadowing_scope: str
    shadowed_scope: str
    project_label: str
    user_label: str
    duplicate: bool = False

    @property
    def message(self) -> str:
        shadowed = shadow_scope_label(self.shadowed_scope)
        shadowing = shadow_scope_label(self.shadowing_scope)
        if self.duplicate:
            return (
                f'warning: skill "{self.name}" is installed in both '
                f"{shadowing} and {shadowed} scope; "
                "the agent decides which copy takes precedence at runtime"
            )
        return (
            f'warning: {shadowed} skill "{self.name}" is shadowed by '
            f'{shadowing} skill "{self.project_label}"; '
            f"{shadowing} scope is effective and {shadowed} scope was skipped"
        )

    def json(self) -> dict[str, object]:
        return {
            "type": "duplicate-skill" if self.duplicate else "shadowed-skill",
            "name": self.name,
            "shadowing_scope": self.shadowing_scope,
            "shadowed_scope": self.shadowed_scope,
            "project_label": self.project_label,
            "user_label": self.user_label,
            "message": self.message,
        }


@dataclass(frozen=True)
class SkillShadowIndex:
    labels_by_alias: dict[str, str]
    names_by_alias: dict[str, str]

    @property
    def has_entries(self) -> bool:
        return bool(self.labels_by_alias)

    def add(self, aliases: Sequence[str], *, label: str, name: str) -> None:
        for alias in aliases:
            self.labels_by_alias.setdefault(alias, label)
            self.names_by_alias.setdefault(alias, name)

    def match(self, aliases: Sequence[str]) -> tuple[str, str] | None:
        for alias in aliases:
            if label := self.labels_by_alias.get(alias):
                return self.names_by_alias[alias], label
        return None


def shadow_scope_label(scope: str) -> str:
    return "user/global" if scope == "user" else scope


def build_skill_shadow_index(
    manifest: Manifest | None,
    installed: Sequence[InstalledSkill],
) -> SkillShadowIndex:
    index = SkillShadowIndex(labels_by_alias={}, names_by_alias={})
    if manifest is not None:
        for desired in manifest.desired_skills:
            index.add(
                desired_skill_shadow_aliases(desired),
                label=desired_label(desired),
                name=desired.name,
            )
    for installed_skill in installed:
        index.add(
            installed_skill_shadow_aliases(installed_skill),
            label=installed_skill.label,
            name=installed_skill.basename,
        )
    return index


def filter_shadowed_manifest(
    manifest: Manifest,
    shadow_index: SkillShadowIndex,
    *,
    shadowing_scope: str = "project",
    shadowed_scope: str = "user",
) -> tuple[Manifest, tuple[SkillShadowWarning, ...]]:
    if not shadow_index.has_entries:
        return manifest, ()

    sources: list[SourceSpec] = []
    warnings: list[SkillShadowWarning] = []
    for source in manifest.sources:
        if source.install_all:
            sources.append(source)
            continue

        skills: list[SkillSpec] = []
        for skill in source.skills:
            desired = DesiredSkill(name=skill.name, spec=skill.spec, source=source.source)
            if warning := shadow_warning_for_desired_skill(
                desired,
                shadow_index,
                shadowing_scope=shadowing_scope,
                shadowed_scope=shadowed_scope,
            ):
                warnings.append(warning)
                continue
            skills.append(skill)

        if skills:
            sources.append(
                SourceSpec(
                    source=source.source,
                    skills=tuple(skills),
                    pin=source.pin,
                    install=source.install,
                )
            )

    return (
        Manifest(path=manifest.path, sources=tuple(sources)),
        unique_shadow_warnings(warnings),
    )


def filter_shadowed_installed(
    installed: Sequence[InstalledSkill],
    shadow_index: SkillShadowIndex,
    *,
    shadowing_scope: str = "project",
    shadowed_scope: str = "user",
) -> tuple[tuple[InstalledSkill, ...], tuple[SkillShadowWarning, ...]]:
    if not shadow_index.has_entries:
        return tuple(installed), ()

    kept: list[InstalledSkill] = []
    warnings: list[SkillShadowWarning] = []
    for skill in installed:
        if warning := shadow_warning_for_installed_skill(
            skill,
            shadow_index,
            shadowing_scope=shadowing_scope,
            shadowed_scope=shadowed_scope,
        ):
            warnings.append(warning)
            continue
        kept.append(skill)
    return tuple(kept), unique_shadow_warnings(warnings)


def filter_shadowed_dynamic_sources(
    manifest: Manifest,
    original_installed: Sequence[InstalledSkill],
    filtered_installed: Sequence[InstalledSkill],
) -> Manifest:
    sources: list[SourceSpec] = []
    for source in manifest.sources:
        if not source.install_all:
            sources.append(source)
            continue
        if matching_dynamic_source_skills(
            source,
            original_installed,
        ) and not matching_dynamic_source_skills(source, filtered_installed):
            continue
        sources.append(source)
    return Manifest(path=manifest.path, sources=tuple(sources))


def shadow_warning_for_desired_skill(
    skill: DesiredSkill,
    shadow_index: SkillShadowIndex,
    *,
    shadowing_scope: str,
    shadowed_scope: str,
) -> SkillShadowWarning | None:
    if match := shadow_index.match(desired_skill_shadow_aliases(skill)):
        name, project_label = match
        return SkillShadowWarning(
            name=name,
            shadowing_scope=shadowing_scope,
            shadowed_scope=shadowed_scope,
            project_label=project_label,
            user_label=desired_label(skill),
        )
    return None


def shadow_warning_for_installed_skill(
    skill: InstalledSkill,
    shadow_index: SkillShadowIndex,
    *,
    shadowing_scope: str,
    shadowed_scope: str,
) -> SkillShadowWarning | None:
    if match := shadow_index.match(installed_skill_shadow_aliases(skill)):
        name, project_label = match
        return SkillShadowWarning(
            name=name,
            shadowing_scope=shadowing_scope,
            shadowed_scope=shadowed_scope,
            project_label=project_label,
            user_label=skill.label,
        )
    return None


def unique_shadow_warnings(
    warnings: Sequence[SkillShadowWarning],
) -> tuple[SkillShadowWarning, ...]:
    unique: list[SkillShadowWarning] = []
    seen: set[tuple[str, str, str]] = set()
    for warning in warnings:
        key = (warning.shadowed_scope, warning.name, warning.project_label)
        if key in seen:
            continue
        seen.add(key)
        unique.append(warning)
    return tuple(unique)


def desired_skill_shadow_aliases(skill: DesiredSkill) -> tuple[str, ...]:
    return shadow_aliases(skill.name, Path(skill.name).name, Path(skill.spec).name)


def installed_skill_shadow_aliases(skill: InstalledSkill) -> tuple[str, ...]:
    return shadow_aliases(skill.name, skill.basename, skill.path.name)


def shadow_aliases(*values: str) -> tuple[str, ...]:
    aliases: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value == "*" or value in seen:
            continue
        seen.add(value)
        aliases.append(value)
    return tuple(aliases)


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
    agent: str | None
    manifest_path: Path | None
    name: str
    source: str
    label: str
    status: str
    path: Path | None = None
    version: str | None = None
    dynamic: bool = False
    managed: bool = True

    def json(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "scope": self.scope,
            **({"agent": self.agent} if self.agent is not None else {}),
            "name": self.name,
            "source": self.source,
            "label": self.label,
            "status": self.status,
        }
        if self.manifest_path is not None:
            payload["manifest"] = str(self.manifest_path)
        if self.path is not None:
            payload["path"] = str(self.path)
        if self.version:
            payload["version"] = self.version
        if self.dynamic:
            payload["dynamic"] = True
        if not self.managed:
            payload["managed"] = False
        return payload


def diff_installed_skills(
    manifest: Manifest,
    installed: Sequence[InstalledSkill],
) -> SkillDiff:
    desired = {skill.name: skill for skill in manifest.desired_skills}
    installed_index = installed_skill_index(installed)
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
    missing: list[DesiredSkill] = []
    for source in manifest.sources:
        if source.install_all:
            if not dynamic_source_satisfied(source, installed):
                missing.append(DesiredSkill(name="*", spec="*", source=source.source))
            continue
        for skill in source.skills:
            desired_skill = DesiredSkill(name=skill.name, spec=skill.spec, source=source.source)
            match = matching_installed_skill(desired_skill, installed_index)
            if match is None or not installed_source_matches(match, source):
                missing.append(desired_skill)
    return SkillDiff(
        missing=tuple(missing),
        extra=tuple(sorted(extra, key=lambda skill: skill.name)),
    )


def list_manifest_skills(
    manifest: Manifest,
    installed: Sequence[InstalledSkill],
    *,
    scope: str,
    agent: str | None = None,
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
                        agent=agent,
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
                        agent=agent,
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
                    agent=agent,
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


def list_installed_skills(
    manifest: Manifest | None,
    installed: Sequence[InstalledSkill],
    *,
    scope: str,
    agent: str | None = None,
) -> tuple[ListedSkill, ...]:
    if manifest is None:
        return unmanaged_installed_skill_rows(
            installed,
            scope=scope,
            agent=agent,
            manifest_path=None,
        )

    rows = list(list_manifest_skills(manifest, installed, scope=scope, agent=agent))
    rows.extend(
        unmanaged_installed_skill_rows(
            diff_installed_skills(manifest, installed).extra,
            scope=scope,
            agent=agent,
            manifest_path=None,
        )
    )
    return tuple(rows)


def unmanaged_installed_skill_rows(
    installed: Sequence[InstalledSkill],
    *,
    scope: str,
    agent: str | None = None,
    manifest_path: Path | None,
) -> tuple[ListedSkill, ...]:
    return tuple(
        ListedSkill(
            scope=scope,
            agent=agent,
            manifest_path=manifest_path,
            name=skill.basename,
            source=skill.github_source or skill.source_url,
            label=skill.label,
            status="installed",
            path=skill.path,
            version=skill.version_label,
            managed=False,
        )
        for skill in sorted(installed, key=lambda skill: (skill.label, str(skill.path)))
    )


def apply_plan(
    manifest: Manifest,
    target: SkillTarget,
    installed: Sequence[InstalledSkill],
    *,
    reinstall: bool = False,
    selector: ApplySelector | None = None,
    prune: bool = False,
    removals: Sequence[RemoveTarget] = (),
) -> list[SkillStep]:
    selected_manifest = filter_manifest(manifest, selector)
    if reinstall:
        return list(iter_install_plan(selected_manifest, target))

    diff = diff_installed_skills(selected_manifest, installed)
    install = list(
        iter_install_plan(
            selected_manifest,
            target,
            missing={(skill.source, skill.name) for skill in diff.missing},
            installed=installed,
        )
    )
    if selector is not None:
        return install

    # Extras are preserved by default; ``prune`` removes them all, while
    # explicit ``removals`` (from `skeel remove --apply`) delete exactly the
    # deselected skills.
    if prune:
        removable = diff.extra
    else:
        removable = tuple(
            skill
            for skill in diff.extra
            if any(matches_remove_target(skill, removal) for removal in removals)
        )
    remove = remove_steps(removable, target)
    if has_missing_dynamic_source(selected_manifest, diff):
        return [*remove, *install]
    return [*install, *remove]


def matches_remove_target(skill: InstalledSkill, removal: RemoveTarget) -> bool:
    if removal.skill is None:
        return skill.github_source == removal.source or (
            not skill.github_source and skill.basename == Path(removal.source).name
        )
    name = parse_skill(removal.skill).name
    if name not in {skill.name, skill.basename, skill.path.name}:
        return False
    return skill.github_source in ("", removal.source)


def has_missing_dynamic_source(manifest: Manifest, diff: SkillDiff) -> bool:
    missing_sources = {skill.source for skill in diff.missing if skill.name == "*"}
    return any(
        source.install_all and source.source in missing_sources for source in manifest.sources
    )


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


MissingKey = tuple[str, str]


def iter_install_plan(
    manifest: Manifest,
    target: SkillTarget,
    *,
    missing: set[MissingKey] | None = None,
    installed: Sequence[InstalledSkill] = (),
) -> Iterator[SkillStep]:
    for source in manifest.sources:
        if missing is not None and not source.install_all and not source.install:
            skills = tuple(
                skill for skill in source.skills if missing_key(source, skill.name) in missing
            )
            if not skills:
                continue
            source = SourceSpec(source=source.source, skills=skills, pin=source.pin)
        if missing is not None and source.install_all and missing_key(source, "*") not in missing:
            continue
        if source.install:
            if missing is not None and not any(
                missing_key(source, skill.name) in missing for skill in source.skills
            ):
                continue
            yield from manual_install_steps(source, target, manifest)
            continue
        yield from install_steps(source, target)


def missing_key(source: SourceSpec, name: str) -> MissingKey:
    return (source.source, name)


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
            if not matches and selector.skill is None:
                matches = tuple(skill for skill in installed if not skill.github_source)
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


def dynamic_source_satisfied(source: SourceSpec, installed: Sequence[InstalledSkill]) -> bool:
    return any(
        installed_skill_matches_dynamic_source(skill, source)
        and installed_source_matches(skill, source)
        for skill in installed
    )


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


def remove_steps(extra: Sequence[InstalledSkill], target: SkillTarget) -> list[SkillStep]:
    root = target.directory.resolve()
    steps: list[SkillStep] = []
    for skill in extra:
        if skill.path.is_symlink():
            raise ValueError(f"refusing to remove symlinked skill: {skill.path}")
        path = skill.path.resolve()
        if path == root or not path.is_relative_to(root):
            raise ValueError(f"refusing to remove skill outside target directory: {skill.path}")
        if skill.path.exists() and not (skill.path / "SKILL.md").is_file():
            raise ValueError(f"refusing to remove directory without SKILL.md: {skill.path}")
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
