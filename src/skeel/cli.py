from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, override

from clypi import ClypiConfig, ClypiFormatter, Command, Positional, arg, configure

from . import __version__
from .gh import (
    GhOptions,
    InstalledSkill,
    SkillStep,
    desired_aliases,
    desired_label,
    install_steps,
    installed_skills,
    manual_install_steps,
    source_skill_label,
    update_steps,
)
from .io import ProcessRunner, StepResult, Terminal
from .manifest import (
    DesiredSkill,
    Manifest,
    SkillSpec,
    SourceSpec,
    load_manifest,
    manifest_path,
    parse_skill,
    remove_manifest_source,
    upsert_manifest_source,
)


def parse_scope(value: object) -> str:
    scope = str(value)
    if scope not in {"project", "user"}:
        raise ValueError("scope must be 'project' or 'user'")
    return scope


def manifest_arg(*, inherited: bool = False) -> str | None:
    return arg(
        None,
        short="m",
        inherited=inherited,
        help="Skill manifest path. Defaults to .agents/skills.yaml in the selected scope.",
    )


def scope_arg(*, inherited: bool = False) -> str | None:
    return arg(
        None,
        parser=parse_scope,
        inherited=inherited,
        help="Target scope. One of: project, user.",
    )


def dry_run_arg(*, inherited: bool = False) -> bool:
    return arg(
        False,
        inherited=inherited,
        help="Show what would run without applying changes.",
    )


def reinstall_arg(*, inherited: bool = False) -> bool:
    return arg(
        False,
        inherited=inherited,
        help="Reinstall every manifest entry instead of only reconciling drift.",
    )


def json_arg(*, inherited: bool = False) -> bool:
    return arg(
        False,
        inherited=inherited,
        help="Write machine-readable JSON to stdout.",
    )


class CommonOptions(Protocol):
    manifest: str | None
    scope: str | None
    dry_run: bool
    json: bool


class ApplyOptions(CommonOptions, Protocol):
    reinstall: bool
    source: str | None
    skill: str | None


class AddOptions(CommonOptions, Protocol):
    source: str
    skill: str | None
    apply: bool


class RemoveOptions(CommonOptions, Protocol):
    source: str
    skill: str | None
    apply: bool


@dataclass(frozen=True)
class ApplySelector:
    source: str
    skill: str | None = None


@dataclass(frozen=True)
class Runtime:
    manifest_path: Path
    manifest_required: bool
    options: GhOptions
    runner: ProcessRunner
    terminal: Terminal


@dataclass(frozen=True)
class ManifestContext:
    scope: str
    runtime: Runtime
    manifest: Manifest


@dataclass(frozen=True)
class ManifestSelection:
    contexts: tuple[ManifestContext, ...]
    missing_paths: tuple[Path, ...]

    @property
    def found_manifest(self) -> bool:
        return bool(self.contexts)


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


def build_runtime(command: CommonOptions) -> Runtime:
    return build_runtime_for_scope(command, scope=single_scope(command))


def single_scope(command: CommonOptions) -> str:
    return command.scope or "project"


def build_runtime_for_scope(command: CommonOptions, *, scope: str) -> Runtime:
    runner = ProcessRunner()
    env_manifest = os.environ.get("SKEEL_MANIFEST")
    base = Path.home() if scope == "user" else Path.cwd()
    manifest_base = base if scope == "user" else None
    return Runtime(
        manifest_path=manifest_path(command.manifest, base=manifest_base),
        manifest_required=command.manifest is not None or env_manifest is not None,
        options=GhOptions(directory=base / ".agents" / "skills"),
        runner=runner,
        terminal=Terminal(json_output=command.json),
    )


def manifest_scopes(command: CommonOptions) -> tuple[str, ...]:
    if command.manifest is not None or os.environ.get("SKEEL_MANIFEST") is not None:
        return (single_scope(command),)
    if command.scope is None:
        return ("project", "user")
    return (command.scope,)


def load_runtime_manifest(runtime: Runtime) -> Manifest | None:
    if not runtime.manifest_required and not runtime.manifest_path.exists():
        return None
    return load_manifest(runtime.manifest_path)


def select_manifest_contexts(command: CommonOptions) -> ManifestSelection:
    contexts: list[ManifestContext] = []
    missing_paths: list[Path] = []
    for scope in manifest_scopes(command):
        runtime = build_runtime_for_scope(command, scope=scope)
        manifest = load_runtime_manifest(runtime)
        if manifest is None:
            missing_paths.append(runtime.manifest_path)
            continue
        contexts.append(ManifestContext(scope=scope, runtime=runtime, manifest=manifest))
    return ManifestSelection(contexts=tuple(contexts), missing_paths=tuple(missing_paths))


def installed_name_aliases(names: set[str]) -> set[str]:
    return names | {Path(name).name for name in names}


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


async def diff_skills(
    manifest: Manifest,
    options: GhOptions,
    runner: ProcessRunner,
) -> SkillDiff:
    return diff_installed_skills(manifest, await installed_skills(options, runner))


def diff_installed_skills(
    manifest: Manifest,
    installed: Sequence[InstalledSkill],
) -> SkillDiff:
    desired = {skill.name: skill for skill in manifest.desired_skills}
    installed_names = {skill.name for skill in installed}
    installed_aliases = installed_name_aliases(installed_names)
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
    missing = tuple(desired[name] for name in sorted(set(desired) - installed_aliases))
    return SkillDiff(missing=missing, extra=tuple(sorted(extra, key=lambda skill: skill.name)))


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


def filter_source(source: SourceSpec, skill: str | None) -> SourceSpec | None:
    if skill is None:
        return source

    selected = parse_skill(skill, source_pin=source.pin if "@" not in skill else None)
    if source.install_all:
        return SourceSpec(
            source=source.source,
            skills=(selected,),
            pin=source.pin,
        )

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
            source = SourceSpec(
                source=source.source,
                skills=skills,
                pin=source.pin,
            )
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


def dynamic_source_installed(source: SourceSpec, installed: Sequence[InstalledSkill]) -> bool:
    return matching_dynamic_source_skill(source, installed) is not None


def matching_dynamic_source_skill(
    source: SourceSpec,
    installed: Sequence[InstalledSkill],
) -> InstalledSkill | None:
    return next(
        (skill for skill in installed if installed_skill_matches_dynamic_source(skill, source)),
        None,
    )


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
            )
        )
    return steps


def diff_json(diff: SkillDiff) -> dict[str, object]:
    return {
        "missing": [
            {
                "name": skill.name,
                "source": skill.source,
            }
            for skill in diff.missing
        ],
        "extra": [
            {
                "name": skill.name,
                "path": str(skill.path),
                "source": skill.source_url or None,
            }
            for skill in diff.extra
        ],
        "in_sync": diff.in_sync,
    }


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
            match = matching_dynamic_source_skill(source, installed)
            rows.append(
                ListedSkill(
                    scope=scope,
                    manifest_path=manifest.path,
                    name="*",
                    source=source.source,
                    label=source_skill_label(source.source, "*"),
                    status="installed" if match else "missing",
                    path=match.path if match else None,
                    version=match.version_label if match else None,
                    dynamic=True,
                )
            )
            continue

        for skill in source.skills:
            desired = DesiredSkill(
                name=skill.name,
                spec=skill.spec,
                source=source.source,
            )
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


def list_json(rows: Sequence[ListedSkill]) -> dict[str, object]:
    return {
        "skills": [row.json() for row in rows],
        "installed": sum(1 for row in rows if row.status == "installed"),
        "missing": sum(1 for row in rows if row.status == "missing"),
        "total": len(rows),
    }


def run_json(
    *,
    dry_run: bool,
    steps: Sequence[StepResult],
    missing: Sequence[str] = (),
    extra: Sequence[str] = (),
) -> dict[str, object]:
    failed = [step.label for step in failed_steps(steps)]
    return {
        "dry_run": dry_run,
        "missing": list(missing),
        "extra": list(extra),
        "steps": [step.json() for step in steps],
        "failed": failed,
    }


def add_json(
    *,
    manifest_path: Path,
    source: str,
    skill: str | None,
    changed: bool,
    dry_run: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "dry_run": dry_run,
        "manifest": str(manifest_path),
        "source": source,
        "changed": changed,
    }
    if skill is not None:
        payload["skill"] = skill
    return payload


def remove_json(
    *,
    manifest_path: Path,
    source: str,
    skill: str | None,
    changed: bool,
    dry_run: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "dry_run": dry_run,
        "manifest": str(manifest_path),
        "source": source,
        "changed": changed,
    }
    if skill is not None:
        payload["skill"] = skill
    return payload


def failed_steps(steps: Sequence[StepResult]) -> list[StepResult]:
    return [step for step in steps if step.returncode not in (None, 0)]


def install_failure_message(step: StepResult) -> str:
    return f"failed to install skill: {step.label}"


async def run_steps(
    steps: Sequence[SkillStep],
    runtime: Runtime,
    *,
    dry_run: bool,
    action: str,
    dry_run_action: str,
    done: str,
    keep_going: bool = False,
) -> tuple[list[StepResult], int]:
    results: list[StepResult] = []
    exit_code = 0
    for step in steps:
        if step.remove_path is not None:
            result = await runtime.terminal.remove_step(
                step.label,
                step.command,
                step.remove_path,
                dry_run=dry_run,
            )
        else:
            result = await runtime.terminal.run_step(
                step.label,
                step.command,
                runtime.runner,
                action=action,
                dry_run_action=dry_run_action,
                done=done,
                dry_run=dry_run,
                outcome=step.outcome,
                executor=step.executor,
            )
        results.append(result)
        if result.returncode not in (None, 0):
            assert result.returncode is not None
            exit_code = result.returncode
            if not keep_going:
                break
    return results, exit_code


async def command_path(command: CommonOptions) -> int:
    runtime = build_runtime(command)
    if command.json:
        runtime.terminal.json({"path": str(runtime.manifest_path)})
    else:
        runtime.terminal.line(str(runtime.manifest_path))
    return 0


async def command_diff(command: CommonOptions) -> int:
    terminal = Terminal(json_output=command.json)
    selection = select_manifest_contexts(command)
    if not selection.found_manifest:
        empty_diff = SkillDiff(missing=(), extra=())
        if command.json:
            terminal.json(diff_json(empty_diff))
        else:
            for path in selection.missing_paths:
                terminal.no_manifest(path)
        return 0

    diffs = [
        await diff_skills(context.manifest, context.runtime.options, context.runtime.runner)
        for context in selection.contexts
    ]
    diff = SkillDiff(
        missing=tuple(skill for current in diffs for skill in current.missing),
        extra=tuple(skill for current in diffs for skill in current.extra),
    )
    if command.json:
        terminal.json(diff_json(diff))
    else:
        terminal.diff(
            [(skill.name, skill.source) for skill in diff.missing],
            [(skill.name, skill.source_url or None) for skill in diff.extra],
            manifest_path=selection.contexts[0].manifest.path,
        )
    return 1 if not diff.in_sync else 0


async def command_list(command: CommonOptions) -> int:
    terminal = Terminal(json_output=command.json)
    selection = select_manifest_contexts(command)
    rows: list[ListedSkill] = []
    for context in selection.contexts:
        installed = await installed_skills(context.runtime.options, context.runtime.runner)
        rows.extend(list_manifest_skills(context.manifest, installed, scope=context.scope))

    if command.json:
        terminal.json(list_json(rows))
        return 0

    if not rows and not selection.found_manifest:
        for path in selection.missing_paths:
            terminal.no_manifest(path)
        return 0

    show_scope = len({row.scope for row in rows}) > 1
    for row in rows:
        detail_parts = [row.scope] if show_scope else []
        if row.version:
            detail_parts.append(row.version)
        terminal.status_line(
            "✔" if row.status == "installed" else "×",
            row.label,
            color="green" if row.status == "installed" else "red",
            detail=" ".join(detail_parts) or None,
        )
    return 0


async def command_apply(command: ApplyOptions) -> int:
    terminal = Terminal(json_output=command.json)
    selection = select_manifest_contexts(command)
    if not selection.found_manifest:
        if command.json:
            terminal.json(run_json(dry_run=command.dry_run, steps=[]))
        else:
            for path in selection.missing_paths:
                terminal.no_manifest(path)
        return 0

    results: list[StepResult] = []
    exit_code = 0
    selector = apply_selector(command)
    for context in selection.contexts:
        steps = await apply_steps(
            context.manifest,
            context.runtime,
            reinstall=command.reinstall,
            selector=selector,
        )
        context_results, context_exit_code = await run_apply_steps(command, context.runtime, steps)
        results.extend(context_results)
        if context_exit_code and not exit_code:
            exit_code = context_exit_code
    return finish_apply_results(command, terminal, results, exit_code)


async def apply_manifest(
    command: CommonOptions,
    runtime: Runtime,
    manifest: Manifest,
    *,
    reinstall: bool = False,
) -> int:
    steps = await apply_steps(manifest, runtime, reinstall=reinstall)
    results, exit_code = await run_apply_steps(command, runtime, steps)
    return finish_apply_results(
        command,
        runtime.terminal,
        results,
        exit_code,
    )


async def apply_steps(
    manifest: Manifest,
    runtime: Runtime,
    *,
    reinstall: bool = False,
    selector: ApplySelector | None = None,
) -> list[SkillStep]:
    selected_manifest = filter_manifest(manifest, selector)
    if reinstall:
        return list(iter_install_plan(selected_manifest, runtime.options))

    installed = await installed_skills(runtime.options, runtime.runner)
    diff = diff_installed_skills(selected_manifest, installed)
    steps = [
        *iter_install_plan(
            selected_manifest,
            runtime.options,
            missing={skill.name for skill in diff.missing},
            installed=installed,
        ),
    ]
    if selector is None:
        steps.extend(remove_steps(diff.extra, runtime.options))
    return steps


def apply_selector(command: ApplyOptions) -> ApplySelector | None:
    if command.source is None:
        return None
    return ApplySelector(source=command.source, skill=command.skill)


async def run_apply_steps(
    command: CommonOptions,
    runtime: Runtime,
    steps: Sequence[SkillStep],
) -> tuple[list[StepResult], int]:
    return await run_steps(
        steps,
        runtime,
        dry_run=command.dry_run,
        action="installing",
        dry_run_action="would install",
        done="installed",
    )


def finish_apply_results(
    command: CommonOptions,
    terminal: Terminal,
    results: Sequence[StepResult],
    exit_code: int,
) -> int:
    if command.json:
        terminal.json(run_json(dry_run=command.dry_run, steps=results))
    elif exit_code:
        failed = failed_steps(results)
        if failed:
            terminal.error(install_failure_message(failed[0]))
            terminal.failure_output(failed[0])
        else:
            terminal.error("install failed")
    return exit_code


async def command_add(command: AddOptions) -> int:
    runtime = build_runtime(command)
    update = upsert_manifest_source(
        runtime.manifest_path,
        command.source,
        command.skill,
        dry_run=command.dry_run,
    )
    if not command.apply:
        if command.json:
            runtime.terminal.json(
                add_json(
                    manifest_path=runtime.manifest_path,
                    source=command.source,
                    skill=command.skill,
                    changed=update.changed,
                    dry_run=command.dry_run,
                )
            )
        else:
            add_status_line(
                runtime.terminal,
                command,
                update.changed,
                manifest_path=runtime.manifest_path,
            )
        return 0

    if command.json:
        return await apply_manifest(command, runtime, update.manifest)

    add_status_line(
        runtime.terminal,
        command,
        update.changed,
        manifest_path=runtime.manifest_path,
    )
    return await apply_manifest(command, runtime, update.manifest)


async def command_remove(command: RemoveOptions) -> int:
    runtime = build_runtime(command)
    manifest_exists = runtime.manifest_path.exists()
    update = remove_manifest_source(
        runtime.manifest_path,
        command.source,
        command.skill,
        dry_run=command.dry_run,
    )
    if not command.apply:
        if command.json:
            runtime.terminal.json(
                remove_json(
                    manifest_path=runtime.manifest_path,
                    source=command.source,
                    skill=command.skill,
                    changed=update.changed,
                    dry_run=command.dry_run,
                )
            )
        else:
            remove_status_line(
                runtime.terminal,
                command,
                update.changed,
                manifest_path=runtime.manifest_path,
            )
        return 0

    if command.json:
        if not manifest_exists:
            runtime.terminal.json(run_json(dry_run=command.dry_run, steps=[]))
            return 0
        return await apply_manifest(command, runtime, update.manifest)

    remove_status_line(
        runtime.terminal,
        command,
        update.changed,
        manifest_path=runtime.manifest_path,
    )
    if not manifest_exists:
        return 0
    return await apply_manifest(command, runtime, update.manifest)


def add_status_line(
    terminal: Terminal,
    command: AddOptions,
    changed: bool,
    *,
    manifest_path: Path,
) -> None:
    color: Literal["cyan", "bright_black", "green"]
    if command.dry_run:
        marker, color = "•", "cyan" if changed else "bright_black"
    else:
        marker, color = ("✔", "green") if changed else ("•", "bright_black")
    terminal.status_line(
        marker,
        add_label(command.source, command.skill),
        color=color,
        detail=str(manifest_path),
    )


def remove_status_line(
    terminal: Terminal,
    command: RemoveOptions,
    changed: bool,
    *,
    manifest_path: Path,
) -> None:
    color: Literal["cyan", "bright_black", "green"]
    if command.dry_run:
        marker, color = "•", "cyan" if changed else "bright_black"
    else:
        marker, color = ("✔", "green") if changed else ("•", "bright_black")
    terminal.status_line(
        marker,
        add_label(command.source, command.skill),
        color=color,
        detail=str(manifest_path),
    )


def add_label(source: str, skill: str | None) -> str:
    return source_skill_label(source, parse_skill(skill).name if skill else "*")


async def command_update(command: CommonOptions) -> int:
    terminal = Terminal(json_output=command.json)
    selection = select_manifest_contexts(command)
    results: list[StepResult] = []
    exit_code = 0
    for context in selection.contexts:
        steps = update_steps(
            await installed_skills(context.runtime.options, context.runtime.runner),
            context.runtime.options,
            manifest=context.manifest,
        )
        scope_results, scope_exit_code = await run_steps(
            steps,
            context.runtime,
            dry_run=command.dry_run,
            action="updating",
            dry_run_action="would update",
            done="updated",
            keep_going=True,
        )
        results.extend(scope_results)
        if scope_exit_code and not exit_code:
            exit_code = scope_exit_code

    if not selection.found_manifest:
        if command.json:
            terminal.json(run_json(dry_run=command.dry_run, steps=[]))
        else:
            for path in selection.missing_paths:
                terminal.no_manifest(path)
        return 0

    if command.json:
        terminal.json(run_json(dry_run=command.dry_run, steps=results))
    elif exit_code:
        failed = failed_steps(results)
        labels = ", ".join(step.label for step in failed)
        terminal.error(f"failed to update skills: {labels}" if failed else "update failed")
        for step in failed:
            terminal.failure_output(step)
    return exit_code


class SkeelCommand(Command):
    async def execute(self) -> int:
        raise NotImplementedError


class PathCommand(SkeelCommand):
    """Print the resolved manifest path."""

    manifest: str | None = manifest_arg(inherited=True)
    scope: str | None = scope_arg(inherited=True)
    dry_run: bool = dry_run_arg(inherited=True)
    json: bool = json_arg(inherited=True)

    @override
    @classmethod
    def prog(cls) -> str:
        return "path"

    @override
    async def execute(self) -> int:
        return await command_path(self)


class Diff(SkeelCommand):
    """Compare desired skills with installed skills."""

    manifest: str | None = manifest_arg(inherited=True)
    scope: str | None = scope_arg(inherited=True)
    dry_run: bool = dry_run_arg(inherited=True)
    json: bool = json_arg(inherited=True)

    @override
    async def execute(self) -> int:
        return await command_diff(self)


class ListCommand(SkeelCommand):
    """Show manifest skill status."""

    manifest: str | None = manifest_arg(inherited=True)
    scope: str | None = scope_arg(inherited=True)
    dry_run: bool = dry_run_arg(inherited=True)
    json: bool = json_arg(inherited=True)

    @override
    @classmethod
    def prog(cls) -> str:
        return "list"

    @override
    async def execute(self) -> int:
        return await command_list(self)


class Apply(SkeelCommand):
    """Reconcile installed skills with the manifest."""

    source: Positional[str | None] = arg(
        None,
        help="Optional manifest source to apply, such as owner/repo.",
    )
    skill: Positional[str | None] = arg(
        None,
        help="Optional skill to apply from the selected source.",
    )
    manifest: str | None = manifest_arg(inherited=True)
    scope: str | None = scope_arg(inherited=True)
    dry_run: bool = dry_run_arg(inherited=True)
    reinstall: bool = reinstall_arg()
    json: bool = json_arg(inherited=True)

    @override
    async def execute(self) -> int:
        return await command_apply(self)


class Add(SkeelCommand):
    """Add or update a desired skill source in the manifest."""

    source: Positional[str] = arg(
        help="GitHub repository source to add, such as owner/repo.",
    )
    skill: Positional[str | None] = arg(
        None,
        help="Optional skill or skill@version to add. Omit to select all skills.",
    )
    apply: bool = arg(
        False,
        help="Apply the manifest after updating it.",
    )
    manifest: str | None = manifest_arg(inherited=True)
    scope: str | None = scope_arg(inherited=True)
    dry_run: bool = dry_run_arg(inherited=True)
    json: bool = json_arg(inherited=True)

    @override
    async def execute(self) -> int:
        return await command_add(self)


class Remove(SkeelCommand):
    """Remove a desired skill source from the manifest."""

    source: Positional[str] = arg(
        help="GitHub repository source to remove, such as owner/repo.",
    )
    skill: Positional[str | None] = arg(
        None,
        help="Optional skill to remove. Omit to remove the source.",
    )
    apply: bool = arg(
        False,
        help="Apply the manifest after updating it.",
    )
    manifest: str | None = manifest_arg(inherited=True)
    scope: str | None = scope_arg(inherited=True)
    dry_run: bool = dry_run_arg(inherited=True)
    json: bool = json_arg(inherited=True)

    @override
    async def execute(self) -> int:
        return await command_remove(self)


class Update(SkeelCommand):
    """Update installed skills declared by manifests."""

    manifest: str | None = manifest_arg(inherited=True)
    scope: str | None = scope_arg(inherited=True)
    dry_run: bool = dry_run_arg(inherited=True)
    json: bool = json_arg(inherited=True)

    @override
    async def execute(self) -> int:
        return await command_update(self)


class Skeel(Command):
    """Declarative agent skill manager."""

    manifest: str | None = manifest_arg()
    scope: str | None = scope_arg()
    dry_run: bool = dry_run_arg()
    json: bool = json_arg()
    subcommand: PathCommand | Diff | ListCommand | Apply | Add | Remove | Update | None = None

    @override
    @classmethod
    def epilog(cls) -> str | None:
        return f"skeel {__version__}"

    async def execute(self) -> int:
        command = self.subcommand
        if command is None:
            self.print_help()
        return await command.execute()


def configure_clypi() -> None:
    configure(
        ClypiConfig(
            disable_colors=os.environ.get("NO_COLOR") is not None,
            help_formatter=ClypiFormatter(boxed=False, show_option_types=False),
        )
    )


def main(argv: list[str] | None = None) -> int:
    configure_clypi()
    try:
        args = sys.argv[1:] if argv is None else argv
        if not args:
            Skeel.print_help()
        command = Skeel.parse(args)
        return asyncio.run(command.execute())
    except SystemExit as error:
        code = error.code
        if isinstance(code, int):
            return code
        return 1 if code else 0
    except KeyboardInterrupt:
        Terminal().error("interrupted")
        return 130
    except Exception as error:
        Terminal().error(str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
