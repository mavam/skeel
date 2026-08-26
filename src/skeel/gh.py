from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

import yaml

from .fast_install import (
    FastInstallError,
    FastInstallSession,
    effective_pin,
    fast_install_command,
    is_github_source,
    prunable_skill_directories,
    skill_command_label,
    supports_fast_install,
)
from .frontmatter import (
    FrontmatterError,
    model_invocation_needs_update,
    update_skill_frontmatter,
)
from .io import (
    Command,
    ProcessResult,
    ProcessRunner,
    RemovalGuard,
    StepExecutor,
    StepOutcome,
    StepPostprocessor,
    build_removal_guard,
)
from .manifest import DesiredSkill, Manifest, SkillSpec, SourceSpec
from .targets import SkillTarget

OutcomeFactory = Callable[[ProcessResult], StepOutcome]
MIN_GH_VERSION = (2, 94, 0)
UpdateStatus = Literal["current", "skipped", "updated"]


@dataclass(frozen=True)
class UpdateClassification:
    status: UpdateStatus
    skipped_detail: str | None = None


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
    removal_guard: RemovalGuard | None = None
    kind: Literal["command", "remove", "frontmatter"] = "command"
    scope: str | None = None
    outcome: OutcomeFactory | None = None
    executor: StepExecutor | None = None
    postprocess: StepPostprocessor | None = None
    preview_detail: str | None = None
    parallel: bool = True


@dataclass(frozen=True)
class InstalledSkill:
    name: str
    path: Path
    source_url: str = ""
    version: str = ""
    pinned: bool = False
    provenance: SkillProvenance = field(default_factory=SkillProvenance)
    usable: bool = True

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


def custom_install_environment(
    source: SourceSpec,
    target: SkillTarget,
    manifest: Manifest,
) -> dict[str, str]:
    del source
    return {
        "SKEEL_AGENT": target.agent or "",
        "SKEEL_SCOPE": target.scope,
        "SKEEL_SKILLS_DIR": str(target.directory),
        "SKEEL_MANIFEST": str(manifest.path),
    }


def manual_install_steps(
    source: SourceSpec,
    target: SkillTarget,
    manifest: Manifest,
) -> list[SkillStep]:
    environment = custom_install_environment(source, target, manifest)
    steps: list[SkillStep] = []
    for index, command in enumerate(source.install):
        final = index == len(source.install) - 1
        verify = source.skills if final else ()
        overridden = (
            tuple(skill for skill in source.skills if skill.disable_model_invocation is not None)
            if final
            else ()
        )
        steps.append(
            SkillStep(
                label=source.source,
                command=list(command),
                parallel=False,
                executor=manual_install_executor(
                    list(command),
                    environment,
                    source=source,
                    target=target,
                    verify=verify,
                ),
                postprocess=source_frontmatter_postprocessor(
                    source.source,
                    target,
                    overridden,
                )
                if overridden
                else None,
                preview_detail=source_frontmatter_preview(overridden),
            )
        )
    return steps


def source_frontmatter_postprocessor(
    source: str,
    target: SkillTarget,
    skills: Sequence[SkillSpec],
) -> StepPostprocessor:
    def postprocess(result: ProcessResult) -> ProcessResult:
        for skill in skills:
            result = install_frontmatter_postprocessor(source, target, skill)(result)
            if result.returncode:
                break
        return result

    return postprocess


def source_frontmatter_preview(skills: Sequence[SkillSpec]) -> str | None:
    return "disable-model-invocation" if skills else None


def manual_install_executor(
    command: Command,
    environment: Mapping[str, str],
    *,
    source: SourceSpec,
    target: SkillTarget,
    verify: Sequence[SkillSpec],
) -> StepExecutor:
    async def execute() -> ProcessResult:
        result = await ProcessRunner().run(command, capture_output=True, env=environment)
        if result.returncode:
            return result
        missing: list[str] = []
        for skill in verify:
            try:
                resolve_installed_frontmatter_path(source.source, target, skill)
            except FrontmatterError:
                missing.append(skill.name)
        if missing:
            names = ", ".join(sorted(missing))
            return ProcessResult(
                command=command,
                returncode=1,
                stderr=(
                    f"custom install for {source.source} did not produce "
                    f"skill(s) {names} in {target.directory}; "
                    "portable installers must honor SKEEL_SKILLS_DIR"
                ),
            )
        return result

    return execute


def source_requires_github_metadata(source: SourceSpec) -> bool:
    return not source.install and is_github_source(source.source)


def installed_source_matches(skill: InstalledSkill, source: SourceSpec) -> bool:
    return not source_requires_github_metadata(source) or skill.github_source == source.source


def needs_source_reinstall(skill: InstalledSkill, source: SourceSpec) -> bool:
    return source_requires_github_metadata(source) and not installed_source_matches(skill, source)


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


def target_args(target: SkillTarget) -> list[str]:
    return ["--dir", str(target.directory)]


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


def frontmatter_steps(
    manifest: Manifest,
    target: SkillTarget,
    installed: Sequence[InstalledSkill] = (),
) -> list[SkillStep]:
    installed_index: dict[str, InstalledSkill] = {}
    for installed_skill in installed:
        if not installed_skill.usable:
            continue
        for alias in (
            installed_skill.name,
            installed_skill.basename,
            installed_skill.path.name,
        ):
            installed_index.setdefault(alias, installed_skill)

    steps: list[SkillStep] = []
    seen: set[Path] = set()
    for source in manifest.sources:
        for skill in source.skills:
            desired = DesiredSkill(name=skill.name, spec=skill.spec, source=source.source)
            current = next(
                (
                    installed_index[alias]
                    for alias in desired_aliases(desired)
                    if alias in installed_index
                ),
                None,
            )
            if current is None or not installed_source_matches(current, source):
                continue
            if skill.disable_model_invocation is None:
                continue
            frontmatter_path = current.path / "SKILL.md"
            if frontmatter_path in seen or not frontmatter_path.is_file():
                continue
            if not model_invocation_needs_update(
                frontmatter_path,
                skill.disable_model_invocation,
                root=target.directory,
            ):
                continue
            seen.add(frontmatter_path)
            steps.append(
                frontmatter_step(
                    source.source,
                    skill,
                    frontmatter_path,
                    target.directory,
                )
            )
    return steps


def frontmatter_step(
    source: str,
    skill: SkillSpec,
    path: Path,
    root: Path,
) -> SkillStep:
    disabled = skill.disable_model_invocation
    assert disabled is not None

    async def execute() -> ProcessResult:
        result = ProcessResult(command=[], returncode=0)
        return frontmatter_postprocessor(path, root, disabled)(result)

    detail = model_invocation_preview_detail(disabled)
    return SkillStep(
        label=source_skill_label(source, skill.name),
        command=[],
        kind="frontmatter",
        executor=execute,
        outcome=lambda _result: StepOutcome(status="updated", detail=detail),
        preview_detail=detail,
        parallel=False,
    )


def frontmatter_postprocessor(
    path: Path,
    root: Path,
    disabled: bool,
) -> StepPostprocessor:
    def postprocess(result: ProcessResult) -> ProcessResult:
        try:
            update_skill_frontmatter(
                path,
                disable_model_invocation=disabled,
                root=root,
            )
        except (OSError, UnicodeError, yaml.YAMLError, FrontmatterError, ValueError) as error:
            return replace(result, returncode=1, stderr=str(error))
        return result

    return postprocess


def install_frontmatter_postprocessor(
    source: str,
    target: SkillTarget,
    skill: SkillSpec,
) -> StepPostprocessor:
    def postprocess(result: ProcessResult) -> ProcessResult:
        try:
            path = resolve_installed_frontmatter_path(source, target, skill)
        except FrontmatterError as error:
            return replace(result, returncode=1, stderr=str(error))
        assert skill.disable_model_invocation is not None
        return frontmatter_postprocessor(
            path,
            target.directory,
            skill.disable_model_invocation,
        )(result)

    return postprocess


def resolve_installed_frontmatter_path(
    source: str,
    target: SkillTarget,
    skill: SkillSpec,
) -> Path:
    requested = skill_command_label(skill).removesuffix("/SKILL.md").rstrip("/")
    inferred_name = Path(requested).name
    candidate_names = tuple(dict.fromkeys(name for name in (inferred_name, skill.name) if name))
    for name in candidate_names:
        path = target.directory / name / "SKILL.md"
        if path.is_file():
            return path

    aliases = {skill.name, inferred_name}
    matches: list[Path] = []
    try:
        candidates = tuple(target.directory.iterdir())
    except OSError as error:
        raise FrontmatterError(
            f"could not inspect installed skills in {target.directory}: {error}"
        ) from error
    for candidate in candidates:
        path = candidate / "SKILL.md"
        if not path.is_file():
            continue
        frontmatter = read_frontmatter(path)
        installed_name = frontmatter.get("name")
        provenance = read_skill_provenance(candidate)
        if (
            candidate.name in aliases
            or (isinstance(installed_name, str) and installed_name in aliases)
            or (provenance.source == source and Path(provenance.path).name in aliases)
        ):
            matches.append(path)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise FrontmatterError(f'frontmatter target for skill "{skill.name}" is ambiguous')
    raise FrontmatterError(f'installed skill "{skill.name}" has no SKILL.md in {target.directory}')


def model_invocation_preview_detail(disabled: bool) -> str:
    value = str(disabled).lower()
    return f"disable-model-invocation={value}"


def install_steps(
    source: SourceSpec,
    target: SkillTarget,
    *,
    current: Sequence[InstalledSkill] = (),
    prune: bool = False,
) -> list[SkillStep]:
    steps: list[SkillStep] = []
    skills: tuple[SkillSpec | None, ...] = (None,) if source.install_all else source.skills
    fast_session = FastInstallSession(source.source)
    immutable_inventory = immutable_source_inventory(current)
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
        command.extend(target_args(target))
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
                target=target,
                command=command,
                immutable_inventory=immutable_inventory,
                prune=prune,
            )
        postprocess = None
        preview_detail = None
        if skill is not None and skill.disable_model_invocation is not None:
            postprocess = install_frontmatter_postprocessor(source.source, target, skill)
            preview_detail = model_invocation_preview_detail(skill.disable_model_invocation)
        steps.append(
            SkillStep(
                label=label,
                command=command,
                executor=executor,
                postprocess=postprocess,
                preview_detail=preview_detail,
            )
        )
    return steps


def immutable_source_inventory(
    installed: Sequence[InstalledSkill],
) -> dict[str, tuple[str, str]] | None:
    if not installed:
        return None
    inventory = {
        skill.provenance.path: (skill.provenance.ref, skill.provenance.tree_sha)
        for skill in installed
        if skill.provenance.path and skill.provenance.ref and skill.provenance.tree_sha
    }
    return inventory if len(inventory) == len(installed) else None


async def immutable_source_is_current(
    session: FastInstallSession,
    pin: str,
    inventory: dict[str, tuple[str, str]],
) -> bool:
    import asyncio

    return await asyncio.to_thread(session.immutable_tree_is_current, pin, inventory)


def fast_install_executor(
    session: FastInstallSession,
    *,
    source: SourceSpec,
    skill: SkillSpec | None,
    target: SkillTarget,
    command: Command,
    immutable_inventory: dict[str, tuple[str, str]] | None = None,
    prune: bool = False,
) -> StepExecutor:
    async def execute() -> ProcessResult:
        import asyncio

        try:
            pin = source.pin if skill is None else None
            if (
                pin
                and immutable_inventory
                and await immutable_source_is_current(session, pin, immutable_inventory)
            ):
                return ProcessResult(command=command, returncode=0)
            install_result = await asyncio.to_thread(
                session.install,
                source,
                skill,
                target.directory,
                prune=prune,
            )
        except FastInstallError as error:
            return ProcessResult(command=command, returncode=1, stderr=str(error))
        return ProcessResult(
            command=command,
            returncode=0,
            removed_paths=install_result.removed_paths,
            warnings=install_result.warnings,
        )

    return execute


async def installed_skills(
    target: SkillTarget,
    runner: ProcessRunner,
) -> tuple[InstalledSkill, ...]:
    directory = target.directory
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
    command.extend(target_args(target))
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
    known_paths = {canonical_skill_entry(skill.path) for skill in skills}
    skills.extend(linked_skills(directory, known_paths=known_paths))
    return tuple(sorted(skills, key=lambda skill: (skill.name, str(skill.path))))


def canonical_skill_entry(path: Path) -> Path:
    """Canonicalize a directory entry without following the entry itself."""
    return path.parent.resolve() / path.name


def linked_skills(directory: Path, *, known_paths: set[Path]) -> tuple[InstalledSkill, ...]:
    """Discover skill-directory symlinks omitted by ``gh skill list``."""
    try:
        entries = tuple(directory.iterdir())
    except OSError:
        return ()

    skills: list[InstalledSkill] = []
    for path in entries:
        if canonical_skill_entry(path) in known_paths or not path.is_symlink():
            continue
        skill_path = path / "SKILL.md"
        if path.exists() and not skill_path.is_file():
            continue
        usable = skill_path.is_file()
        frontmatter = read_frontmatter(skill_path) if usable else {}
        name = frontmatter.get("name")
        skills.append(
            InstalledSkill(
                name=name if isinstance(name, str) and name else path.name,
                path=path,
                provenance=read_skill_provenance(path) if usable else SkillProvenance(),
                usable=usable,
            )
        )
    return tuple(skills)


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


def scoped_steps(steps: Sequence[SkillStep], scope: str | None) -> list[SkillStep]:
    """Stamp every step from a manifest context with its scope for display."""
    if scope is None:
        return list(steps)
    return [replace(step, scope=scope) for step in steps]


def update_steps(
    installed: Sequence[InstalledSkill],
    target: SkillTarget,
    *,
    manifest: Manifest,
) -> list[SkillStep]:
    # Import locally to avoid the gh -> reconcile -> gh module cycle. This keeps
    # dynamic-source attribution consistent with apply, diff, and list.
    from .reconcile import matching_dynamic_source_skills

    labels = desired_labels(manifest)
    specs = desired_install_specs(manifest)
    sessions: dict[str, FastInstallSession] = {}
    repair_unknown_paths = dynamic_repair_unknown_paths(installed, manifest)
    dynamic_sources = tuple(source for source in manifest.sources if source.install_all)
    orphan_source = dynamic_sources[0] if len(dynamic_sources) == 1 else None
    excluded_paths: set[Path] = set()
    steps: list[SkillStep] = []

    # Refresh install-all entries once at source level so the installer can
    # discover skills that were added upstream since the previous install.
    for source in dynamic_sources:
        attributed = list(matching_dynamic_source_skills(source, installed))
        if source is orphan_source:
            attributed.extend(skill for skill in installed if skill.path in repair_unknown_paths)
            excluded_paths.update(repair_unknown_paths)
        attributed = list(unique_installed_skills(attributed))
        excluded_paths.update(skill.path for skill in attributed)

        step = install_steps(source, target, current=attributed, prune=True)[0]
        steps.append(
            replace(
                step,
                outcome=source_update_outcome(source, attributed, target),
                parallel=not supports_fast_install(source, None),
            )
        )

    # Explicit entries retain their per-skill update and repair behavior.
    for skill in sorted(installed, key=lambda skill: skill.name):
        if skill.path in excluded_paths:
            continue
        label = labels.get(skill.name, labels.get(skill.basename, skill.label))
        matched_spec: SkillSpec | None = None
        if match := matching_desired_install(skill, specs):
            source, skill_spec = match
            matched_spec = skill_spec
            if supports_fast_install(source, skill_spec):
                session = sessions.setdefault(source.source, FastInstallSession(source.source))
                command = fast_install_command(source, skill_spec)
                step = SkillStep(
                    label=label,
                    command=command,
                    outcome=fast_update_outcome(skill),
                    executor=fast_install_executor(
                        session,
                        source=source,
                        skill=skill_spec,
                        target=target,
                        command=command,
                    ),
                )
                steps.append(with_update_frontmatter(step, skill, skill_spec, target))
                continue
            if needs_source_reinstall(skill, source):
                repair = install_step_for_skill(source, skill_spec, target)
                repair = replace(repair, label=label, outcome=update_outcome(skill))
                steps.append(with_update_frontmatter(repair, skill, skill_spec, target))
                continue

        step = SkillStep(
            label=label,
            command=[
                "gh",
                "skill",
                "update",
                skill.update_name,
                "--dir",
                str(target.directory),
                "--all",
            ],
            outcome=update_outcome(skill),
        )
        if matched_spec is not None:
            step = with_update_frontmatter(step, skill, matched_spec, target)
        steps.append(step)
    return steps


def with_update_frontmatter(
    step: SkillStep,
    installed: InstalledSkill,
    desired: SkillSpec,
    target: SkillTarget,
) -> SkillStep:
    if desired.disable_model_invocation is None:
        return step
    return replace(
        step,
        postprocess=frontmatter_postprocessor(
            installed.path / "SKILL.md",
            target.directory,
            desired.disable_model_invocation,
        ),
        preview_detail=model_invocation_preview_detail(desired.disable_model_invocation),
    )


def pinned_prune_preview_steps(
    manifest: Manifest,
    target: SkillTarget,
) -> list[SkillStep]:
    steps: list[SkillStep] = []
    for source in manifest.sources:
        if not source.install_all or not supports_fast_install(source, None):
            continue
        pin = effective_pin(source, None)
        assert pin is not None
        repository_tree = FastInstallSession(source.source).repository_tree(pin)
        if not repository_tree.complete:
            continue
        for path in prunable_skill_directories(
            source=source.source,
            remote_skill_paths=repository_tree.skill_paths,
            directory=target.directory,
        ):
            steps.append(
                SkillStep(
                    label=source_skill_label(source.source, path.name),
                    command=["rm", "-rf", str(path)],
                    remove_path=path,
                    removal_guard=build_removal_guard(target.directory, path),
                    kind="remove",
                    parallel=False,
                )
            )
    return steps


def unique_installed_skills(
    skills: Sequence[InstalledSkill],
) -> tuple[InstalledSkill, ...]:
    unique: list[InstalledSkill] = []
    seen: set[Path] = set()
    for skill in skills:
        if skill.path in seen:
            continue
        seen.add(skill.path)
        unique.append(skill)
    return tuple(unique)


def install_step_for_skill(
    source: SourceSpec,
    skill: SkillSpec,
    target: SkillTarget,
) -> SkillStep:
    source = SourceSpec(source=source.source, skills=(skill,), pin=source.pin)
    return install_steps(source, target)[0]


def dynamic_repair_unknown_paths(
    installed: Sequence[InstalledSkill],
    manifest: Manifest,
) -> set[Path]:
    specs = desired_install_specs(manifest)
    return {
        skill.path
        for skill in installed
        if not skill.github_source and matching_desired_install(skill, specs) is None
    }


def update_output(result: ProcessResult) -> str:
    return "\n".join(part for part in [result.stdout, result.stderr] if part)


def classify_update_output(output: str) -> UpdateClassification:
    lowered = output.lower()
    if "has no github metadata" in lowered:
        return UpdateClassification("skipped", "missing GitHub metadata")
    if "pinned" in lowered and "skip" in lowered:
        return UpdateClassification("skipped", "pinned")
    if "all skills are up to date" in lowered:
        return UpdateClassification("current")
    return UpdateClassification("updated")


def update_outcome(skill: InstalledSkill) -> OutcomeFactory:
    before = skill.provenance

    def outcome(result: ProcessResult) -> StepOutcome:
        classification = classify_update_output(update_output(result))
        after = read_skill_provenance(skill.path)
        detail = version_transition(before, after)
        if detail is None and classification.status == "skipped":
            detail = classification.skipped_detail
        return StepOutcome(status=classification.status, detail=detail)

    return outcome


def fast_update_outcome(skill: InstalledSkill) -> OutcomeFactory:
    before = skill.provenance

    def outcome(result: ProcessResult) -> StepOutcome:
        del result
        after = read_skill_provenance(skill.path)
        status = "current" if before.version_label == after.version_label else "updated"
        return StepOutcome(status=status, detail=version_transition(before, after))

    return outcome


def source_update_outcome(
    source: SourceSpec,
    installed: Sequence[InstalledSkill],
    target: SkillTarget,
) -> OutcomeFactory:
    before = {skill.path: read_skill_provenance(skill.path) for skill in installed}
    known_paths = set(before)

    def outcome(result: ProcessResult) -> StepOutcome:
        after = scan_source_inventory(source, target, known_paths=known_paths)
        classified = classify_source_inventory_change(before, after)
        if not result.removed_paths:
            return classified
        names = ", ".join(sorted(path.name for path in result.removed_paths))
        detail = classified.detail or skill_count_detail(len(result.removed_paths), prefix="-")
        return StepOutcome(
            status=classified.status,
            detail=f"{detail} (removed: {names})",
        )

    return outcome


def scan_source_inventory(
    source: SourceSpec,
    target: SkillTarget,
    *,
    known_paths: set[Path] | None = None,
) -> dict[Path, SkillProvenance]:
    known_paths = known_paths or set()
    candidates = set(known_paths)
    try:
        candidates.update(
            path
            for path in target.directory.iterdir()
            if path.is_dir() and (path / "SKILL.md").is_file()
        )
    except OSError:
        pass

    inventory: dict[Path, SkillProvenance] = {}
    for path in candidates:
        if not path.exists():
            continue
        provenance = read_skill_provenance(path)
        if path in known_paths or provenance.source == source.source:
            inventory[path] = provenance
    return inventory


def classify_source_inventory_change(
    before: Mapping[Path, SkillProvenance],
    after: Mapping[Path, SkillProvenance],
) -> StepOutcome:
    added = set(after) - set(before)
    removed = set(before) - set(after)
    changed = {
        path
        for path in set(before) & set(after)
        if before[path].version_label != after[path].version_label
    }
    if not added and not removed and not changed:
        return StepOutcome(status="current")

    detail = source_inventory_change_detail(before, after, added, removed, changed)
    return StepOutcome(status="updated", detail=detail)


def source_inventory_change_detail(
    before: Mapping[Path, SkillProvenance],
    after: Mapping[Path, SkillProvenance],
    added: set[Path],
    removed: set[Path],
    changed: set[Path],
) -> str:
    if changed and not added and not removed:
        transitions = {
            transition
            for path in changed
            if (transition := version_transition(before[path], after[path])) is not None
        }
        if len(transitions) == 1:
            return next(iter(transitions))

    details: list[str] = []
    if added:
        details.append(skill_count_detail(len(added), prefix="+"))
    if removed:
        details.append(skill_count_detail(len(removed), prefix="-"))
    if changed:
        details.append(f"{len(changed)} changed")
    return ", ".join(details)


def skill_count_detail(count: int, *, prefix: str) -> str:
    noun = "skill" if count == 1 else "skills"
    return f"{prefix}{count} {noun}"


def version_transition(before: SkillProvenance, after: SkillProvenance) -> str | None:
    before_label = before.version_label
    after_label = after.version_label
    if before_label == after_label:
        return None
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
    except OSError, UnicodeError:
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

    try:
        data = yaml.safe_load("\n".join(body))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def metadata_string(metadata: Mapping[str, object], key: str) -> str:
    value = metadata.get(key)
    return value if isinstance(value, str) else ""
