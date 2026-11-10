from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import stat
import sys
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, Protocol

from rich.console import Console, RenderableType
from rich.progress import Progress, ProgressColumn, Task, TaskID
from rich.spinner import Spinner
from rich.text import Text

from .targets import SkillTarget

Command = list[str]
StepExecutor = Callable[[], Awaitable["ProcessResult"]]
StepPostprocessor = Callable[["ProcessResult"], "ProcessResult"]
TerminalColorSystem = Literal["standard"]
DEFAULT_PARALLELISM = 32


@dataclass(frozen=True)
class OutputMarker:
    icon: str
    color: str


MARKER_SUCCESS = OutputMarker("✔︎", "green")
MARKER_SKIPPED = OutputMarker("!", "yellow")
MARKER_FAILURE = OutputMarker("✘", "red")
MARKER_UPDATED = OutputMarker("↑", "green")
MARKER_CURRENT = OutputMarker("=", "bright_black")
MARKER_INSTALL = OutputMarker("+", "green")
MARKER_REMOVE = OutputMarker("-", "red")
MARKER_PREVIEW = OutputMarker("↳", "cyan")
MARKER_NOOP = OutputMarker("=", "bright_black")
MARKER_EMPTY = OutputMarker("∅", "bright_black")
SCOPE_USER = "⌂"
SCOPE_PROJECT = "★"
STYLE_REPO = "not bold cyan"
STYLE_SEPARATOR = "not bold bright_black"
STYLE_SKILL = "bold default"
STYLE_DETAIL = "not bold bright_black"
STYLE_TARGET = "not bold dim default"
STYLE_NEW_VERSION = "not bold green"
STYLE_WARNING = "yellow bold"


@dataclass(frozen=True)
class ProcessResult:
    command: Command
    returncode: int
    stdout: str = ""
    stderr: str = ""
    removed_paths: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class StepOutcome:
    status: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class RemovalGuard:
    root: Path
    relative_path: Path
    root_device: int
    root_inode: int
    skill_device: int | None = None
    skill_inode: int | None = None
    skill_symlink_target: str | None = None


@dataclass(frozen=True)
class StepResult:
    label: str
    command: Command
    returncode: int | None
    status: str | None = None
    detail: str | None = None
    scope: str | None = None
    stdout: str = ""
    stderr: str = ""
    removed_paths: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()
    target: SkillTarget | None = None

    def json(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "label": self.label,
            "command": self.command,
            "shell": quote_command(self.command),
            "returncode": self.returncode,
        }
        if self.status is not None:
            payload["status"] = self.status
        if self.detail is not None:
            payload["detail"] = self.detail
        if self.scope is not None:
            payload["scope"] = self.scope
        if self.target is not None:
            payload["directory"] = str(self.target.directory)
            if self.target.agent is not None:
                payload["agent"] = self.target.agent
        if self.stdout:
            payload["stdout"] = self.stdout
        if self.stderr:
            payload["stderr"] = self.stderr
        if self.removed_paths:
            payload["removed"] = [str(path) for path in self.removed_paths]
        if self.warnings:
            payload["warnings"] = list(self.warnings)
        return payload


class SkillStepLike(Protocol):
    @property
    def label(self) -> str: ...

    @property
    def command(self) -> Command: ...

    @property
    def remove_path(self) -> Path | None: ...

    @property
    def removal_guard(self) -> RemovalGuard | None: ...

    @property
    def kind(self) -> str: ...

    @property
    def scope(self) -> str | None: ...

    @property
    def outcome(self) -> Callable[[ProcessResult], StepOutcome] | None: ...

    @property
    def executor(self) -> StepExecutor | None: ...

    @property
    def postprocess(self) -> StepPostprocessor | None: ...

    @property
    def preview_detail(self) -> str | None: ...

    @property
    def parallel(self) -> bool: ...

    @property
    def target(self) -> SkillTarget | None: ...


class StepRuntime(Protocol):
    @property
    def runner(self) -> ProcessRunner: ...

    @property
    def terminal(self) -> Terminal: ...


def quote_command(command: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def status_marker(status: str | None) -> OutputMarker | None:
    match status:
        case "installed":
            return MARKER_INSTALL
        case "removed":
            return MARKER_REMOVE
        case "current":
            return MARKER_CURRENT
        case "updated":
            return MARKER_UPDATED
        case "skipped":
            return MARKER_SKIPPED
        case _:
            return None


def scope_glyph(scope: str | None) -> str | None:
    match scope:
        case "user":
            return SCOPE_USER
        case "project":
            return SCOPE_PROJECT
        case _:
            return None


def detail_text(detail: str | None) -> Text:
    text = Text()
    if detail:
        if " → " in detail:
            before, after = detail.split(" → ", 1)
            text.append(before, style=STYLE_DETAIL)
            text.append(" → ", style=STYLE_DETAIL)
            text.append(after, style=STYLE_NEW_VERSION)
        else:
            text.append(detail, style=STYLE_DETAIL)
    return text


def scoped_label_text(
    label: str,
    *,
    scope: str | None = None,
    detail: str | None = None,
) -> Text:
    """Render a muted scope glyph (when scoped), the label, and an optional detail."""
    text = Text()
    glyph = scope_glyph(scope)
    if glyph:
        text.append(glyph, style=STYLE_DETAIL)
        text.append(" ")
    text.append_text(label_text(label))
    extra = detail_text(detail)
    if extra.plain:
        text.append(" ", style=STYLE_DETAIL)
        text.append_text(extra)
    return text


def display_directory(directory: Path) -> str:
    try:
        directory = Path("~") / directory.relative_to(Path.home())
    except ValueError:
        pass
    return str(directory)


def target_label(target: SkillTarget) -> str:
    return f"{target.agent or 'custom'}  {display_directory(target.directory)}"


def target_names(targets: Sequence[SkillTarget]) -> dict[SkillTarget, str]:
    """Use short agent names unless distinct directories make them ambiguous."""
    counts = Counter(target.agent or "custom" for target in targets)
    return {
        target: (
            target.agent or "custom"
            if counts[target.agent or "custom"] == 1
            else display_directory(target.directory)
        )
        for target in targets
    }


def append_targets(text: Text, names: Sequence[str]) -> None:
    if names:
        text.append("  ")
        text.append(", ".join(dict.fromkeys(names)), style=STYLE_TARGET)


def print_columns(console: Console, rows: Sequence[Sequence[Text]]) -> None:
    """Align separate fields, stacking secondary fields when they won't fit."""
    if not rows:
        return
    columns = [index for index in range(len(rows[0])) if any(row[index].plain for row in rows)]
    widths = [max(row[index].cell_len for row in rows) for index in columns]
    fits = sum(widths) + 2 * (len(columns) - 1) <= console.width
    for row in rows:
        cells = [row[index] for index in columns]
        if not fits:
            console.print(cells[0])
            secondary = [cell for cell in cells[1:] if cell.plain]
            if secondary:
                console.print(Text("  ") + Text("  ").join(secondary))
            continue
        text = Text()
        last = max(index for index, cell in enumerate(cells) if cell.plain)
        for index, cell in enumerate(cells[: last + 1]):
            text.append_text(cell)
            if index < last:
                text.append(" " * (widths[index] - cell.cell_len + 2))
        console.print(text)


def pinned_result(result: StepResult) -> bool:
    return result.status == "skipped" and (result.detail or "").partition(" ")[0] == "pinned"


def collapse_update_rows(results: Sequence[StepResult]) -> list[list[StepResult]]:
    """Merge identical successful outcomes across targets, never distinct diagnostics."""
    rows: list[list[StepResult]] = []
    matching: dict[tuple[str, str | None, str | None, str | None], list[StepResult]] = {}
    for result in results:
        mergeable = (
            result.returncode == 0
            and result.target is not None
            and not result.warnings
            and not result.removed_paths
        )
        key = (result.label, result.scope, result.status, result.detail)
        group = matching.get(key) if mergeable else None
        if group is not None and all(other.target != result.target for other in group):
            group.append(result)
        else:
            group = [result]
            rows.append(group)
            if mergeable:
                matching[key] = group
    return rows


def label_parts(label: str) -> tuple[str, str]:
    if "@" not in label:
        return label, ""
    source, skill = label.rsplit("@", 1)
    return (source, "") if skill == "*" else (skill, source)


def label_text(label: str) -> Text:
    skill, source = label_parts(label)
    text = Text(skill, style=STYLE_SKILL)
    if source:
        text.append(" ", style=STYLE_SEPARATOR)
        text.append(source, style=STYLE_REPO)
    return text


def label_sort_key(label: str) -> str:
    return label_text(label).plain


class StepMarkerColumn(ProgressColumn):
    def __init__(self) -> None:
        super().__init__()
        self.spinner = Spinner("dots", style="blue")

    def render(self, task: Task) -> RenderableType:
        marker = task.fields.get("marker")
        if marker is not None:
            return Text(str(marker), style=str(task.fields.get("marker_style") or ""))
        return self.spinner.render(task.get_time())


class StepDescriptionColumn(ProgressColumn):
    def render(self, task: Task) -> RenderableType:
        detail = task.fields.get("detail")
        scope = task.fields.get("scope")
        text = scoped_label_text(
            task.description,
            scope=scope if isinstance(scope, str) else None,
            detail=detail if isinstance(detail, str) else None,
        )
        target = task.fields.get("target")
        if isinstance(target, SkillTarget):
            append_targets(text, [target_label(target)])
        return text


class ProcessRunner:
    async def run(
        self,
        command: Command,
        *,
        capture_output: bool = False,
        env: Mapping[str, str] | None = None,
    ) -> ProcessResult:
        pipe = asyncio.subprocess.PIPE
        stdout = pipe if capture_output else None
        stderr = pipe if capture_output else None
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=stdout,
            stderr=stderr,
            env={**os.environ, **env} if env is not None else None,
        )

        try:
            stdout_bytes, stderr_bytes = await process.communicate()
        except asyncio.CancelledError:
            await terminate_process(process)
            raise
        return ProcessResult(
            command=command,
            returncode=process.returncode or 0,
            stdout=(stdout_bytes or b"").decode(errors="replace"),
            stderr=(stderr_bytes or b"").decode(errors="replace"),
        )


async def terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return

    try:
        process.terminate()
    except ProcessLookupError:
        return

    try:
        await asyncio.wait_for(process.wait(), timeout=2)
    except TimeoutError:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                return
        await process.wait()


class Terminal:
    def __init__(self, *, json_output: bool = False) -> None:
        self.json_output = json_output
        no_color = os.environ.get("NO_COLOR") is not None
        stdout_color_system: TerminalColorSystem | None = (
            "standard" if sys.stdout.isatty() and not no_color else None
        )
        stderr_color_system: TerminalColorSystem | None = (
            "standard" if sys.stderr.isatty() and not no_color else None
        )
        self.console = Console(
            file=sys.stdout,
            color_system=stdout_color_system,
            no_color=no_color,
            highlight=False,
            markup=False,
        )
        self.error_console = Console(
            stderr=True,
            color_system=stderr_color_system,
            no_color=no_color,
            highlight=False,
            markup=False,
        )

    def json(self, payload: object) -> None:
        sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
        sys.stdout.flush()

    def line(self, message: str | Text = "") -> None:
        self.console.print(message)

    def error(self, message: str) -> None:
        self.error_console.print(message, style=MARKER_FAILURE.color)

    def success(self, message: str) -> None:
        text = self.status_text(MARKER_SUCCESS, message)
        self.line(text)

    def status_line(
        self,
        marker: OutputMarker,
        label: str,
        *,
        detail: str | None = None,
        scope: str | None = None,
    ) -> None:
        self.line(self.status_text(marker, label, detail=detail, scope=scope))

    def step_status_line(
        self,
        marker: OutputMarker,
        label: str,
        *,
        detail: str | None = None,
        scope: str | None = None,
    ) -> None:
        self.error_console.print(self.status_text(marker, label, detail=detail, scope=scope))

    def warning(self, message: str | Text) -> None:
        self.error_console.print(message, style=STYLE_WARNING)

    def failure_output(self, step: StepResult) -> None:
        output = (step.stderr or step.stdout).strip()
        if not output:
            return
        if step.target is not None:
            self.error_console.print(f"  {target_label(step.target)}", style=STYLE_TARGET)
        for line in output.splitlines():
            self.error_console.print(f"  {line}", style=STYLE_DETAIL)

    def no_manifest(self, path: Path) -> None:
        text = Text(MARKER_EMPTY.icon, style=MARKER_EMPTY.color)
        text.append(" no manifest at")
        text.append(" ")
        text.append(str(path), style=STYLE_DETAIL)
        self.line(text)

    def command_block(self, command: Command) -> list[Text]:
        text = Text(MARKER_PREVIEW.icon, style=MARKER_PREVIEW.color)
        text.append(" ")
        text.append(quote_command(command), style=STYLE_DETAIL)
        return [text]

    def diff(
        self,
        missing: Sequence[tuple[str, str | None, str | None]],
        extra: Sequence[tuple[str, str | None, str | None]],
        changed: Sequence[tuple[str, str | None, str | None, str]],
        *,
        manifest_path: Path,
        warning: bool = False,
    ) -> None:
        if not missing and not extra and not changed:
            return

        if warning:
            self.warning(f"skills differ from {manifest_path}")

        for name, source, scope in missing:
            self.status_line(MARKER_INSTALL, f"{source or 'manual'}@{name}", scope=scope)
        for name, source, scope in extra:
            self.status_line(MARKER_REMOVE, f"{source or 'installed'}@{name}", scope=scope)
        for name, source, scope, detail in changed:
            self.status_line(
                MARKER_UPDATED,
                f"{source or 'manual'}@{name}",
                detail=detail,
                scope=scope,
            )

    def dry_run_step(self, label: str, command: Command, *, action: str) -> StepResult:
        del action
        for line in self.command_block(command):
            self.line(line)
        return StepResult(label=label, command=command, returncode=None)

    def status_text(
        self,
        marker: OutputMarker,
        label: str,
        *,
        detail: str | None = None,
        scope: str | None = None,
    ) -> Text:
        text = Text(marker.icon, style=marker.color)
        text.append(" ")
        text.append_text(scoped_label_text(label, scope=scope, detail=detail))
        return text

    def live_progress_enabled(self) -> bool:
        return self.error_console.is_interactive

    def progress(self, *, transient: bool = False) -> Progress:
        return Progress(
            StepMarkerColumn(),
            StepDescriptionColumn(),
            console=self.error_console,
            transient=transient,
            redirect_stdout=False,
            redirect_stderr=False,
            disable=not self.live_progress_enabled(),
        )

    async def execute_step(
        self,
        label: str,
        command: Command,
        runner: ProcessRunner,
        *,
        outcome: Callable[[ProcessResult], StepOutcome] | None = None,
        executor: StepExecutor | None = None,
        postprocess: StepPostprocessor | None = None,
        default_status: str | None = None,
        scope: str | None = None,
    ) -> StepResult:
        result = await executor() if executor else await runner.run(command, capture_output=True)
        if result.returncode == 0 and postprocess is not None:
            result = postprocess(result)
        failed = result.returncode != 0
        step_outcome = outcome(result) if not failed and outcome else StepOutcome()
        return StepResult(
            label=label,
            command=command,
            returncode=result.returncode,
            status=step_outcome.status or (default_status if not failed else None),
            detail=step_outcome.detail,
            scope=scope,
            stdout=result.stdout if failed else "",
            stderr=result.stderr if failed else "",
            removed_paths=result.removed_paths,
            warnings=result.warnings,
        )

    def execute_remove_step(
        self,
        label: str,
        command: Command,
        path: Path,
        guard: RemovalGuard,
        *,
        scope: str | None = None,
    ) -> StepResult:
        returncode = self._remove_path(path, guard)
        return StepResult(
            label=label,
            command=command,
            returncode=returncode,
            status="removed" if returncode == 0 else None,
            scope=scope,
        )

    def render_step_result(self, result: StepResult) -> None:
        marker, detail = self.step_result_marker(result)
        text = self.status_text(marker, result.label, detail=detail, scope=result.scope)
        if result.target is not None:
            append_targets(text, [target_label(result.target)])
        self.error_console.print(text)
        for warning in result.warnings:
            self.warning(warning)

    def render_update_summary(self, results: Sequence[StepResult], *, verbose: bool) -> None:
        targets = list(dict.fromkeys(result.target for result in results if result.target))
        names = target_names(targets) if len(targets) > 1 else {}
        if names:
            legend = []
            for target, name in names.items():
                directory = display_directory(target.directory)
                legend.append(
                    (
                        Text(name, style=STYLE_TARGET),
                        Text(directory if name != directory else "", style=STYLE_TARGET),
                    )
                )
            print_columns(self.error_console, legend)
            self.error_console.print()

        failed: list[StepResult] = []
        by_status: dict[str, list[StepResult]] = {
            "updated": [],
            "skipped": [],
            "current": [],
        }
        for result in results:
            if step_failed(result):
                failed.append(result)
                continue
            status = result.status
            if status is not None and status in by_status:
                by_status[status].append(result)

        for bucket in by_status.values():
            bucket.sort(key=lambda result: label_sort_key(result.label))
        updated = by_status["updated"]
        skipped = by_status["skipped"]
        current = by_status["current"]

        rows = updated + (current if verbose else []) + skipped + failed
        groups = collapse_update_rows(rows) if names else [[result] for result in rows]
        rendered: list[tuple[Text, Text, Text, Text]] = []
        for group in groups:
            result = group[0]
            marker, detail = self.step_result_marker(result)
            skill, source = label_parts(result.label)
            text = Text(marker.icon, style=marker.color)
            text.append(" ")
            if glyph := scope_glyph(result.scope):
                text.append(f"{glyph} ", style=STYLE_DETAIL)
            text.append(skill, style=STYLE_SKILL)
            labels = [names[item.target] for item in group if item.target in names]
            status_cell = detail_text(detail)
            if step_failed(result):
                status_cell = Text("failed", style=MARKER_FAILURE.color)
            elif not status_cell.plain:
                status_cell = Text(result.status or "", style=marker.color)
            rendered.append(
                (
                    text,
                    Text(source, style=STYLE_REPO),
                    status_cell,
                    Text(", ".join(dict.fromkeys(labels)), style=STYLE_TARGET),
                )
            )
        print_columns(self.error_console, rendered)
        if rows:
            self.error_console.print()

        pinned = sum(pinned_result(result) for result in skipped)
        summary = [
            (len(failed), "failed", MARKER_FAILURE.color),
            (len(updated), "updated", MARKER_UPDATED.color),
            (len(current), "current", MARKER_CURRENT.color),
            (pinned, "pinned", MARKER_NOOP.color),
            (len(skipped) - pinned, "skipped", MARKER_SKIPPED.color),
        ]
        counts = [Text(f"{count} {label}", style=style) for count, label, style in summary if count]
        if counts:
            text = Text(style=STYLE_DETAIL)
            if names:
                text.append(f"{len(results)} operations across {len(targets)} targets: ")
            text.append_text(Text(", ", style=STYLE_DETAIL).join(counts))
            self.error_console.print(text)
        warnings: dict[str, list[str]] = {}
        for result in results:
            for warning in result.warnings:
                labels = warnings.setdefault(warning, [])
                if result.target in names:
                    labels.append(names[result.target])
        for warning, labels in warnings.items():
            text = Text(warning, style=STYLE_WARNING)
            append_targets(text, labels)
            self.warning(text)

    def step_result_marker(self, result: StepResult) -> tuple[OutputMarker, str | None]:
        if result.returncode not in (None, 0):
            return MARKER_FAILURE, None

        if pinned_result(result):
            return MARKER_NOOP, result.detail
        marker = status_marker(result.status)
        if marker is None:
            return MARKER_SUCCESS, result.detail

        return marker, result.detail

    def finish_progress_task(
        self,
        progress: Progress,
        task_id: TaskID,
        result: StepResult,
    ) -> None:
        marker, detail = self.step_result_marker(result)
        progress.update(
            task_id,
            completed=1,
            marker=marker.icon,
            marker_style=marker.color,
            detail=detail or "",
            scope=result.scope or "",
            refresh=True,
        )

    def _remove_path(self, path: Path, guard: RemovalGuard) -> int:
        try:
            remove_guarded_directory(path, guard)
        except (OSError, ValueError) as error:
            self.error(str(error))
            return 1
        return 0


def build_removal_guard(root: Path, path: Path) -> RemovalGuard:
    """Validate a planned skill removal and capture filesystem identities."""
    canonical_root = root.resolve()
    canonical_path = path.parent.resolve() / path.name
    if canonical_path == canonical_root or not canonical_path.is_relative_to(canonical_root):
        raise ValueError(f"refusing to remove skill outside target directory: {path}")

    skill_identity: tuple[int, int] | None = None
    skill_symlink_target = os.readlink(path) if path.is_symlink() else None
    if path.exists() or skill_symlink_target is not None:
        if path.exists() and not (path / "SKILL.md").is_file():
            raise ValueError(f"refusing to remove directory without SKILL.md: {path}")
        skill_stat = path.stat(follow_symlinks=False)
        skill_identity = (skill_stat.st_dev, skill_stat.st_ino)

    root_stat = canonical_root.stat()
    return RemovalGuard(
        root=canonical_root,
        relative_path=canonical_path.relative_to(canonical_root),
        root_device=root_stat.st_dev,
        root_inode=root_stat.st_ino,
        skill_device=skill_identity[0] if skill_identity is not None else None,
        skill_inode=skill_identity[1] if skill_identity is not None else None,
        skill_symlink_target=skill_symlink_target,
    )


def move_guarded_directory(path: Path, destination: Path, guard: RemovalGuard) -> None:
    """Move a validated skill within its unchanged target directory."""
    relative = guard.relative_path
    if relative.is_absolute() or relative == Path(".") or ".." in relative.parts:
        raise ValueError(f"refusing to move invalid relative skill path: {path}")
    if destination.parent.resolve() != guard.root:
        raise ValueError(f"refusing to move skill outside target directory: {destination}")
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise OSError("safe target directory opening is unavailable on this platform")

    root_lstat = os.lstat(guard.root)
    if stat.S_ISLNK(root_lstat.st_mode):
        raise ValueError(f"refusing to move through symlinked target: {guard.root}")

    root_fd = os.open(guard.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        root_stat = os.fstat(root_fd)
        if (root_stat.st_dev, root_stat.st_ino) != (guard.root_device, guard.root_inode):
            raise ValueError(f"refusing to move through replaced target: {guard.root}")
        skill_stat = os.stat(relative, dir_fd=root_fd, follow_symlinks=False)
        if (skill_stat.st_dev, skill_stat.st_ino) != (
            guard.skill_device,
            guard.skill_inode,
        ):
            raise ValueError(f"refusing to move replaced skill: {path}")
        if not stat.S_ISDIR(skill_stat.st_mode) or guard.skill_symlink_target is not None:
            raise ValueError(f"refusing to move non-directory skill: {path}")
        metadata_stat = os.stat(relative / "SKILL.md", dir_fd=root_fd, follow_symlinks=False)
        if not stat.S_ISREG(metadata_stat.st_mode):
            raise ValueError(f"refusing to move directory without regular SKILL.md: {path}")
        try:
            os.stat(destination.name, dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError(f"refusing to replace existing skill: {destination}")
        os.rename(relative, destination.name, src_dir_fd=root_fd, dst_dir_fd=root_fd)
    finally:
        os.close(root_fd)


def remove_guarded_directory(path: Path, guard: RemovalGuard) -> None:
    """Remove a validated skill relative to its unchanged target directory."""
    relative = guard.relative_path
    if relative.is_absolute() or relative == Path(".") or ".." in relative.parts:
        raise ValueError(f"refusing to remove invalid relative skill path: {path}")
    if not shutil.rmtree.avoids_symlink_attacks:
        raise OSError("safe directory removal is unavailable on this platform")
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise OSError("safe target directory opening is unavailable on this platform")

    root_lstat = os.lstat(guard.root)
    if stat.S_ISLNK(root_lstat.st_mode):
        raise ValueError(f"refusing to remove through symlinked target: {guard.root}")

    root_fd = os.open(guard.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        root_stat = os.fstat(root_fd)
        if (root_stat.st_dev, root_stat.st_ino) != (guard.root_device, guard.root_inode):
            raise ValueError(f"refusing to remove through replaced target: {guard.root}")
        if not stat.S_ISDIR(root_stat.st_mode):
            raise ValueError(f"refusing to remove through non-directory target: {guard.root}")

        try:
            skill_stat = os.stat(relative, dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            if guard.skill_device is None and guard.skill_inode is None:
                return
            raise
        if guard.skill_device is None or guard.skill_inode is None:
            raise ValueError(f"refusing to remove skill that appeared after planning: {path}")
        if (skill_stat.st_dev, skill_stat.st_ino) != (guard.skill_device, guard.skill_inode):
            raise ValueError(f"refusing to remove replaced skill: {path}")
        if guard.skill_symlink_target is not None:
            if not stat.S_ISLNK(skill_stat.st_mode) or os.readlink(relative, dir_fd=root_fd) != (
                guard.skill_symlink_target
            ):
                raise ValueError(f"refusing to remove replaced symlinked skill: {path}")
            os.unlink(relative, dir_fd=root_fd)
            return
        if not stat.S_ISDIR(skill_stat.st_mode):
            raise ValueError(f"refusing to remove non-directory skill: {path}")
        metadata_stat = os.stat(
            relative / "SKILL.md",
            dir_fd=root_fd,
            follow_symlinks=False,
        )
        if not stat.S_ISREG(metadata_stat.st_mode):
            raise ValueError(f"refusing to remove directory without regular SKILL.md: {path}")

        shutil.rmtree(relative, dir_fd=root_fd)
    finally:
        os.close(root_fd)


def failed_steps(steps: Sequence[StepResult]) -> list[StepResult]:
    return [step for step in steps if step.returncode not in (None, 0)]


def step_failed(result: StepResult) -> bool:
    return result.returncode not in (None, 0)


def first_failure_code(results: Sequence[StepResult]) -> int:
    for result in results:
        if step_failed(result):
            assert result.returncode is not None
            return result.returncode
    return 0


def can_run_step_in_parallel(step: SkillStepLike) -> bool:
    return step.parallel and step.kind == "command" and step.remove_path is None


def dry_run_step_result(
    step: SkillStepLike,
    runtime: StepRuntime,
    *,
    dry_run_action: str,
) -> StepResult:
    if step.kind == "frontmatter":
        if not runtime.terminal.json_output:
            runtime.terminal.status_line(
                MARKER_PREVIEW,
                step.label,
                detail=step.preview_detail,
                scope=step.scope,
            )
        return StepResult(
            label=step.label,
            command=[],
            returncode=None,
            status="updated",
            detail=step.preview_detail,
            scope=step.scope,
        )
    if step.remove_path is not None:
        if runtime.terminal.json_output:
            return StepResult(
                label=step.label,
                command=step.command,
                returncode=None,
                status="removed",
                scope=step.scope,
            )
        return runtime.terminal.dry_run_step(step.label, step.command, action="would remove")

    if runtime.terminal.json_output:
        return StepResult(
            label=step.label,
            command=step.command,
            returncode=None,
            detail=step.preview_detail,
            scope=step.scope,
        )
    result = runtime.terminal.dry_run_step(step.label, step.command, action=dry_run_action)
    if step.preview_detail:
        runtime.terminal.line(f"  {step.preview_detail}")
    return result


async def execute_skill_step(
    step: SkillStepLike,
    runtime: StepRuntime,
    *,
    default_status: str | None,
) -> StepResult:
    if step.remove_path is not None:
        if step.removal_guard is None:
            raise ValueError(f"remove step lacks execution guard: {step.remove_path}")
        result = runtime.terminal.execute_remove_step(
            step.label,
            step.command,
            step.remove_path,
            step.removal_guard,
            scope=step.scope,
        )
    else:
        result = await runtime.terminal.execute_step(
            step.label,
            step.command,
            runtime.runner,
            outcome=step.outcome,
            executor=step.executor,
            postprocess=step.postprocess,
            default_status=default_status,
            scope=step.scope,
        )
    return replace(result, target=step.target)


async def run_serial_step(
    step: SkillStepLike,
    runtime: StepRuntime,
    *,
    default_status: str | None,
    render: bool = True,
    remove_current_progress_tasks: bool = False,
) -> StepResult:
    if runtime.terminal.json_output:
        return await execute_skill_step(step, runtime, default_status=default_status)

    if not runtime.terminal.live_progress_enabled():
        result = await execute_skill_step(step, runtime, default_status=default_status)
        if render:
            runtime.terminal.render_step_result(result)
        return result

    with runtime.terminal.progress(transient=True) as progress:
        task_id = progress.add_task(step.label, total=1, scope=step.scope or "", target=step.target)
        result = await execute_skill_step(step, runtime, default_status=default_status)
        runtime.terminal.finish_progress_task(progress, task_id, result)
        if should_remove_progress_task(
            result,
            remove_current_progress_tasks=remove_current_progress_tasks,
        ):
            progress.remove_task(task_id)
    if render:
        runtime.terminal.render_step_result(result)
    return result


async def run_parallel_step_group(
    steps: Sequence[SkillStepLike],
    runtime: StepRuntime,
    *,
    default_status: str | None,
    keep_going: bool,
    render: bool = True,
    remove_current_progress_tasks: bool = False,
) -> tuple[list[StepResult], int]:
    results: list[StepResult | None] = [None] * len(steps)
    next_index = 0
    index_lock = asyncio.Lock()
    stop_launching = asyncio.Event()
    progress = (
        runtime.terminal.progress(transient=True)
        if not runtime.terminal.json_output and runtime.terminal.live_progress_enabled()
        else None
    )

    async def next_step() -> tuple[int, SkillStepLike] | None:
        nonlocal next_index
        async with index_lock:
            if stop_launching.is_set() and not keep_going:
                return None
            if next_index >= len(steps):
                return None
            index = next_index
            next_index += 1
            return index, steps[index]

    async def worker() -> None:
        while work := await next_step():
            index, step = work
            task_id = (
                progress.add_task(step.label, total=1, scope=step.scope or "", target=step.target)
                if progress is not None
                else None
            )
            result = await execute_skill_step(step, runtime, default_status=default_status)
            results[index] = result
            if progress is not None and task_id is not None:
                runtime.terminal.finish_progress_task(progress, task_id, result)
                if should_remove_progress_task(
                    result,
                    remove_current_progress_tasks=remove_current_progress_tasks,
                ):
                    progress.remove_task(task_id)
            if step_failed(result) and not keep_going:
                stop_launching.set()

    async def run_workers() -> None:
        worker_count = min(DEFAULT_PARALLELISM, len(steps))
        await asyncio.gather(*(worker() for _ in range(worker_count)))

    if progress is None:
        await run_workers()
    else:
        with progress:
            await run_workers()

    ordered_results = [result for result in results if result is not None]
    if not runtime.terminal.json_output and render:
        for result in ordered_results:
            runtime.terminal.render_step_result(result)
    return ordered_results, first_failure_code(ordered_results)


def should_remove_progress_task(
    result: StepResult,
    *,
    remove_current_progress_tasks: bool,
) -> bool:
    return remove_current_progress_tasks and not step_failed(result) and result.status == "current"


async def run_steps(
    steps: Sequence[SkillStepLike],
    runtime: StepRuntime,
    *,
    dry_run: bool,
    dry_run_action: str,
    default_status: str | None = None,
    keep_going: bool = False,
    render: bool = True,
    remove_current_progress_tasks: bool = False,
) -> tuple[list[StepResult], int]:
    results: list[StepResult] = []
    exit_code = 0
    index = 0
    multiple_targets = len({step.target for step in steps}) > 1
    while index < len(steps):
        step = steps[index]
        if dry_run:
            if (
                multiple_targets
                and not runtime.terminal.json_output
                and step.target is not None
                and (index == 0 or steps[index - 1].target != step.target)
            ):
                runtime.terminal.line(Text(target_label(step.target), style="bold"))
            result = dry_run_step_result(step, runtime, dry_run_action=dry_run_action)
            results.append(replace(result, scope=step.scope, target=step.target))
            index += 1
            continue

        if can_run_step_in_parallel(step):
            end = index + 1
            while end < len(steps) and can_run_step_in_parallel(steps[end]):
                end += 1
            group_results, group_exit_code = await run_parallel_step_group(
                steps[index:end],
                runtime,
                default_status=default_status,
                keep_going=keep_going,
                render=render,
                remove_current_progress_tasks=remove_current_progress_tasks,
            )
            results.extend(group_results)
            if group_exit_code and not exit_code:
                exit_code = group_exit_code
            if group_exit_code and not keep_going:
                break
            index = end
            continue

        result = await run_serial_step(
            step,
            runtime,
            default_status=default_status,
            render=render,
            remove_current_progress_tasks=remove_current_progress_tasks,
        )
        results.append(result)
        index += 1
        if step_failed(result):
            assert result.returncode is not None
            if not exit_code:
                exit_code = result.returncode
            if not keep_going:
                break
    return results, exit_code
