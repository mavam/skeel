from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from rich.console import Console, RenderableType
from rich.progress import Progress, ProgressColumn, Task, TaskID
from rich.spinner import Spinner
from rich.text import Text

Command = list[str]
StepExecutor = Callable[[], Awaitable["ProcessResult"]]
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
MARKER_CURRENT = OutputMarker("·", "bright_black")
MARKER_INSTALL = OutputMarker("+", "green")
MARKER_REMOVE = OutputMarker("-", "red")
MARKER_PREVIEW = OutputMarker("↳", "cyan")
MARKER_NOOP = OutputMarker("=", "bright_black")
MARKER_EMPTY = OutputMarker("∅", "bright_black")
SCOPE_USER = "⌂"
STYLE_REPO = "not bold cyan"
STYLE_SEPARATOR = "not bold bright_black"
STYLE_SKILL = "bold black"
STYLE_DETAIL = "not bold bright_black"
STYLE_NEW_VERSION = "not bold green"
STYLE_WARNING = "yellow bold"


@dataclass(frozen=True)
class ProcessResult:
    command: Command
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class StepOutcome:
    status: str | None = None
    detail: str | None = None


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
        if self.stdout:
            payload["stdout"] = self.stdout
        if self.stderr:
            payload["stderr"] = self.stderr
        return payload


class SkillStepLike(Protocol):
    @property
    def label(self) -> str: ...

    @property
    def command(self) -> Command: ...

    @property
    def remove_path(self) -> Path | None: ...

    @property
    def kind(self) -> str: ...

    @property
    def scope(self) -> str | None: ...

    @property
    def outcome(self) -> Callable[[ProcessResult], StepOutcome] | None: ...

    @property
    def executor(self) -> StepExecutor | None: ...

    @property
    def parallel(self) -> bool: ...


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


def scope_marker(scope: str | None) -> str | None:
    return SCOPE_USER if scope == "user" else None


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


def append_scope_text(text: Text, scope: str | None) -> None:
    marker = scope_marker(scope)
    if marker:
        text.append(" ", style=STYLE_DETAIL)
        text.append(marker, style=STYLE_DETAIL)


def label_text(label: str) -> Text:
    text = Text()
    if "@" not in label:
        text.append(label, style=STYLE_SKILL)
        return text

    source, skill = label.rsplit("@", 1)
    if skill == "*":
        text.append(source, style=STYLE_SKILL)
        return text

    text.append(skill, style=STYLE_SKILL)
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
        text = label_text(task.description)
        detail = task.fields.get("detail")
        scope = task.fields.get("scope")
        append_scope_text(text, scope if isinstance(scope, str) else None)
        extra = detail_text(detail if isinstance(detail, str) else None)
        if extra.plain:
            text.append(" ", style=STYLE_DETAIL)
            text.append_text(extra)
        return text


class ProcessRunner:
    async def run(
        self,
        command: Command,
        *,
        capture_output: bool = False,
    ) -> ProcessResult:
        pipe = asyncio.subprocess.PIPE
        stdout = pipe if capture_output else None
        stderr = pipe if capture_output else None
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=stdout,
            stderr=stderr,
        )

        stdout_bytes, stderr_bytes = await process.communicate()
        return ProcessResult(
            command=command,
            returncode=process.returncode or 0,
            stdout=(stdout_bytes or b"").decode(errors="replace"),
            stderr=(stderr_bytes or b"").decode(errors="replace"),
        )


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

    def warning(self, message: str) -> None:
        self.error_console.print(message, style=STYLE_WARNING)

    def failure_output(self, step: StepResult) -> None:
        output = (step.stderr or step.stdout).strip()
        if not output:
            return
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
        *,
        manifest_path: Path,
        warning: bool = False,
    ) -> None:
        if not missing and not extra:
            return

        if warning:
            self.warning(f"skills differ from {manifest_path}")

        for name, source, scope in missing:
            self.status_line(MARKER_INSTALL, f"{source or 'manual'}@{name}", scope=scope)
        for name, source, scope in extra:
            self.status_line(MARKER_REMOVE, f"{source or 'installed'}@{name}", scope=scope)

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
        text.append_text(label_text(label))
        append_scope_text(text, scope)
        extra = detail_text(detail)
        if extra.plain:
            text.append(" ", style=STYLE_DETAIL)
            text.append_text(extra)
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
        default_status: str | None = None,
        scope: str | None = None,
    ) -> StepResult:
        result = await executor() if executor else await runner.run(command, capture_output=True)
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
        )

    def execute_remove_step(
        self,
        label: str,
        command: Command,
        path: Path,
        *,
        scope: str | None = None,
    ) -> StepResult:
        returncode = self._remove_path(path)
        return StepResult(
            label=label,
            command=command,
            returncode=returncode,
            status="removed" if returncode == 0 else None,
            scope=scope,
        )

    def render_step_result(self, result: StepResult) -> None:
        marker, detail = self.step_result_marker(result)
        self.step_status_line(marker, result.label, detail=detail, scope=result.scope)

    def render_update_summary(self, results: Sequence[StepResult], *, verbose: bool) -> None:
        failed = [result for result in results if step_failed(result)]
        updated = sorted(
            (
                result
                for result in results
                if not step_failed(result) and result.status == "updated"
            ),
            key=lambda result: label_sort_key(result.label),
        )
        skipped = sorted(
            (
                result
                for result in results
                if not step_failed(result) and result.status == "skipped"
            ),
            key=lambda result: label_sort_key(result.label),
        )
        current = sorted(
            (
                result
                for result in results
                if not step_failed(result) and result.status == "current"
            ),
            key=lambda result: label_sort_key(result.label),
        )

        rows = updated + (current if verbose else []) + skipped
        for result in rows:
            marker, detail = self.step_result_marker(result)
            self.step_status_line(marker, result.label, detail=detail, scope=result.scope)
        if rows:
            self.error_console.print()

        summary = [
            (len(updated), "updated", MARKER_UPDATED.color),
            (len(skipped), "skipped", MARKER_SKIPPED.color),
            (len(failed), "failed", MARKER_FAILURE.color),
            (len(current), "current", MARKER_CURRENT.color),
        ]
        for count, label, style in summary:
            if count:
                self.error_console.print(f"{count} {label}", style=style)

    def step_result_marker(self, result: StepResult) -> tuple[OutputMarker, str | None]:
        if result.returncode not in (None, 0):
            return MARKER_FAILURE, None

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

    def _remove_path(self, path: Path) -> int:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        except OSError as error:
            self.error(str(error))
            return 1
        return 0


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
            scope=step.scope,
        )
    return runtime.terminal.dry_run_step(step.label, step.command, action=dry_run_action)


async def execute_skill_step(
    step: SkillStepLike,
    runtime: StepRuntime,
    *,
    default_status: str | None,
) -> StepResult:
    if step.remove_path is not None:
        return runtime.terminal.execute_remove_step(
            step.label,
            step.command,
            step.remove_path,
            scope=step.scope,
        )
    return await runtime.terminal.execute_step(
        step.label,
        step.command,
        runtime.runner,
        outcome=step.outcome,
        executor=step.executor,
        default_status=default_status,
        scope=step.scope,
    )


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
        task_id = progress.add_task(step.label, total=1, scope=step.scope or "")
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
                progress.add_task(step.label, total=1, scope=step.scope or "")
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
    while index < len(steps):
        step = steps[index]
        if dry_run:
            result = dry_run_step_result(step, runtime, dry_run_action=dry_run_action)
            results.append(result)
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
