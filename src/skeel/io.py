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
from typing import Literal

from rich.console import Console, RenderableType
from rich.progress import Progress, ProgressColumn, Task, TaskID
from rich.spinner import Spinner
from rich.text import Text

Command = list[str]
StepExecutor = Callable[[], Awaitable["ProcessResult"]]
TerminalColorSystem = Literal["standard"]


@dataclass(frozen=True)
class OutputMarker:
    icon: str
    color: str


MARKER_SUCCESS = OutputMarker("✔︎", "green")
MARKER_SKIPPED = OutputMarker("✔︎", "yellow")
MARKER_FAILURE = OutputMarker("✘", "red")
MARKER_INSTALL = OutputMarker("+", "green")
MARKER_REMOVE = OutputMarker("-", "red")
MARKER_PREVIEW = OutputMarker("↳", "cyan")
MARKER_NOOP = OutputMarker("=", "bright_black")
MARKER_EMPTY = OutputMarker("∅", "bright_black")
STYLE_REPO = "not bold cyan"
STYLE_SEPARATOR = "not bold bright_black"
STYLE_SKILL = "bold black"
STYLE_DETAIL = "not bold bright_black"
STYLE_OLD_VERSION = "not bold bright_black"
STYLE_VERSION_ARROW = "not bold bright_black"
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
        if self.stdout:
            payload["stdout"] = self.stdout
        if self.stderr:
            payload["stderr"] = self.stderr
        return payload


def quote_command(command: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def status_marker(status: str | None) -> OutputMarker | None:
    match status:
        case "installed":
            return MARKER_INSTALL
        case "removed":
            return MARKER_REMOVE
        case "current":
            return MARKER_SUCCESS
        case "skipped":
            return MARKER_SKIPPED
        case _:
            return None


def detail_text(detail: str) -> Text:
    text = Text()
    if " → " not in detail:
        text.append(detail, style=STYLE_DETAIL)
        return text

    _before, after = detail.split(" → ", 1)
    text.append(after, style=STYLE_NEW_VERSION)
    return text


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
        if isinstance(detail, str) and detail:
            text.append(" ", style=STYLE_DETAIL)
            text.append_text(detail_text(detail))
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
    ) -> None:
        self.line(self.status_text(marker, label, detail=detail))

    def step_status_line(
        self,
        marker: OutputMarker,
        label: str,
        *,
        detail: str | None = None,
    ) -> None:
        self.error_console.print(self.status_text(marker, label, detail=detail))

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
        missing: Sequence[tuple[str, str | None]],
        extra: Sequence[tuple[str, str | None]],
        *,
        manifest_path: Path,
        warning: bool = False,
    ) -> None:
        if not missing and not extra:
            return

        if warning:
            self.warning(f"skills differ from {manifest_path}")

        for name, source in missing:
            self.status_line(MARKER_INSTALL, f"{source or 'manual'}@{name}")
        for name, source in extra:
            self.status_line(MARKER_REMOVE, f"{source or 'installed'}@{name}")

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
    ) -> Text:
        text = Text(marker.icon, style=marker.color)
        text.append(" ")
        text.append_text(label_text(label))
        if detail:
            text.append(" ", style=STYLE_DETAIL)
            text.append_text(detail_text(detail))
        return text

    def live_progress_enabled(self) -> bool:
        return self.error_console.is_interactive

    def progress(self) -> Progress:
        return Progress(
            StepMarkerColumn(),
            StepDescriptionColumn(),
            console=self.error_console,
            transient=False,
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
            stdout=result.stdout if failed else "",
            stderr=result.stderr if failed else "",
        )

    def execute_remove_step(
        self,
        label: str,
        command: Command,
        path: Path,
    ) -> StepResult:
        returncode = self._remove_path(path)
        return StepResult(
            label=label,
            command=command,
            returncode=returncode,
            status="removed" if returncode == 0 else None,
        )

    def render_step_result(self, result: StepResult) -> None:
        marker, detail = self.step_result_marker(result)
        self.step_status_line(marker, result.label, detail=detail)

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
            refresh=True,
        )

    async def run_step(
        self,
        label: str,
        command: Command,
        runner: ProcessRunner,
        *,
        action: str,
        dry_run_action: str,
        done: str,
        dry_run: bool = False,
        outcome: Callable[[ProcessResult], StepOutcome] | None = None,
        executor: StepExecutor | None = None,
        default_status: str | None = None,
    ) -> StepResult:
        del action, done
        if dry_run:
            if self.json_output:
                return StepResult(label=label, command=command, returncode=None)
            return self.dry_run_step(label, command, action=dry_run_action)

        if self.json_output:
            return await self.execute_step(
                label,
                command,
                runner,
                outcome=outcome,
                executor=executor,
                default_status=default_status,
            )

        if not self.live_progress_enabled():
            result = await self.execute_step(
                label,
                command,
                runner,
                outcome=outcome,
                executor=executor,
                default_status=default_status,
            )
            self.render_step_result(result)
            return result

        with self.progress() as progress:
            task_id = progress.add_task(label, total=1)
            result = await self.execute_step(
                label,
                command,
                runner,
                outcome=outcome,
                executor=executor,
                default_status=default_status,
            )
            self.finish_progress_task(progress, task_id, result)
        return result

    async def remove_step(
        self,
        label: str,
        command: Command,
        path: Path,
        *,
        dry_run: bool = False,
    ) -> StepResult:
        if dry_run:
            if self.json_output:
                return StepResult(label=label, command=command, returncode=None, status="removed")
            return self.dry_run_step(label, command, action="would remove")

        if self.json_output:
            return self.execute_remove_step(label, command, path)

        if not self.live_progress_enabled():
            result = self.execute_remove_step(label, command, path)
            self.render_step_result(result)
            return result

        with self.progress() as progress:
            task_id = progress.add_task(label, total=1)
            result = self.execute_remove_step(label, command, path)
            self.finish_progress_task(progress, task_id, result)
        return result

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
