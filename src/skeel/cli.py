from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, override

from clypi import ClypiConfig, ClypiFormatter, Command, Positional, arg, configure

from . import __version__
from .gh import (
    GhOptions,
    SkillStep,
    installed_skills,
    source_skill_label,
    update_steps,
)
from .io import (
    MARKER_FAILURE,
    MARKER_NOOP,
    MARKER_PREVIEW,
    MARKER_SUCCESS,
    SCOPE_USER,
    ProcessRunner,
    StepResult,
    Terminal,
    failed_steps,
    run_steps,
)
from .manifest import (
    Manifest,
    load_manifest,
    manifest_path,
    parse_skill,
    remove_manifest_source,
    upsert_manifest_source,
)
from .reconcile import (
    ApplySelector,
    ListedSkill,
    SkillDiff,
    apply_plan,
    diff_installed_skills,
    list_manifest_skills,
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


async def diff_skills(
    manifest: Manifest,
    options: GhOptions,
    runner: ProcessRunner,
) -> SkillDiff:
    return diff_installed_skills(manifest, await installed_skills(options, runner))


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


def install_failure_message(step: StepResult) -> str:
    return f"failed to install skill: {step.label}"


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

    for row in rows:
        detail_parts: list[str] = []
        if row.version:
            detail_parts.append(row.version)
        if row.scope == "user":
            detail_parts.append(SCOPE_USER)
        terminal.status_line(
            MARKER_SUCCESS if row.status == "installed" else MARKER_FAILURE,
            row.label,
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
    installed = () if reinstall else await installed_skills(runtime.options, runtime.runner)
    return apply_plan(
        manifest,
        runtime.options,
        installed,
        reinstall=reinstall,
        selector=selector,
    )


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
        dry_run_action="would install",
        default_status="installed",
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
    if command.dry_run:
        marker = MARKER_PREVIEW if changed else MARKER_NOOP
    else:
        marker = MARKER_SUCCESS if changed else MARKER_NOOP
    terminal.status_line(
        marker,
        add_label(command.source, command.skill),
        detail=str(manifest_path),
    )


def remove_status_line(
    terminal: Terminal,
    command: RemoveOptions,
    changed: bool,
    *,
    manifest_path: Path,
) -> None:
    if command.dry_run:
        marker = MARKER_PREVIEW if changed else MARKER_NOOP
    else:
        marker = MARKER_SUCCESS if changed else MARKER_NOOP
    terminal.status_line(
        marker,
        add_label(command.source, command.skill),
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
            dry_run_action="would update",
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
    version: bool = arg(False, help="Print the skeel version and exit.")
    subcommand: PathCommand | Diff | ListCommand | Apply | Add | Remove | Update | None = None

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
        if len(args) == 0:
            Skeel.print_help()
            return 0  # type: ignore[unreachable]
        if args == ["--version"]:
            print(__version__)
            return 0
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
