import asyncio
import json
from pathlib import Path

from skeel import __version__
from skeel.cli import Runtime, diff_skills, main, run_steps
from skeel.gh import GhOptions, InstalledSkill, SkillStep
from skeel.io import ProcessResult, ProcessRunner, StepOutcome, Terminal, detail_text, label_text
from skeel.manifest import Manifest, SkillSpec, SourceSpec, load_manifest


def write_manifest(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "skills.yaml"
    path.write_text(content.strip())
    return path


def test_no_arguments_prints_help(capsys) -> None:
    assert main([]) == 0

    output = capsys.readouterr().out
    assert "Usage:" in output
    assert "skeel" in output
    assert "apply" in output
    assert "add" in output
    assert "remove" in output


def test_version_flag_prints_version(capsys) -> None:
    assert main(["--version"]) == 0

    assert capsys.readouterr().out.strip() == f"skeel {__version__}"


def test_apply_without_default_manifest_is_noop(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    assert main(["apply"]) == 0

    output = capsys.readouterr().out
    assert "no manifest" in output
    assert ".agents/skills.yaml" in output
    assert not (tmp_path / ".agents").exists()


def test_apply_dry_run_reconciles_missing_and_extra_skills(tmp_path, capsys, monkeypatch) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  tenzir/skills:
    - tenzir-docs
    - tenzir-ecs
""",
    )
    workdir = tmp_path / "work"
    target = workdir / ".agents" / "skills"
    target.mkdir(parents=True)
    monkeypatch.chdir(workdir)

    async def fake_installed_skills(options, runner):
        assert options.directory == target
        return (
            InstalledSkill(name="tenzir-docs", path=target / "tenzir-docs"),
            InstalledSkill(name="obsolete", path=target / "obsolete"),
        )

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "--manifest", str(path), "apply", "--dry-run"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [step["label"] for step in payload["steps"]] == [
        "tenzir/skills@tenzir-ecs",
        "obsolete",
    ]
    assert payload["steps"][0]["command"][:5] == [
        "gh",
        "skill",
        "install",
        "tenzir/skills",
        "tenzir-ecs",
    ]
    assert payload["steps"][1]["command"] == ["rm", "-rf", str(target / "obsolete")]


def test_apply_uses_diff_markers_for_install_and_remove(tmp_path, capsys, monkeypatch) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  tenzir/skills:
    - tenzir-ecs
""",
    )
    workdir = tmp_path / "work"
    target = workdir / ".agents" / "skills"
    (target / "obsolete").mkdir(parents=True)
    monkeypatch.chdir(workdir)

    async def fake_installed_skills(options, runner):
        assert options.directory == target
        return (InstalledSkill(name="obsolete", path=target / "obsolete"),)

    class Runner:
        async def run(self, command, **kwargs):
            assert kwargs == {"capture_output": True}
            return ProcessResult(command=command, returncode=0)

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)
    monkeypatch.setattr("skeel.cli.ProcessRunner", Runner)

    assert main(["--manifest", str(path), "apply"]) == 0
    assert capsys.readouterr().err.splitlines() == [
        "+ tenzir-ecs tenzir/skills",
        "- obsolete",
    ]


def test_apply_reinstall_can_target_manifest_source(tmp_path, capsys, monkeypatch) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  cloudflare/skills:
    - wrangler
  tenzir/skills:
    - tenzir-docs
    - tenzir-ecs
""",
    )
    monkeypatch.chdir(tmp_path)

    assert (
        main(
            [
                "--json",
                "--manifest",
                str(path),
                "apply",
                "--reinstall",
                "tenzir/skills",
                "--dry-run",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert [step["label"] for step in payload["steps"]] == [
        "tenzir/skills@tenzir-docs",
        "tenzir/skills@tenzir-ecs",
    ]


def test_apply_source_selector_does_not_remove_unselected_skills(
    tmp_path, capsys, monkeypatch
) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  cloudflare/skills:
    - wrangler
  tenzir/skills:
    - tenzir-docs
    - tenzir-ecs
""",
    )
    target = tmp_path / ".agents" / "skills"
    target.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    async def fake_installed_skills(options, runner):
        assert options.directory == target
        return (
            InstalledSkill(name="tenzir-docs", path=target / "tenzir-docs"),
            InstalledSkill(name="obsolete", path=target / "obsolete"),
        )

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "--manifest", str(path), "apply", "tenzir/skills", "--dry-run"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [step["label"] for step in payload["steps"]] == ["tenzir/skills@tenzir-ecs"]


def test_apply_defaults_to_user_manifest_when_project_manifest_is_absent(
    tmp_path, capsys, monkeypatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".agents").mkdir(parents=True)
    project.mkdir()
    (home / ".agents" / "skills.yaml").write_text(
        """
sources:
  cloudflare/skills:
    - wrangler
""".strip()
    )
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    async def fake_installed_skills(options, runner):
        assert options.directory == home / ".agents" / "skills"
        return ()

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "apply", "--dry-run"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["steps"][0]["label"] == "cloudflare/skills@wrangler"
    assert payload["steps"][0]["command"] == [
        "gh",
        "skill",
        "install",
        "cloudflare/skills",
        "wrangler",
        "--allow-hidden-dirs",
        "--dir",
        str(home / ".agents" / "skills"),
        "--force",
    ]


def test_add_writes_manifest_in_keyed_shape(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["--json", "add", "tenzir/skills", "tenzir-docs@main"]) == 0
    assert main(["--json", "add", "mavam/quarto-brief"]) == 0

    payload = json.loads(capsys.readouterr().out.splitlines()[-1])
    manifest = load_manifest(tmp_path / ".agents" / "skills.yaml")
    assert payload["changed"] is True
    assert manifest.sources[0].source == "tenzir/skills"
    assert manifest.sources[0].skills[0].spec == "tenzir-docs@main"
    assert manifest.sources[1].install_all is True
    assert (tmp_path / ".agents" / "skills.yaml").read_text() == (
        "sources:\n  tenzir/skills:\n    - tenzir-docs@main\n  mavam/quarto-brief:\n"
    )


def test_add_apply_dry_run_plans_without_writing_manifest(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["--json", "add", "tenzir/skills", "tenzir-docs", "--apply", "--dry-run"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert not (tmp_path / ".agents").exists()
    assert payload["steps"][0]["label"] == "tenzir/skills@tenzir-docs"
    assert payload["steps"][0]["command"][:5] == [
        "gh",
        "skill",
        "install",
        "tenzir/skills",
        "tenzir-docs",
    ]


def test_remove_writes_manifest_in_keyed_shape(tmp_path, capsys, monkeypatch) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  tenzir/skills:
    - tenzir-docs
    - tenzir-ecs
  mavam/quarto-brief:
""",
    )

    assert main(["--json", "--manifest", str(path), "remove", "tenzir/skills", "tenzir-docs"]) == 0
    assert main(["--json", "--manifest", str(path), "remove", "mavam/quarto-brief"]) == 0

    payload = json.loads(capsys.readouterr().out.splitlines()[-1])
    manifest = load_manifest(path)
    assert payload["changed"] is True
    assert manifest.sources[0].source == "tenzir/skills"
    assert [skill.name for skill in manifest.sources[0].skills] == ["tenzir-ecs"]
    assert path.read_text() == "sources:\n  tenzir/skills:\n    - tenzir-ecs\n"


def test_remove_apply_dry_run_reconciles_removed_skill(tmp_path, capsys, monkeypatch) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  tenzir/skills:
    - tenzir-docs
    - tenzir-ecs
""",
    )
    target = tmp_path / ".agents" / "skills"
    target.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    async def fake_installed_skills(options, runner):
        assert options.directory == target
        return (
            InstalledSkill(name="tenzir-docs", path=target / "tenzir-docs"),
            InstalledSkill(name="tenzir-ecs", path=target / "tenzir-ecs"),
        )

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert (
        main(
            [
                "--json",
                "--manifest",
                str(path),
                "remove",
                "tenzir/skills",
                "tenzir-docs",
                "--apply",
                "--dry-run",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["steps"] == [
        {
            "command": ["rm", "-rf", str(target / "tenzir-docs")],
            "label": "tenzir-docs",
            "returncode": None,
            "shell": f"rm -rf {target / 'tenzir-docs'}",
            "status": "removed",
        }
    ]
    assert "tenzir-docs" in path.read_text()


def test_list_reports_project_and_user_manifest_statuses_by_default(
    tmp_path, capsys, monkeypatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".agents").mkdir(parents=True)
    (project / ".agents").mkdir(parents=True)
    (project / ".agents" / "skills.yaml").write_text(
        """
sources:
  tenzir/skills:
    - tenzir-docs
""".strip()
    )
    (home / ".agents" / "skills.yaml").write_text(
        """
sources:
  anthropics/skills:
    - skill-creator
  cloudflare/skills:
    - wrangler
  mavam/quarto-brief:
""".strip()
    )
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    async def fake_installed_skills(options, runner):
        if options.directory == project / ".agents" / "skills":
            return (InstalledSkill(name="tenzir-docs", path=options.directory / "tenzir-docs"),)
        assert options.directory == home / ".agents" / "skills"
        return (
            InstalledSkill(name="skill-creator", path=options.directory / "skill-creator"),
            InstalledSkill(
                name="custom/quarto",
                path=options.directory / "quarto",
                source_url="https://github.com/mavam/quarto-brief.git",
            ),
        )

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "list"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [(skill["scope"], skill["label"], skill["status"]) for skill in payload["skills"]] == [
        ("project", "tenzir/skills@tenzir-docs", "installed"),
        ("user", "anthropics/skills@skill-creator", "installed"),
        ("user", "cloudflare/skills@wrangler", "missing"),
        ("user", "mavam/quarto-brief@quarto", "installed"),
    ]


def test_list_marks_user_scope_rows_with_home_suffix(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".agents").mkdir(parents=True)
    (project / ".agents").mkdir(parents=True)
    (project / ".agents" / "skills.yaml").write_text(
        """
sources:
  tenzir/skills:
    - tenzir-docs
""".strip()
    )
    (home / ".agents" / "skills.yaml").write_text(
        """
sources:
  anthropics/skills:
    - skill-creator
  cloudflare/skills:
    - wrangler
  mavam/quarto-brief:
""".strip()
    )
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    async def fake_installed_skills(options, runner):
        if options.directory == project / ".agents" / "skills":
            return (
                InstalledSkill(
                    name="tenzir-docs",
                    path=options.directory / "tenzir-docs",
                    version="main@a5d04ab",
                ),
            )
        assert options.directory == home / ".agents" / "skills"
        return (
            InstalledSkill(
                name="skill-creator",
                path=options.directory / "skill-creator",
                version="main@3cf9a8d",
            ),
            InstalledSkill(
                name="custom/quarto",
                path=options.directory / "quarto",
                source_url="https://github.com/mavam/quarto-brief.git",
                version="main@e89c555",
            ),
        )

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["list"]) == 0

    assert capsys.readouterr().out.splitlines() == [
        "✔︎ tenzir-docs tenzir/skills main@a5d04ab",
        "✔︎ skill-creator anthropics/skills main@3cf9a8d ⌂",
        "✘ wrangler cloudflare/skills ⌂",
        "✔︎ quarto mavam/quarto-brief main@e89c555 ⌂",
    ]


def test_diff_matches_namespaced_installed_skills_by_basename(monkeypatch) -> None:
    manifest = Manifest(
        path=Path("manifest.yaml"),
        sources=(
            SourceSpec(
                source="mattpocock/skills",
                skills=(
                    SkillSpec(spec="caveman", name="caveman"),
                    SkillSpec(spec="teach", name="teach"),
                ),
            ),
        ),
    )

    async def fake_installed_skills(options, runner):
        return (InstalledSkill(name="productivity/caveman", path=Path("/tmp/skills/caveman")),)

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    diff = asyncio.run(
        diff_skills(manifest, GhOptions(directory=Path("/tmp/skills")), ProcessRunner())
    )

    assert [(skill.name, skill.source) for skill in diff.missing] == [
        ("teach", "mattpocock/skills")
    ]
    assert diff.extra == ()


def test_diff_defaults_to_user_manifest_when_project_manifest_is_absent(
    tmp_path, capsys, monkeypatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".agents").mkdir(parents=True)
    project.mkdir()
    (home / ".agents" / "skills.yaml").write_text(
        """
sources:
  cloudflare/skills:
    - wrangler
""".strip()
    )
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    async def fake_installed_skills(options, runner):
        assert options.directory == home / ".agents" / "skills"
        return ()

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "diff"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["missing"] == [{"name": "wrangler", "source": "cloudflare/skills"}]


def test_diff_human_output_uses_flat_install_and_remove_rows(tmp_path, capsys, monkeypatch) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  cloudflare/skills:
    - wrangler
    - vectorize
""",
    )
    target = tmp_path / ".agents" / "skills"
    target.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    async def fake_installed_skills(options, runner):
        assert options.directory == target
        return (
            InstalledSkill(name="obsolete-skill", path=target / "obsolete-skill"),
            InstalledSkill(name="old-experiment", path=target / "old-experiment"),
        )

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--manifest", str(path), "diff"]) == 1

    assert capsys.readouterr().out.splitlines() == [
        "+ wrangler cloudflare/skills",
        "+ vectorize cloudflare/skills",
        "- obsolete-skill installed",
        "- old-experiment installed",
    ]


def test_apply_failure_reports_failed_skill(tmp_path, capsys, monkeypatch) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  openclaw/gogcli:
    - gog
""",
    )
    monkeypatch.chdir(tmp_path)

    class Runner:
        async def run(self, command, **kwargs):
            assert kwargs == {"capture_output": True}
            if command == ["gh", "--version"]:
                return ProcessResult(command=command, returncode=0, stdout="gh version 2.94.0")
            if command[:3] == ["gh", "skill", "list"]:
                return ProcessResult(command=command, returncode=0, stdout="[]")
            assert "--allow-hidden-dirs" in command
            return ProcessResult(
                command=command,
                returncode=7,
                stdout="process stdout",
                stderr="process stderr",
            )

    monkeypatch.setattr("skeel.cli.ProcessRunner", Runner)

    assert main(["--manifest", str(path), "apply"]) == 7

    captured = capsys.readouterr()
    assert "✘ gog openclaw/gogcli" in captured.err
    assert "failed to install skill: openclaw/gogcli@gog" in captured.err
    assert "process stdout" not in captured.out + captured.err
    assert "process stderr" in captured.err


def test_run_steps_executes_parallel_commands_concurrently(tmp_path: Path) -> None:
    class Runner:
        def __init__(self) -> None:
            self.active = 0
            self.max_active = 0

        async def run(self, command, **kwargs):
            assert kwargs == {"capture_output": True}
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return ProcessResult(command=command, returncode=0)

    runner = Runner()
    runtime = Runtime(
        manifest_path=Path("manifest.yaml"),
        manifest_required=False,
        options=GhOptions(directory=tmp_path),
        runner=runner,
        terminal=Terminal(json_output=True),
    )
    steps = tuple(SkillStep(label=f"skill-{index}", command=[str(index)]) for index in range(8))

    results, exit_code = asyncio.run(
        run_steps(
            steps,
            runtime,
            dry_run=False,
            action="installing",
            dry_run_action="would install",
            done="installed",
        )
    )

    assert exit_code == 0
    assert [result.label for result in results] == [step.label for step in steps]
    assert runner.max_active > 1


def test_run_steps_stops_launching_after_apply_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("skeel.cli.DEFAULT_PARALLELISM", 4)

    class Runner:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        async def run(self, command, **kwargs):
            assert kwargs == {"capture_output": True}
            self.calls.append(command)
            if command == ["fail"]:
                await asyncio.sleep(0)
                return ProcessResult(command=command, returncode=7, stderr="failed")
            await asyncio.sleep(0.02)
            return ProcessResult(command=command, returncode=0)

    runner = Runner()
    runtime = Runtime(
        manifest_path=Path("manifest.yaml"),
        manifest_required=False,
        options=GhOptions(directory=tmp_path),
        runner=runner,
        terminal=Terminal(json_output=True),
    )
    steps = (
        SkillStep(label="fail", command=["fail"]),
        *(SkillStep(label=f"skill-{index}", command=[str(index)]) for index in range(9)),
    )

    results, exit_code = asyncio.run(
        run_steps(
            steps,
            runtime,
            dry_run=False,
            action="installing",
            dry_run_action="would install",
            done="installed",
        )
    )

    assert exit_code == 7
    assert len(runner.calls) == 4
    assert [result.label for result in results] == ["fail", "skill-0", "skill-1", "skill-2"]


def test_run_steps_keeps_manual_steps_as_sequential_barriers(tmp_path: Path) -> None:
    class Runner:
        def __init__(self) -> None:
            self.active: set[str] = set()
            self.events: list[tuple[str, str, tuple[str, ...]]] = []

        async def run(self, command, **kwargs):
            assert kwargs == {"capture_output": True}
            name = command[0]
            self.events.append(("start", name, tuple(sorted(self.active))))
            self.active.add(name)
            await asyncio.sleep(0.01)
            self.active.remove(name)
            self.events.append(("end", name, tuple(sorted(self.active))))
            return ProcessResult(command=command, returncode=0)

    runner = Runner()
    runtime = Runtime(
        manifest_path=Path("manifest.yaml"),
        manifest_required=False,
        options=GhOptions(directory=tmp_path),
        runner=runner,
        terminal=Terminal(json_output=True),
    )
    steps = (
        SkillStep(label="parallel-1", command=["parallel-1"]),
        SkillStep(label="parallel-2", command=["parallel-2"]),
        SkillStep(label="manual", command=["manual"], parallel=False),
        SkillStep(label="parallel-3", command=["parallel-3"]),
    )

    results, exit_code = asyncio.run(
        run_steps(
            steps,
            runtime,
            dry_run=False,
            action="installing",
            dry_run_action="would install",
            done="installed",
        )
    )

    assert exit_code == 0
    assert [result.label for result in results] == [step.label for step in steps]
    assert ("start", "manual", ()) in runner.events
    assert ("start", "parallel-3", ()) in runner.events

    def event_index(action: str, name: str) -> int:
        return next(
            index
            for index, (event_action, event_name, _active) in enumerate(runner.events)
            if event_action == action and event_name == name
        )

    assert event_index("end", "parallel-1") < event_index("start", "manual")
    assert event_index("end", "parallel-2") < event_index("start", "manual")
    assert event_index("end", "manual") < event_index("start", "parallel-3")


def test_run_steps_turns_live_progress_rows_into_final_results(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class Runner:
        async def run(self, command, **kwargs):
            assert kwargs == {"capture_output": True}
            return ProcessResult(command=command, returncode=0)

    class Progress:
        def __init__(self) -> None:
            self.events: list[tuple[str, object]] = []
            self.next_task_id = 0

        def __enter__(self):
            self.events.append(("enter", None))
            return self

        def __exit__(self, *args):
            self.events.append(("exit", None))
            return None

        def add_task(self, description: str, **fields) -> int:
            self.next_task_id += 1
            self.events.append(("add", (self.next_task_id, description, fields)))
            return self.next_task_id

        def update(self, task_id: int, **fields) -> None:
            self.events.append(("update", (task_id, fields)))

        def remove_task(self, task_id: int) -> None:
            self.events.append(("remove", task_id))

    progress = Progress()
    terminal = Terminal(json_output=False)
    rendered: list[str] = []
    monkeypatch.setattr(terminal, "live_progress_enabled", lambda: True)
    monkeypatch.setattr(terminal, "progress", lambda: progress)
    monkeypatch.setattr(
        terminal,
        "render_step_result",
        lambda result: rendered.append(result.label),
    )
    runtime = Runtime(
        manifest_path=Path("manifest.yaml"),
        manifest_required=False,
        options=GhOptions(directory=tmp_path),
        runner=Runner(),
        terminal=terminal,
    )
    steps = (
        SkillStep(
            label="current",
            command=["current"],
            outcome=lambda _result: StepOutcome(status="current", detail="main@abc1234"),
        ),
        SkillStep(
            label="skipped",
            command=["skipped"],
            outcome=lambda _result: StepOutcome(status="skipped"),
        ),
    )

    results, exit_code = asyncio.run(
        run_steps(
            steps,
            runtime,
            dry_run=False,
            action="updating",
            dry_run_action="would update",
            done="updated",
            keep_going=True,
        )
    )

    assert exit_code == 0
    assert [result.label for result in results] == ["current", "skipped"]
    assert ("remove", 1) not in progress.events
    assert ("remove", 2) not in progress.events
    assert rendered == []
    assert (
        "update",
        (
            1,
            {
                "completed": 1,
                "marker": "✔︎",
                "marker_style": "green",
                "detail": "main@abc1234",
                "refresh": True,
            },
        ),
    ) in progress.events
    assert (
        "update",
        (
            2,
            {
                "completed": 1,
                "marker": "✔︎",
                "marker_style": "yellow",
                "detail": "",
                "refresh": True,
            },
        ),
    ) in progress.events


def test_version_transition_detail_highlights_old_and_new_versions() -> None:
    text = detail_text("main@old1234 → main@new5678")

    assert text.plain == "main@new5678"
    assert str(text.style) == ""
    assert [(span.start, span.end, str(span.style)) for span in text.spans] == [
        (0, 12, "not bold green"),
    ]


def test_skill_label_styles_skill_then_source() -> None:
    text = label_text("tenzir/skills@tenzir-docs")

    assert text.plain == "tenzir-docs tenzir/skills"
    assert str(text.style) == ""
    assert [(span.start, span.end, str(span.style)) for span in text.spans] == [
        (0, 11, "bold black"),
        (11, 12, "not bold bright_black"),
        (12, 25, "not bold cyan"),
    ]


def test_wildcard_skill_label_hides_star() -> None:
    text = label_text("mavam/quarto-brief@*")

    assert text.plain == "mavam/quarto-brief"
    assert str(text.style) == ""
    assert [(span.start, span.end, str(span.style)) for span in text.spans] == [
        (0, 18, "bold black"),
    ]


def test_update_dry_run_labels_installed_skills_from_manifest(
    tmp_path, capsys, monkeypatch
) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  mattpocock/skills:
    - caveman
""",
    )
    workdir = tmp_path / "work"
    target = workdir / ".agents" / "skills"
    target.mkdir(parents=True)
    monkeypatch.chdir(workdir)

    async def fake_installed_skills(options, runner):
        assert options.directory == target
        return (
            InstalledSkill(
                name="productivity/caveman",
                path=target / "caveman",
                source_url="https://github.com/mattpocock/skills",
            ),
            InstalledSkill(name="clacks", path=target / "clacks"),
        )

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "--manifest", str(path), "update", "--dry-run"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [step["label"] for step in payload["steps"]] == [
        "clacks",
        "mattpocock/skills@caveman",
    ]


def test_update_human_output_has_no_final_success_line(tmp_path, capsys, monkeypatch) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  cloudflare/skills:
    - wrangler
""",
    )
    target = tmp_path / ".agents" / "skills"
    target.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    async def fake_installed_skills(options, runner):
        assert options.directory == target
        return (InstalledSkill(name="wrangler", path=target / "wrangler"),)

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--manifest", str(path), "update", "--dry-run"]) == 0

    output = capsys.readouterr().out
    assert "gh skill update wrangler" in output
    assert "skills updated" not in output
    assert "dry run complete" not in output
    assert "skills are in sync" not in output


def test_update_defaults_to_user_manifest_when_project_manifest_is_absent(
    tmp_path, capsys, monkeypatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".agents").mkdir(parents=True)
    project.mkdir()
    (home / ".agents" / "skills.yaml").write_text(
        """
sources:
  cloudflare/skills:
    - wrangler
""".strip()
    )
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    async def fake_installed_skills(options, runner):
        assert options.directory == home / ".agents" / "skills"
        return (InstalledSkill(name="wrangler", path=options.directory / "wrangler"),)

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "update", "--dry-run"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["steps"][0]["label"] == "cloudflare/skills@wrangler"
    assert payload["steps"][0]["command"] == [
        "gh",
        "skill",
        "update",
        "wrangler",
        "--dir",
        str(home / ".agents" / "skills"),
    ]
