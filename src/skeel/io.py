from __future__ import annotations

import asyncio
import json
import shlex
import shutil
import sys
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import clypi
from clypi import Spinner

Command = list[str]
StatusMarker = tuple[str, clypi.ColorType]
StepExecutor = Callable[[], Awaitable["ProcessResult"]]


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


def status_marker(status: str | None) -> StatusMarker | None:
    match status:
        case "current":
            return "•", "bright_black"
        case "skipped":
            return "◦", "yellow"
        case _:
            return None


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

    def json(self, payload: object) -> None:
        clypi.cprint(json.dumps(payload, sort_keys=True))

    def line(self, message: str = "") -> None:
        clypi.cprint(message)

    def error(self, message: str) -> None:
        clypi.cprint(message, fg="red", file=sys.stderr)

    def success(self, message: str) -> None:
        clypi.cprint(f"{clypi.style('✔', fg='green')} {message}")

    def status_line(
        self,
        marker: str,
        label: str,
        *,
        color: clypi.ColorType,
        detail: str | None = None,
    ) -> None:
        self.line(f"{clypi.style(marker, fg=color)} {self.label_with_detail(label, detail)}")

    def warning(self, message: str) -> None:
        clypi.cprint(message, fg="yellow", bold=True, file=sys.stderr)

    def failure_output(self, step: StepResult) -> None:
        output = (step.stderr or step.stdout).strip()
        if not output:
            return
        for line in output.splitlines():
            clypi.cprint(f"  {line}", fg="bright_black", file=sys.stderr)

    def no_manifest(self, path: Path) -> None:
        self.line(f"• no manifest at {clypi.style(str(path), fg='bright_black')}")

    def command_block(self, command: Command) -> list[str]:
        command_line = clypi.style(quote_command(command), fg="bright_black")
        prefix = clypi.style("• ", fg="cyan")
        return clypi.indented([command_line], prefix=prefix)

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

        if missing:
            self.line(clypi.style("missing", fg="red", bold=True))
            grouped: dict[str, list[str]] = {}
            for name, source in missing:
                grouped.setdefault(source or "manual", []).append(name)
            for source, names in grouped.items():
                self.line(f"  {clypi.style(source, fg='bright_black')}")
                for name in names:
                    self.line(clypi.style(f"    - {name}", fg="red"))
        if extra:
            self.line(clypi.style("extra", fg="green", bold=True))
            grouped_extra: dict[str, list[str]] = {}
            for name, source in extra:
                grouped_extra.setdefault(source or "installed", []).append(name)
            for source, names in grouped_extra.items():
                self.line(f"  {clypi.style(source, fg='bright_black')}")
                for name in names:
                    self.line(clypi.style(f"    + {name}", fg="green"))

    def dry_run_step(self, label: str, command: Command, *, action: str) -> StepResult:
        del action
        for line in self.command_block(command):
            self.line(line)
        return StepResult(label=label, command=command, returncode=None)

    def label_with_detail(self, label: str, detail: str | None) -> str:
        if not detail:
            return label
        return f"{label} {clypi.style(detail, fg='bright_black')}"

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
    ) -> StepResult:
        del action, done
        if dry_run:
            if self.json_output:
                return StepResult(label=label, command=command, returncode=None)
            return self.dry_run_step(label, command, action=dry_run_action)

        step_status: str | None = None
        detail: str | None = None
        if self.json_output:
            result = (
                await executor() if executor else await runner.run(command, capture_output=True)
            )
            step_outcome = outcome(result) if result.returncode == 0 and outcome else StepOutcome()
            failed = result.returncode != 0
            return StepResult(
                label=label,
                command=command,
                returncode=result.returncode,
                status=step_outcome.status,
                detail=step_outcome.detail,
                stdout=result.stdout if failed else "",
                stderr=result.stderr if failed else "",
            )

        async with Spinner(label, suffix="", output="stderr") as spinner:
            result = (
                await executor() if executor else await runner.run(command, capture_output=True)
            )
            if result.returncode:
                await spinner.fail(label)
            else:
                step_outcome = outcome(result) if outcome else StepOutcome()
                step_status = step_outcome.status
                detail = step_outcome.detail
                marker = status_marker(step_status)
                message = self.label_with_detail(label, detail)
                if marker is None:
                    await spinner.done(message)
                else:
                    await self._finish_spinner(spinner, message, marker=marker)
        return StepResult(
            label=label,
            command=command,
            returncode=result.returncode,
            status=step_status,
            detail=detail,
            stdout=result.stdout if result.returncode else "",
            stderr=result.stderr if result.returncode else "",
        )

    async def _finish_spinner(
        self,
        spinner: Any,
        label: str,
        *,
        marker: StatusMarker,
    ) -> None:
        task = getattr(spinner, "_task", None)
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        if getattr(spinner, "_capture", False):
            spinner._stdout.stop()
            spinner._stderr.stop()

        spinner._manual_exit = True
        icon, color = marker
        spinner._print(label, icon=icon, color=color, end="\n")

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
            returncode = self._remove_path(path)
            return StepResult(
                label=label,
                command=command,
                returncode=returncode,
                status="removed" if returncode == 0 else None,
            )

        async with Spinner(label, suffix="", output="stderr") as spinner:
            returncode = self._remove_path(path)
            if returncode:
                await spinner.fail(label)
            else:
                await spinner.done(label)
        return StepResult(
            label=label,
            command=command,
            returncode=returncode,
            status="removed" if returncode == 0 else None,
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
