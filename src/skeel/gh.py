from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from .fast_install import (
    FastInstallError,
    FastInstallSession,
    fast_install_command,
    supports_fast_install,
)
from .io import Command, ProcessResult, ProcessRunner, StepExecutor, StepOutcome
from .manifest import DesiredSkill, Manifest, SkillSpec, SourceSpec

OutcomeFactory = Callable[[ProcessResult], StepOutcome]
MIN_GH_VERSION = (2, 94, 0)


@dataclass(frozen=True)
class SkillProvenance:
    repo_url: str = ""
    ref: str = ""
    path: str = ""
    tree_sha: str = ""

    @property
    def source(self) -> str:
        return github_source(self.repo_url)

    @property
    def version_label(self) -> str:
        ref = short_ref(self.ref)
        sha = short_sha(self.tree_sha)
        if ref and sha:
            return f"{ref}@{sha}"
        return ref or sha


@dataclass(frozen=True)
class SkillStep:
    label: str
    command: Command
    remove_path: Path | None = None
    kind: Literal["command", "remove"] = "command"
    outcome: OutcomeFactory | None = None
    executor: StepExecutor | None = None
    parallel: bool = True


@dataclass(frozen=True)
class InstalledSkill:
    name: str
    path: Path
    source_url: str = ""
    version: str = ""
    pinned: bool = False
    provenance: SkillProvenance = field(default_factory=SkillProvenance)

    @property
    def basename(self) -> str:
        return Path(self.name).name

    @property
    def update_name(self) -> str:
        return self.path.name or self.basename

    @property
    def github_source(self) -> str:
        return self.provenance.source or github_source(self.source_url)

    @property
    def label(self) -> str:
        if self.github_source:
            return source_skill_label(self.github_source, self.basename)
        return self.name

    @property
    def version_label(self) -> str:
        return self.provenance.version_label or self.version


@dataclass(frozen=True)
class GhOptions:
    directory: Path


def manual_install_steps(source: SourceSpec) -> list[SkillStep]:
    return [
        SkillStep(label=source.source, command=list(command), parallel=False)
        for command in source.install
    ]


def source_skill_label(source: str, name: str) -> str:
    return f"{source}@{name}"


def skill_label(source: str, skill: SkillSpec | None) -> str:
    return source_skill_label(source, skill.name if skill else "*")


def github_source(url: str) -> str:
    prefix = "https://github.com/"
    if not url.startswith(prefix):
        return ""
    return url.removeprefix(prefix).removesuffix(".git")


def short_ref(ref: str) -> str:
    return ref.removeprefix("refs/heads/").removeprefix("refs/tags/")


def short_sha(sha: str) -> str:
    return sha[:7] if sha else ""


def target_args(options: GhOptions) -> list[str]:
    return ["--dir", str(options.directory)]


def parse_gh_version(output: str) -> tuple[int, int, int] | None:
    match = re.search(r"gh version (\d+)\.(\d+)\.(\d+)", output)
    if match is None:
        return None
    major, minor, patch = match.groups()
    return (int(major), int(minor), int(patch))


async def ensure_minimum_gh_version(runner: ProcessRunner) -> None:
    result = await runner.run(["gh", "--version"], capture_output=True)
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "gh --version failed"
        raise RuntimeError(message)
    version = parse_gh_version(result.stdout or result.stderr)
    if version is not None and version < MIN_GH_VERSION:
        raise RuntimeError(
            "skeel requires GitHub CLI 2.94.0 or newer for `gh skill list --json`; "
            "update gh and try again"
        )


def install_steps(source: SourceSpec, options: GhOptions) -> list[SkillStep]:
    steps: list[SkillStep] = []
    skills: tuple[SkillSpec | None, ...] = (None,) if source.install_all else source.skills
    fast_session = FastInstallSession(source.source)
    for skill in skills:
        command = ["gh", "skill", "install", source.source]
        label = skill_label(source.source, skill)
        pin = source.pin
        if skill:
            command.append(skill.spec)
            pin = skill.pin
        else:
            command.append("--all")
        command.append("--allow-hidden-dirs")
        command.extend(target_args(options))
        command.append("--force")
        if pin:
            command.extend(["--pin", pin])
        executor: StepExecutor | None = None
        if supports_fast_install(source, skill):
            command = fast_install_command(source, skill)
            executor = fast_install_executor(
                fast_session,
                source=source,
                skill=skill,
                options=options,
                command=command,
            )
        steps.append(SkillStep(label=label, command=command, executor=executor))
    return steps


def fast_install_executor(
    session: FastInstallSession,
    *,
    source: SourceSpec,
    skill: SkillSpec | None,
    options: GhOptions,
    command: Command,
) -> StepExecutor:
    async def execute() -> ProcessResult:
        import asyncio

        try:
            await asyncio.to_thread(session.install, source, skill, options.directory)
        except FastInstallError as error:
            return ProcessResult(command=command, returncode=1, stderr=str(error))
        return ProcessResult(command=command, returncode=0)

    return execute


async def installed_skills(
    options: GhOptions,
    runner: ProcessRunner,
) -> tuple[InstalledSkill, ...]:
    directory = options.directory
    if directory and not directory.exists():
        return ()
    await ensure_minimum_gh_version(runner)

    command = [
        "gh",
        "skill",
        "list",
        "--json",
        "skillName,path,sourceURL,version,pinned",
    ]
    command.extend(target_args(options))
    result = await runner.run(command, capture_output=True)
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "gh skill list failed"
        raise RuntimeError(message)
    entries = json.loads(result.stdout or "[]")
    if not isinstance(entries, list):
        raise RuntimeError("gh skill list returned invalid JSON")
    skills: list[InstalledSkill] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("skillName"), str):
            raise RuntimeError("gh skill list returned invalid skill entries")
        path = entry.get("path")
        if not isinstance(path, str):
            raise RuntimeError("gh skill list returned invalid skill path")
        skill_path = Path(path)
        source_url = entry.get("sourceURL")
        version = entry.get("version")
        pinned = entry.get("pinned")
        skills.append(
            InstalledSkill(
                name=entry["skillName"],
                path=skill_path,
                source_url=source_url if isinstance(source_url, str) else "",
                version=version if isinstance(version, str) else "",
                pinned=pinned if isinstance(pinned, bool) else False,
                provenance=read_skill_provenance(skill_path),
            )
        )
    return tuple(skills)


async def installed_skill_names(options: GhOptions, runner: ProcessRunner) -> set[str]:
    return {skill.name for skill in await installed_skills(options, runner)}


def desired_skill_names(manifest: Manifest) -> set[str]:
    return manifest.desired_skill_names


def desired_labels(manifest: Manifest) -> dict[str, str]:
    labels: dict[str, str] = {}
    for skill in manifest.desired_skills:
        label = desired_label(skill)
        for alias in desired_aliases(skill):
            labels.setdefault(alias, label)
    return labels


def desired_label(skill: DesiredSkill) -> str:
    return source_skill_label(skill.source, skill.name)


def desired_aliases(skill: DesiredSkill) -> set[str]:
    return {skill.name, Path(skill.name).name, Path(skill.spec).name}


def desired_install_specs(manifest: Manifest) -> dict[str, tuple[SourceSpec, SkillSpec]]:
    specs: dict[str, tuple[SourceSpec, SkillSpec]] = {}
    for source in manifest.sources:
        for skill in source.skills:
            desired = DesiredSkill(name=skill.name, spec=skill.spec, source=source.source)
            for alias in desired_aliases(desired):
                specs.setdefault(alias, (source, skill))
    return specs


def matching_desired_install(
    skill: InstalledSkill,
    specs: dict[str, tuple[SourceSpec, SkillSpec]],
) -> tuple[SourceSpec, SkillSpec] | None:
    for alias in {skill.name, skill.basename, skill.path.name}:
        if spec := specs.get(alias):
            return spec
    return None


def update_steps(
    installed: Sequence[InstalledSkill],
    options: GhOptions,
    *,
    manifest: Manifest,
) -> list[SkillStep]:
    labels = desired_labels(manifest)
    specs = desired_install_specs(manifest)
    sessions: dict[str, FastInstallSession] = {}
    steps: list[SkillStep] = []
    for skill in sorted(installed, key=lambda skill: skill.name):
        label = labels.get(skill.name, labels.get(skill.basename, skill.label))
        if match := matching_desired_install(skill, specs):
            source, skill_spec = match
            if supports_fast_install(source, skill_spec):
                session = sessions.setdefault(source.source, FastInstallSession(source.source))
                command = fast_install_command(source, skill_spec)
                steps.append(
                    SkillStep(
                        label=label,
                        command=command,
                        outcome=fast_update_outcome(skill),
                        executor=fast_install_executor(
                            session,
                            source=source,
                            skill=skill_spec,
                            options=options,
                            command=command,
                        ),
                    )
                )
                continue

        steps.append(
            SkillStep(
                label=label,
                command=[
                    "gh",
                    "skill",
                    "update",
                    skill.update_name,
                    "--dir",
                    str(options.directory),
                ],
                outcome=update_outcome(skill),
            )
        )
    return steps


def update_status(result: ProcessResult) -> str:
    output = "\n".join(part for part in [result.stdout, result.stderr] if part)
    if "has no GitHub metadata" in output:
        return "skipped"
    if "pinned" in output and "skip" in output.lower():
        return "skipped"
    if "All skills are up to date" in output:
        return "current"
    return "updated"


def update_outcome(skill: InstalledSkill) -> OutcomeFactory:
    before = skill.provenance

    def outcome(result: ProcessResult) -> StepOutcome:
        status = update_status(result)
        after = read_skill_provenance(skill.path)
        return StepOutcome(status=status, detail=version_transition(before, after))

    return outcome


def fast_update_outcome(skill: InstalledSkill) -> OutcomeFactory:
    before = skill.provenance

    def outcome(result: ProcessResult) -> StepOutcome:
        del result
        after = read_skill_provenance(skill.path)
        status = "current" if before.version_label == after.version_label else "updated"
        return StepOutcome(status=status, detail=version_transition(before, after))

    return outcome


def version_transition(before: SkillProvenance, after: SkillProvenance) -> str | None:
    before_label = before.version_label
    after_label = after.version_label
    if not before_label and not after_label:
        return None
    if before_label == after_label:
        return before_label
    return f"{before_label or 'unknown'} → {after_label or 'unknown'}"


def read_skill_provenance(path: Path) -> SkillProvenance:
    metadata = read_skill_metadata(path)
    return SkillProvenance(
        repo_url=metadata_string(metadata, "github-repo"),
        ref=metadata_string(metadata, "github-ref"),
        path=metadata_string(metadata, "github-path"),
        tree_sha=metadata_string(metadata, "github-tree-sha"),
    )


def read_skill_metadata(path: Path) -> Mapping[str, object]:
    skill_path = path / "SKILL.md" if path.is_dir() else path
    frontmatter = read_frontmatter(skill_path)
    metadata = frontmatter.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def read_frontmatter(path: Path) -> Mapping[str, object]:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return {}
    if not lines or lines[0].strip() != "---":
        return {}

    body: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        body.append(line)
    else:
        return {}

    data = yaml.safe_load("\n".join(body))
    return data if isinstance(data, dict) else {}


def metadata_string(metadata: Mapping[str, object], key: str) -> str:
    value = metadata.get(key)
    return value if isinstance(value, str) else ""
