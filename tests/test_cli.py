import asyncio
import json
import re
import sys
from pathlib import Path

import pytest

from skeel import __version__
from skeel.cli import Runtime, configure_interrupt_handling, diff_skills, main
from skeel.gh import GhOptions, InstalledSkill, SkillStep, read_skill_provenance
from skeel.io import (
    ProcessResult,
    ProcessRunner,
    StepOutcome,
    StepResult,
    Terminal,
    run_steps,
)
from skeel.manifest import Manifest, SkillSpec, SourceSpec, load_manifest

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def plain(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def write_manifest(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "skills.yaml"
    path.write_text(content.strip())
    return path


def write_update_manifest(tmp_path: Path, sources: dict[str, list[str]]) -> Path:
    lines = ["sources:"]
    for source, skills in sources.items():
        lines.append(f"  {source}:")
        for skill in skills:
            lines.append(f"    - {skill}")
    return write_manifest(tmp_path, "\n".join(lines))


def write_shadowed_scope(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path, Path]:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project_target = project / ".agents" / "skills"
    user_target = home / ".agents" / "skills"
    project_target.mkdir(parents=True)
    user_target.mkdir(parents=True)
    (project / ".agents" / "skills.yaml").write_text(
        """
sources:
  project/skills:
    - wrangler
""".strip()
    )
    (home / ".agents" / "skills.yaml").write_text(
        """
sources:
  cloudflare/skills:
    - wrangler
""".strip()
    )
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)
    return home, project, project_target, user_target


def assert_shadow_warning(payload: dict[str, object]) -> None:
    warnings = payload["warnings"]
    assert isinstance(warnings, list)
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning["type"] == "shadowed-skill"
    assert warning["name"] == "wrangler"
    assert warning["shadowing_scope"] == "project"
    assert warning["shadowed_scope"] == "user"
    assert warning["project_label"] == "project/skills@wrangler"
    assert warning["user_label"] == "cloudflare/skills@wrangler"
    assert "project scope is effective" in warning["message"]
    assert "user/global scope was skipped" in warning["message"]


def write_skill_metadata(path: Path, *, name: str, source: str, sha: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"""
---
metadata:
  github-ref: refs/heads/main
  github-repo: https://github.com/{source}
  github-tree-sha: {sha}
name: {name}
---
# {name}
""".strip()
    )


def installed_update_skill(
    target: Path,
    *,
    name: str,
    source: str,
    sha: str = "9f3e1a20000",
) -> InstalledSkill:
    path = target / name
    write_skill_metadata(path, name=name, source=source, sha=sha)
    return InstalledSkill(
        name=name,
        path=path,
        source_url=f"https://github.com/{source}",
        provenance=read_skill_provenance(path),
    )


class UpdateRunner:
    def __init__(
        self,
        target: Path,
        sources: dict[str, str],
        *,
        updated: dict[str, str] | None = None,
        skipped: set[str] | None = None,
        failed: set[str] | None = None,
    ) -> None:
        self.target = target
        self.sources = sources
        self.updated = updated or {}
        self.skipped = skipped or set()
        self.failed = failed or set()

    async def run(self, command, **kwargs):
        assert kwargs == {"capture_output": True}
        assert command[:3] == ["gh", "skill", "update"]
        name = command[3]
        if name in self.failed:
            return ProcessResult(command=command, returncode=7, stderr="gh failed")
        if name in self.updated:
            write_skill_metadata(
                self.target / name,
                name=name,
                source=self.sources[name],
                sha=self.updated[name],
            )
            return ProcessResult(command=command, returncode=0, stdout=f"Updated {name}")
        if name in self.skipped:
            return ProcessResult(command=command, returncode=0, stdout=f"{name} pinned, skipped")
        return ProcessResult(command=command, returncode=0, stdout="All skills are up to date")


def test_no_arguments_prints_help(capsys) -> None:
    assert main([]) == 0

    output = capsys.readouterr().out
    assert "Usage:" in output
    assert "skeel" in output
    assert "apply" in output
    assert "add" in output
    assert "remove" in output
    assert f"skeel {__version__}" not in output


def test_version_flag_prints_version(capsys) -> None:
    assert main(["--version"]) == 0

    assert capsys.readouterr().out.strip() == __version__


def test_help_lists_scope_shortcuts(capsys) -> None:
    assert main([]) == 0

    output = plain(capsys.readouterr().out)
    assert "-g, --user" in output
    assert "Alias: --global" in output
    assert "-a, --all" in output


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (
            [],
            [
                "Examples",
                "skeel add owner/repo skill-name",
                "skeel apply --dry-run",
                "skeel update",
                "skeel --manifest ./skills.yaml apply",
            ],
        ),
        (
            ["path", "--help"],
            [
                "Examples",
                "skeel path",
                "skeel -g path",
                "skeel path -a --json",
            ],
        ),
        (
            ["diff", "--help"],
            [
                "Examples",
                "skeel diff",
                "skeel diff -a",
                "skeel --manifest ./skills.yaml diff",
                "skeel diff --json",
            ],
        ),
        (
            ["list", "--help"],
            [
                "Examples",
                "skeel list",
                "skeel list -a",
                "skeel -g list",
                "skeel list --json",
            ],
        ),
        (
            ["apply", "--help"],
            [
                "Examples",
                "skeel apply --dry-run",
                "skeel apply owner/repo",
                "skeel apply owner/repo skill-name",
                "skeel apply --reinstall",
            ],
        ),
        (
            ["add", "--help"],
            [
                "Examples",
                "skeel add owner/repo skill-name",
                "skeel add owner/repo skill-name@main",
                "skeel add owner/repo",
                "skeel -g add owner/repo skill-name",
            ],
        ),
        (
            ["remove", "--help"],
            [
                "Examples",
                "skeel remove skill-name",
                "skeel remove skill-name --source owner/repo",
                "skeel remove --source owner/repo",
                "skeel remove skill-name -a",
            ],
        ),
        (
            ["update", "--help"],
            [
                "Examples",
                "skeel update",
                "skeel update owner/repo",
                "skeel update owner/repo skill-name",
                "skeel update --verbose",
            ],
        ),
    ],
)
def test_help_lists_examples(args, expected, capsys) -> None:
    assert main(args) == 0

    output = plain(capsys.readouterr().out)
    for text in expected:
        assert text in output


def test_path_defaults_to_project_scope(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    assert main(["path"]) == 0

    assert capsys.readouterr().out.strip() == ".agents/skills.yaml"


@pytest.mark.parametrize("selector", ["-g", "--user", "--global"])
@pytest.mark.parametrize("after_subcommand", [False, True])
def test_path_user_scope_shortcuts(
    tmp_path, capsys, monkeypatch, selector: str, after_subcommand: bool
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    args = ["path", selector] if after_subcommand else [selector, "path"]
    assert main(args) == 0

    assert (
        Path(capsys.readouterr().out.strip()).resolve()
        == (home / ".agents" / "skills.yaml").resolve()
    )


def test_path_all_scopes_json(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    assert main(["--json", "path", "-a"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "paths": [
            {"scope": "project", "path": ".agents/skills.yaml"},
            {"scope": "user", "path": str(home / ".agents" / "skills.yaml")},
        ]
    }


@pytest.mark.parametrize(
    "args",
    [
        ["path", "-a"],
        ["apply", "--dry-run", "-a"],
        ["remove", "-a", "alpha-skill"],
    ],
)
def test_all_scopes_rejects_cli_manifest(args, tmp_path, capsys, monkeypatch) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  example/skills:
    - alpha-skill
""",
    )

    async def fake_installed_skills(options, runner):
        raise AssertionError(f"unexpected skill directory: {options.directory}")

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--manifest", str(path), *args]) == 2

    assert "--all cannot be used with an explicit manifest" in capsys.readouterr().err


@pytest.mark.parametrize(
    "args",
    [
        ["path", "-a"],
        ["apply", "--dry-run", "-a"],
        ["remove", "-a", "alpha-skill"],
    ],
)
def test_all_scopes_rejects_env_manifest(args, tmp_path, capsys, monkeypatch) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  example/skills:
    - alpha-skill
""",
    )
    monkeypatch.setenv("SKEEL_MANIFEST", str(path))

    async def fake_installed_skills(options, runner):
        raise AssertionError(f"unexpected skill directory: {options.directory}")

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(args) == 2

    assert "--all cannot be used with an explicit manifest" in capsys.readouterr().err


@pytest.mark.parametrize(
    "args",
    [
        ["--scope", "user", "-g", "path"],
        ["--scope", "user", "--scope", "project", "path"],
        ["-g", "--user", "path"],
        ["-ga", "path"],
        ["--all", "--user", "path"],
    ],
)
def test_multiple_scope_selectors_are_rejected(args, capsys) -> None:
    assert main(args) == 2

    assert "multiple scope selectors are not allowed" in capsys.readouterr().err


def test_interrupt_handling_suppresses_unraisable_keyboard_interrupt(monkeypatch) -> None:
    forwarded: list[object] = []

    def original_hook(unraisable: object) -> None:
        forwarded.append(unraisable)

    class Unraisable:
        def __init__(self, exc_type: type[BaseException]) -> None:
            self.exc_type = exc_type

    monkeypatch.setattr(sys, "unraisablehook", original_hook)

    configure_interrupt_handling()
    hook = sys.unraisablehook

    hook(Unraisable(KeyboardInterrupt))
    runtime_error = Unraisable(RuntimeError)
    hook(runtime_error)
    configure_interrupt_handling()

    assert forwarded == [runtime_error]
    assert sys.unraisablehook is hook


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


def test_apply_defaults_to_project_scope(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".agents").mkdir(parents=True)
    (project / ".agents").mkdir(parents=True)
    (project / ".agents" / "skills.yaml").write_text(
        """
sources:
  project/skills:
    - local-alpha
""".strip()
    )
    (home / ".agents" / "skills.yaml").write_text(
        """
sources:
  user/skills:
    - user-beta
""".strip()
    )
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    async def fake_installed_skills(options, runner):
        assert options.directory == project / ".agents" / "skills"
        return ()

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "apply", "--dry-run"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [(step["scope"], step["label"]) for step in payload["steps"]] == [
        ("project", "project/skills@local-alpha"),
    ]


def test_apply_all_warns_and_skips_shadowed_user_skill(tmp_path, capsys, monkeypatch) -> None:
    write_shadowed_scope(tmp_path, monkeypatch)

    async def fake_installed_skills(options, runner):
        return ()

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "apply", "-a", "--dry-run"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [(step["scope"], step["label"]) for step in payload["steps"]] == [
        ("project", "project/skills@wrangler"),
    ]
    assert_shadow_warning(payload)


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


def test_apply_selector_requires_manifest_match(tmp_path, capsys, monkeypatch) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  tenzir/skills:
    - tenzir-docs
""",
    )
    monkeypatch.chdir(tmp_path)

    assert main(["--manifest", str(path), "apply", "cloudflare/skills", "--dry-run"]) == 2
    assert "no manifest entry matches: cloudflare/skills@*" in capsys.readouterr().err

    assert main(["--manifest", str(path), "apply", "tenzir/skills", "tenzir-ecs", "--dry-run"]) == 2
    assert "no manifest entry matches: tenzir/skills@tenzir-ecs" in capsys.readouterr().err


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


def test_add_human_output_marks_user_scope(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    assert main(["--scope", "user", "add", "tenzir/skills", "tenzir-docs"]) == 0

    output = capsys.readouterr().out
    line = " ".join(output.split())
    assert line.startswith("+ ⌂ tenzir-docs tenzir/skills ")
    assert ".agents/skills.yaml" in "".join(output.split())


def test_add_rejects_all_scopes(capsys) -> None:
    assert main(["add", "-a", "tenzir/skills"]) == 2

    assert "add does not support --all" in capsys.readouterr().err


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

    assert (
        main(
            [
                "--json",
                "--manifest",
                str(path),
                "remove",
                "tenzir-docs",
                "--source",
                "tenzir/skills",
            ]
        )
        == 0
    )
    assert (
        main(["--json", "--manifest", str(path), "remove", "--source", "mavam/quarto-brief"]) == 0
    )

    payload = json.loads(capsys.readouterr().out.splitlines()[-1])
    manifest = load_manifest(path)
    assert payload["changed"] is True
    assert manifest.sources[0].source == "tenzir/skills"
    assert [skill.name for skill in manifest.sources[0].skills] == ["tenzir-ecs"]
    assert path.read_text() == "sources:\n  tenzir/skills:\n    - tenzir-ecs\n"


def test_remove_resolves_unique_skill_name(tmp_path, capsys) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  tenzir/skills:
    - tenzir-docs@main
    - tenzir-ecs
  cloudflare/skills:
    - wrangler
""",
    )

    assert main(["--json", "--manifest", str(path), "remove", "tenzir-docs"]) == 0

    payload = json.loads(capsys.readouterr().out)
    manifest = load_manifest(path)
    assert payload["changed"] is True
    assert payload["source"] == "tenzir/skills"
    assert payload["skill"] == "tenzir-docs"
    remaining = [
        (source.source, [skill.name for skill in source.skills]) for source in manifest.sources
    ]
    assert remaining == [
        ("tenzir/skills", ["tenzir-ecs"]),
        ("cloudflare/skills", ["wrangler"]),
    ]


def test_remove_source_flag_removes_whole_source(tmp_path, capsys) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  tenzir/skills:
    - tenzir-docs
  cloudflare/skills:
    - wrangler
""",
    )

    assert main(["--json", "--manifest", str(path), "remove", "--source", "tenzir/skills"]) == 0

    payload = json.loads(capsys.readouterr().out)
    manifest = load_manifest(path)
    assert payload["changed"] is True
    assert payload["source"] == "tenzir/skills"
    assert "skill" not in payload
    assert [source.source for source in manifest.sources] == ["cloudflare/skills"]


def test_remove_rejects_ambiguous_skill_name(tmp_path, capsys) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  tenzir/skills:
    - wrangler
  cloudflare/skills:
    - wrangler
""",
    )
    original = path.read_text()

    assert main(["--manifest", str(path), "remove", "wrangler"]) == 2

    assert path.read_text() == original
    error = capsys.readouterr().err
    assert '"wrangler" is ambiguous' in error
    assert "tenzir/skills@wrangler" in error
    assert "cloudflare/skills@wrangler" in error
    assert "skeel remove <skill> --source" in error
    assert "<source>" in error


def test_remove_unknown_skill_name_requires_manifest_match(tmp_path, capsys) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  tenzir/skills:
    - tenzir-docs
""",
    )
    original = path.read_text()

    assert main(["--manifest", str(path), "remove", "wrangler"]) == 2
    assert "no manifest entry matches skill: wrangler" in capsys.readouterr().err
    assert path.read_text() == original


def test_remove_resolves_user_scope_shortcut(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".agents").mkdir(parents=True)
    project.mkdir()
    user_manifest = home / ".agents" / "skills.yaml"
    user_manifest.write_text(
        """
sources:
  example/skills:
    - alpha-skill
    - beta-skill
""".strip()
    )
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    assert main(["--json", "-g", "remove", "alpha-skill"]) == 0

    payload = json.loads(capsys.readouterr().out)
    manifest = load_manifest(user_manifest)
    assert payload["changed"] is True
    assert payload["manifest"] == str(user_manifest)
    assert payload["source"] == "example/skills"
    assert payload["skill"] == "alpha-skill"
    assert [skill.name for skill in manifest.sources[0].skills] == ["beta-skill"]


def test_remove_human_output_marks_user_scope_shortcut(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".agents").mkdir(parents=True)
    project.mkdir()
    (home / ".agents" / "skills.yaml").write_text(
        """
sources:
  example/skills:
    - alpha-skill
    - beta-skill
""".strip()
    )
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    assert main(["remove", "-g", "alpha-skill"]) == 0

    output = capsys.readouterr().out
    line = " ".join(output.split())
    assert line.startswith("- ⌂ alpha-skill example/skills ")
    assert ".agents/skills.yaml" in "".join(output.split())


def test_remove_defaults_to_project_when_project_and_user_match(
    tmp_path, capsys, monkeypatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".agents").mkdir(parents=True)
    (project / ".agents").mkdir(parents=True)
    (project / ".agents" / "skills.yaml").write_text(
        """
sources:
  example/skills:
    - alpha-skill
""".strip()
    )
    (home / ".agents" / "skills.yaml").write_text(
        """
sources:
  example/skills:
    - alpha-skill
""".strip()
    )
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    assert main(["--json", "remove", "alpha-skill"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["manifest"] == ".agents/skills.yaml"
    assert "scope" not in payload
    assert load_manifest(home / ".agents" / "skills.yaml").desired_skill_names == {"alpha-skill"}
    assert load_manifest(project / ".agents" / "skills.yaml").desired_skill_names == set()


def test_remove_all_removes_project_and_user_matches(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".agents").mkdir(parents=True)
    (project / ".agents").mkdir(parents=True)
    (project / ".agents" / "skills.yaml").write_text(
        """
sources:
  example/skills:
    - alpha-skill
""".strip()
    )
    (home / ".agents" / "skills.yaml").write_text(
        """
sources:
  example/skills:
    - alpha-skill
""".strip()
    )
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    assert main(["--json", "remove", "-a", "alpha-skill"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [
        (removal["scope"], removal["source"], removal["skill"]) for removal in payload["removals"]
    ] == [
        ("project", "example/skills", "alpha-skill"),
        ("user", "example/skills", "alpha-skill"),
    ]
    assert load_manifest(project / ".agents" / "skills.yaml").desired_skill_names == set()
    assert load_manifest(home / ".agents" / "skills.yaml").desired_skill_names == set()


def test_remove_source_requires_manifest_match(tmp_path, capsys) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  tenzir/skills:
    - tenzir-docs
""",
    )
    original = path.read_text()

    assert main(["--manifest", str(path), "remove", "--source", "cloudflare/skills"]) == 2
    assert "no manifest entry matches: cloudflare/skills@*" in capsys.readouterr().err
    assert path.read_text() == original

    assert (
        main(
            [
                "--manifest",
                str(path),
                "remove",
                "tenzir-ecs",
                "--source",
                "tenzir/skills",
            ]
        )
        == 2
    )
    assert "no manifest entry matches: tenzir/skills@tenzir-ecs" in capsys.readouterr().err
    assert path.read_text() == original


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

    assert main(["--json", "list", "-a"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [(skill["scope"], skill["label"], skill["status"]) for skill in payload["skills"]] == [
        ("project", "tenzir/skills@tenzir-docs", "installed"),
        ("user", "anthropics/skills@skill-creator", "installed"),
        ("user", "cloudflare/skills@wrangler", "missing"),
        ("user", "mavam/quarto-brief@quarto", "installed"),
    ]


def test_list_includes_unmanaged_installed_skills_by_default(tmp_path, capsys, monkeypatch) -> None:
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
  cloudflare/skills:
    - wrangler
""".strip()
    )
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    async def fake_installed_skills(options, runner):
        if options.directory == project / ".agents" / "skills":
            return (
                InstalledSkill(name="tenzir-docs", path=options.directory / "tenzir-docs"),
                InstalledSkill(
                    name="obsolete-skill",
                    path=options.directory / "obsolete-skill",
                    source_url="https://github.com/example/skills",
                ),
            )
        assert options.directory == home / ".agents" / "skills"
        return (
            InstalledSkill(name="wrangler", path=options.directory / "wrangler"),
            InstalledSkill(name="local-only", path=options.directory / "local-only"),
        )

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "list"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [
        (
            skill["scope"],
            skill["label"],
            skill["status"],
            "manifest" in skill,
            skill.get("managed", True),
        )
        for skill in payload["skills"]
    ] == [
        ("project", "tenzir/skills@tenzir-docs", "installed", True, True),
        ("project", "example/skills@obsolete-skill", "installed", False, False),
    ]


def test_list_reports_installed_skills_without_manifest(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".agents" / "skills").mkdir(parents=True)
    (project / ".agents" / "skills").mkdir(parents=True)
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    async def fake_installed_skills(options, runner):
        if options.directory == project / ".agents" / "skills":
            return (InstalledSkill(name="project-only", path=options.directory / "project-only"),)
        raise AssertionError(f"unexpected skill directory: {options.directory}")

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "list"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [
        (skill["scope"], skill["label"], "manifest" in skill, skill.get("managed", True))
        for skill in payload["skills"]
    ] == [
        ("project", "project-only", False, False),
    ]


def test_list_human_output_prefixes_scope_glyph(tmp_path, capsys, monkeypatch) -> None:
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
  cloudflare/skills:
    - wrangler
""".strip()
    )
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    async def fake_installed_skills(options, runner):
        if options.directory == project / ".agents" / "skills":
            return (InstalledSkill(name="tenzir-docs", path=options.directory / "tenzir-docs"),)
        assert options.directory == home / ".agents" / "skills"
        return (InstalledSkill(name="wrangler", path=options.directory / "wrangler"),)

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["list", "-a"]) == 0

    assert capsys.readouterr().out.splitlines() == [
        "✔︎ ★ tenzir-docs tenzir/skills",
        "✔︎ ⌂ wrangler cloudflare/skills",
    ]


def test_list_human_output_single_scope_keeps_glyph(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".agents").mkdir(parents=True)
    (project / ".agents").mkdir(parents=True)
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
        if options.directory == project / ".agents" / "skills":
            return ()
        assert options.directory == home / ".agents" / "skills"
        return (InstalledSkill(name="wrangler", path=options.directory / "wrangler"),)

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["list", "-g"]) == 0

    assert capsys.readouterr().out.splitlines() == [
        "✔︎ ⌂ wrangler cloudflare/skills",
    ]


def test_detail_text_renders_version_transition_without_scope() -> None:
    from skeel.io import detail_text

    assert detail_text("main@old → main@new").plain == "main@old → main@new"
    assert detail_text(None).plain == ""


def test_status_text_renders_scope_marker_without_detail() -> None:
    terminal = Terminal()
    from skeel.io import MARKER_SUCCESS

    text = terminal.status_text(MARKER_SUCCESS, "cloudflare/skills@wrangler", scope="user")
    assert text.plain == "✔︎ ⌂ wrangler cloudflare/skills"

    text = terminal.status_text(MARKER_SUCCESS, "cloudflare/skills@wrangler", scope="project")
    assert text.plain == "✔︎ ★ wrangler cloudflare/skills"

    text = terminal.status_text(MARKER_SUCCESS, "cloudflare/skills@wrangler")
    assert text.plain == "✔︎ wrangler cloudflare/skills"


def test_status_text_renders_scope_marker_before_detail() -> None:
    terminal = Terminal()
    from skeel.io import MARKER_SKIPPED

    text = terminal.status_text(
        MARKER_SKIPPED,
        "downstairs-dawgs/clacks@clacks",
        detail="missing GitHub metadata",
        scope="user",
    )

    assert text.plain == "! ⌂ clacks downstairs-dawgs/clacks missing GitHub metadata"


def test_diff_marks_user_scope_across_project_and_user_manifests(
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
  cloudflare/skills:
    - wrangler
""".strip()
    )
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    async def fake_installed_skills(options, runner):
        return ()

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "diff", "-a"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert [(skill["scope"], skill["name"]) for skill in payload["missing"]] == [
        ("project", "tenzir-docs"),
        ("user", "wrangler"),
    ]
    assert payload["in_sync"] is False

    # The human output tags each row with its scope glyph after the marker.
    assert main(["diff", "-a"]) == 1
    assert capsys.readouterr().out.splitlines() == [
        "+ ★ tenzir-docs tenzir/skills",
        "+ ⌂ wrangler cloudflare/skills",
    ]


def test_diff_defaults_to_project_scope(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".agents").mkdir(parents=True)
    (project / ".agents").mkdir(parents=True)
    (project / ".agents" / "skills.yaml").write_text(
        """
sources:
  project/skills:
    - local-alpha
""".strip()
    )
    (home / ".agents" / "skills.yaml").write_text(
        """
sources:
  user/skills:
    - user-beta
""".strip()
    )
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    async def fake_installed_skills(options, runner):
        assert options.directory == project / ".agents" / "skills"
        return ()

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "diff"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert [(skill["scope"], skill["name"]) for skill in payload["missing"]] == [
        ("project", "local-alpha"),
    ]


def test_diff_all_warns_and_skips_shadowed_user_skill(tmp_path, capsys, monkeypatch) -> None:
    write_shadowed_scope(tmp_path, monkeypatch)

    async def fake_installed_skills(options, runner):
        return ()

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "diff", "-a"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert [(skill["scope"], skill["source"], skill["name"]) for skill in payload["missing"]] == [
        ("project", "project/skills", "wrangler"),
    ]
    assert_shadow_warning(payload)

    assert main(["diff", "-a"]) == 1
    captured = capsys.readouterr()
    assert captured.out.splitlines() == ["+ ★ wrangler project/skills"]
    error = " ".join(plain(captured.err).split())
    assert 'user/global skill "wrangler" is shadowed' in error
    assert "project scope is effective and user/global scope was skipped" in error


def test_list_all_warns_and_skips_shadowed_user_skill(tmp_path, capsys, monkeypatch) -> None:
    _, _, project_target, user_target = write_shadowed_scope(tmp_path, monkeypatch)

    async def fake_installed_skills(options, runner):
        if options.directory == project_target:
            return (InstalledSkill(name="wrangler", path=project_target / "wrangler"),)
        if options.directory == user_target:
            return (InstalledSkill(name="wrangler", path=user_target / "wrangler"),)
        raise AssertionError(f"unexpected skill directory: {options.directory}")

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "list", "-a"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [(skill["scope"], skill["label"], skill["status"]) for skill in payload["skills"]] == [
        ("project", "project/skills@wrangler", "installed"),
    ]
    assert_shadow_warning(payload)


def test_list_all_skips_shadowed_dynamic_user_source(tmp_path, capsys, monkeypatch) -> None:
    home, _, project_target, user_target = write_shadowed_scope(tmp_path, monkeypatch)
    (home / ".agents" / "skills.yaml").write_text(
        """
sources:
  cloudflare/skills:
""".strip()
    )

    async def fake_installed_skills(options, runner):
        if options.directory == project_target:
            return (InstalledSkill(name="wrangler", path=project_target / "wrangler"),)
        if options.directory == user_target:
            return (
                InstalledSkill(
                    name="wrangler",
                    path=user_target / "wrangler",
                    source_url="https://github.com/cloudflare/skills",
                ),
            )
        raise AssertionError(f"unexpected skill directory: {options.directory}")

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "list", "-a"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [(skill["scope"], skill["label"], skill["status"]) for skill in payload["skills"]] == [
        ("project", "project/skills@wrangler", "installed"),
    ]
    assert_shadow_warning(payload)


def test_list_deduplicates_project_and_user_scope_at_home(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path
    (home / ".agents").mkdir(parents=True)
    (home / ".agents" / "skills.yaml").write_text(
        """
sources:
  cloudflare/skills:
    - wrangler
""".strip()
    )
    monkeypatch.chdir(home)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)
    calls: list[Path] = []

    async def fake_installed_skills(options, runner):
        calls.append(options.directory)
        return (InstalledSkill(name="wrangler", path=options.directory / "wrangler"),)

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "list", "-a"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert calls == [home / ".agents" / "skills"]
    assert [(skill["scope"], skill["label"], skill["status"]) for skill in payload["skills"]] == [
        ("user", "cloudflare/skills@wrangler", "installed"),
    ]


def test_list_reports_single_missing_manifest_at_home(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path
    monkeypatch.chdir(home)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    assert main(["list"]) == 0

    output = capsys.readouterr().out
    assert output.count("no manifest at") == 1


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
        "+ ★ wrangler cloudflare/skills",
        "+ ★ vectorize cloudflare/skills",
        "- ★ obsolete-skill installed",
        "- ★ old-experiment installed",
    ]


def test_diff_reports_missing_dynamic_source(tmp_path, capsys, monkeypatch) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  example/skills:
""",
    )
    monkeypatch.chdir(tmp_path)

    async def fake_installed_skills(options, runner):
        return ()

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--manifest", str(path), "diff"]) == 1

    assert capsys.readouterr().out.splitlines() == [
        "+ ★ example/skills",
    ]


def test_diff_json_reports_missing_dynamic_source(tmp_path, capsys, monkeypatch) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  example/skills:
""",
    )
    monkeypatch.chdir(tmp_path)

    async def fake_installed_skills(options, runner):
        return ()

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "--manifest", str(path), "diff"]) == 1

    assert json.loads(capsys.readouterr().out) == {
        "missing": [
            {
                "name": "*",
                "source": "example/skills",
                "scope": "project",
            }
        ],
        "extra": [],
        "in_sync": False,
    }


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
    assert "✘ ★ gog openclaw/gogcli" in captured.err
    assert "failed to install skill: openclaw/gogcli@gog" in captured.err
    assert "process stdout" not in captured.out + captured.err
    assert "process stderr" in captured.err


def test_run_steps_carries_step_scope_into_results(tmp_path: Path) -> None:
    class Runner:
        async def run(self, command, **kwargs):
            return ProcessResult(command=command, returncode=0)

    runtime = Runtime(
        manifest_path=Path("manifest.yaml"),
        manifest_required=False,
        options=GhOptions(directory=tmp_path),
        runner=Runner(),
        terminal=Terminal(json_output=True),
    )
    target = tmp_path / "obsolete"
    target.mkdir()
    steps = (
        SkillStep(label="install", command=["install"], scope="user"),
        SkillStep(label="remove", command=["remove"], remove_path=target, scope="user"),
    )

    results, exit_code = asyncio.run(
        run_steps(steps, runtime, dry_run=False, dry_run_action="would install")
    )

    assert exit_code == 0
    assert [result.scope for result in results] == ["user", "user"]
    # The scope survives JSON serialization too.
    assert all(result.json()["scope"] == "user" for result in results)


def test_process_runner_terminates_cancelled_subprocess(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    terminated = tmp_path / "terminated"
    child = "\n".join(
        [
            "import pathlib",
            "import signal",
            "import sys",
            "import time",
            f"ready = pathlib.Path({str(ready)!r})",
            f"terminated = pathlib.Path({str(terminated)!r})",
            "def stop(signum, frame):",
            "    terminated.write_text('terminated')",
            "    sys.exit(0)",
            "signal.signal(signal.SIGTERM, stop)",
            "ready.write_text('ready')",
            "while True:",
            "    time.sleep(0.1)",
        ]
    )

    async def run_cancelled_process() -> None:
        runner = ProcessRunner()
        task = asyncio.create_task(runner.run([sys.executable, "-c", child], capture_output=True))
        for _ in range(100):
            if ready.exists():
                break
            await asyncio.sleep(0.01)
        assert ready.exists()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run_cancelled_process())

    assert terminated.read_text() == "terminated"


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
            dry_run_action="would install",
            default_status="installed",
        )
    )

    assert exit_code == 0
    assert [result.label for result in results] == [step.label for step in steps]
    assert runner.max_active > 1


def test_run_steps_can_remove_completed_current_progress_tasks(tmp_path: Path) -> None:
    class Runner:
        async def run(self, command, **kwargs):
            assert kwargs == {"capture_output": True}
            return ProcessResult(command=command, returncode=0)

    class RecordingProgress:
        def __init__(self) -> None:
            self.next_task = 0
            self.descriptions: dict[int, str] = {}
            self.scopes: dict[int, str] = {}
            self.removed: list[int] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            pass

        def add_task(self, description, *, total, scope=""):
            del total
            task_id = self.next_task
            self.next_task += 1
            self.descriptions[task_id] = description
            self.scopes[task_id] = scope
            return task_id

        def update(self, task_id, **kwargs) -> None:
            del task_id, kwargs

        def remove_task(self, task_id) -> None:
            self.removed.append(task_id)

    class ActiveOnlyTerminal(Terminal):
        def __init__(self) -> None:
            super().__init__(json_output=False)
            self.recording_progress = RecordingProgress()

        def live_progress_enabled(self) -> bool:
            return True

        def progress(self, *, transient: bool = False):
            assert transient is True
            return self.recording_progress

    terminal = ActiveOnlyTerminal()
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
            outcome=lambda result: StepOutcome(status="current"),
            scope="user",
        ),
        SkillStep(
            label="skipped",
            command=["skipped"],
            outcome=lambda result: StepOutcome(status="skipped"),
            scope="user",
        ),
    )

    results, exit_code = asyncio.run(
        run_steps(
            steps,
            runtime,
            dry_run=False,
            dry_run_action="would install",
            render=False,
            remove_current_progress_tasks=True,
        )
    )

    assert exit_code == 0
    assert [result.label for result in results] == ["current", "skipped"]
    removed_labels = [
        terminal.recording_progress.descriptions[task_id]
        for task_id in terminal.recording_progress.removed
    ]
    assert removed_labels == ["current"]
    assert set(terminal.recording_progress.scopes.values()) == {"user"}


def test_run_steps_stops_launching_after_apply_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("skeel.io.DEFAULT_PARALLELISM", 4)

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
            dry_run_action="would install",
            default_status="installed",
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
            dry_run_action="would install",
            default_status="installed",
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


def test_update_dry_run_prints_commands_without_json(tmp_path, capsys, monkeypatch) -> None:
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

    assert main(["--manifest", str(path), "update", "--dry-run"]) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    normalized_output = " ".join(captured.out.split())
    assert captured.out.count("↳") == 2
    assert "↳ gh skill update clacks --dir" in normalized_output
    assert "↳ gh skill update caveman --dir" in normalized_output
    assert normalized_output.count("--all") == 2


def test_update_summary_renders_changed_rows_and_tally(tmp_path, capsys, monkeypatch) -> None:
    current_names = [f"current-{index:02d}" for index in range(27)]
    manifest_sources = {
        "tenzir/skills": ["tenzir-ship"],
        "example/skills": current_names,
    }
    path = write_update_manifest(tmp_path, manifest_sources)
    home = tmp_path / "home"
    target = home / ".agents" / "skills"
    target.mkdir(parents=True)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    installed = tuple(
        installed_update_skill(target, name=name, source=source)
        for source, names in manifest_sources.items()
        for name in names
    )
    sources_by_name = {name: source for source, names in manifest_sources.items() for name in names}

    async def fake_installed_skills(options, runner):
        assert options.directory == target
        return installed

    runner = UpdateRunner(
        target,
        sources_by_name,
        updated={"tenzir-ship": "12c7aa30000"},
    )
    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)
    monkeypatch.setattr("skeel.cli.ProcessRunner", lambda: runner)

    assert main(["--manifest", str(path), "--scope", "user", "update"]) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.splitlines() == [
        "↑ ⌂ tenzir-ship tenzir/skills main@9f3e1a2 → main@12c7aa3",
        "",
        "1 updated",
        "27 current",
    ]
    assert all(not line.startswith(" ") for line in captured.err.splitlines() if line)


def test_update_summary_collapses_all_current_output(tmp_path, capsys, monkeypatch) -> None:
    skill_names = [f"current-{index:02d}" for index in range(28)]
    manifest_sources = {"example/skills": skill_names}
    path = write_update_manifest(tmp_path, manifest_sources)
    home = tmp_path / "home"
    target = home / ".agents" / "skills"
    target.mkdir(parents=True)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    installed = tuple(
        installed_update_skill(target, name=name, source="example/skills") for name in skill_names
    )
    sources_by_name = {name: "example/skills" for name in skill_names}

    async def fake_installed_skills(options, runner):
        assert options.directory == target
        return installed

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)
    monkeypatch.setattr("skeel.cli.ProcessRunner", lambda: UpdateRunner(target, sources_by_name))

    assert main(["--manifest", str(path), "--scope", "user", "update"]) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "28 current\n"


def test_update_verbose_lists_current_rows(tmp_path, capsys, monkeypatch) -> None:
    manifest_sources = {
        "downstairs-dawgs/clacks": ["clacks"],
        "openclaw/gogcli": ["gog"],
        "tenzir/skills": ["tenzir-ship"],
    }
    path = write_update_manifest(tmp_path, manifest_sources)
    home = tmp_path / "home"
    target = home / ".agents" / "skills"
    target.mkdir(parents=True)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    installed = tuple(
        installed_update_skill(target, name=name, source=source)
        for source, names in manifest_sources.items()
        for name in names
    )
    sources_by_name = {name: source for source, names in manifest_sources.items() for name in names}

    async def fake_installed_skills(options, runner):
        assert options.directory == target
        return installed

    runner = UpdateRunner(
        target,
        sources_by_name,
        updated={"tenzir-ship": "12c7aa30000"},
    )
    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)
    monkeypatch.setattr("skeel.cli.ProcessRunner", lambda: runner)

    assert main(["--manifest", str(path), "--scope", "user", "update", "-v"]) == 0

    err = capsys.readouterr().err
    assert "↑ ⌂ tenzir-ship tenzir/skills main@9f3e1a2 → main@12c7aa3" in err
    assert "· ⌂ clacks downstairs-dawgs/clacks" in err
    assert "· ⌂ gog openclaw/gogcli" in err
    assert "1 updated" in err
    assert "2 current" in err


def test_update_summary_counts_skips_and_failures(tmp_path, capsys, monkeypatch) -> None:
    manifest_sources = {
        "tenzir/skills": ["tenzir-ship"],
        "mattpocock/skills": ["caveman"],
        "openclaw/openclaw": ["openhue"],
        "example/skills": ["steady"],
    }
    path = write_update_manifest(tmp_path, manifest_sources)
    home = tmp_path / "home"
    target = home / ".agents" / "skills"
    target.mkdir(parents=True)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    installed = tuple(
        installed_update_skill(target, name=name, source=source)
        for source, names in manifest_sources.items()
        for name in names
    )
    sources_by_name = {name: source for source, names in manifest_sources.items() for name in names}

    async def fake_installed_skills(options, runner):
        assert options.directory == target
        return installed

    runner = UpdateRunner(
        target,
        sources_by_name,
        updated={"tenzir-ship": "12c7aa30000"},
        skipped={"caveman"},
        failed={"openhue"},
    )
    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)
    monkeypatch.setattr("skeel.cli.ProcessRunner", lambda: runner)

    assert main(["--manifest", str(path), "--scope", "user", "update"]) == 7

    err = capsys.readouterr().err
    assert "↑ ⌂ tenzir-ship tenzir/skills main@9f3e1a2 → main@12c7aa3" in err
    assert "! ⌂ caveman mattpocock/skills pinned" in err
    assert "1 updated" in err
    assert "1 skipped" in err
    assert "1 failed" in err
    assert "1 current" in err
    assert "failed to update skills: openclaw/openclaw@openhue" in err
    assert "  gh failed" in err


def test_update_deduplicates_project_and_user_scope_at_home(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path
    target = home / ".agents" / "skills"
    target.mkdir(parents=True)
    (home / ".agents" / "skills.yaml").write_text(
        """
sources:
  cloudflare/skills:
    - wrangler
  tenzir/skills:
    - tenzir-docs
""".strip()
    )
    monkeypatch.chdir(home)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)
    calls: list[Path] = []

    async def fake_installed_skills(options, runner):
        calls.append(options.directory)
        return (
            InstalledSkill(name="wrangler", path=target / "wrangler"),
            InstalledSkill(name="tenzir-docs", path=target / "tenzir-docs"),
        )

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "update", "--dry-run", "-a"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert calls == [target]
    assert [step["label"] for step in payload["steps"]] == [
        "tenzir/skills@tenzir-docs",
        "cloudflare/skills@wrangler",
    ]


def test_update_defaults_to_project_scope(tmp_path, capsys, monkeypatch) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project_target = project / ".agents" / "skills"
    user_target = home / ".agents" / "skills"
    project_target.mkdir(parents=True)
    user_target.mkdir(parents=True)
    (project / ".agents" / "skills.yaml").write_text(
        """
sources:
  project/skills:
    - local-alpha
""".strip()
    )
    (home / ".agents" / "skills.yaml").write_text(
        """
sources:
  user/skills:
    - user-beta
""".strip()
    )
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    async def fake_installed_skills(options, runner):
        del runner
        if options.directory == project_target:
            return (InstalledSkill(name="local-alpha", path=project_target / "local-alpha"),)
        raise AssertionError(f"unexpected skill directory: {options.directory}")

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "update", "--dry-run"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [(step["label"], step["scope"]) for step in payload["steps"]] == [
        ("project/skills@local-alpha", "project"),
    ]


def test_update_schedules_project_and_user_scopes_together(tmp_path, capsys, monkeypatch) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project_target = project / ".agents" / "skills"
    user_target = home / ".agents" / "skills"
    project_target.mkdir(parents=True)
    user_target.mkdir(parents=True)
    (project / ".agents" / "skills.yaml").write_text(
        """
sources:
  project/skills:
    - local-alpha
""".strip()
    )
    (home / ".agents" / "skills.yaml").write_text(
        """
sources:
  user/skills:
    - user-beta
""".strip()
    )
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)

    async def fake_installed_skills(options, runner):
        del runner
        if options.directory == project_target:
            return (InstalledSkill(name="local-alpha", path=project_target / "local-alpha"),)
        if options.directory == user_target:
            return (InstalledSkill(name="user-beta", path=user_target / "user-beta"),)
        raise AssertionError(f"unexpected skill directory: {options.directory}")

    calls = []

    async def fake_run_steps(steps, runtime, **kwargs):
        calls.append((tuple(steps), runtime, kwargs))
        return (
            [
                StepResult(
                    label=step.label,
                    command=step.command,
                    returncode=0,
                    status="current",
                    scope=step.scope,
                )
                for step in steps
            ],
            0,
        )

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)
    monkeypatch.setattr("skeel.cli.run_steps", fake_run_steps)

    assert main(["--json", "update", "-a"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert len(calls) == 1
    steps, runtime, kwargs = calls[0]
    assert runtime.options.directory == project_target
    assert kwargs == {
        "dry_run": False,
        "dry_run_action": "would update",
        "keep_going": True,
        "render": False,
        "remove_current_progress_tasks": True,
    }
    assert [(step.label, step.scope) for step in steps] == [
        ("project/skills@local-alpha", "project"),
        ("user/skills@user-beta", "user"),
    ]
    assert [(step["label"], step["scope"]) for step in payload["steps"]] == [
        ("project/skills@local-alpha", "project"),
        ("user/skills@user-beta", "user"),
    ]


def test_update_all_warns_and_skips_shadowed_user_skill(tmp_path, capsys, monkeypatch) -> None:
    _, _, project_target, user_target = write_shadowed_scope(tmp_path, monkeypatch)

    async def fake_installed_skills(options, runner):
        del runner
        if options.directory == project_target:
            return (InstalledSkill(name="wrangler", path=project_target / "wrangler"),)
        if options.directory == user_target:
            return (InstalledSkill(name="wrangler", path=user_target / "wrangler"),)
        raise AssertionError(f"unexpected skill directory: {options.directory}")

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "update", "-a", "--dry-run"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [(step["scope"], step["label"]) for step in payload["steps"]] == [
        ("project", "project/skills@wrangler"),
    ]
    assert_shadow_warning(payload)


def test_update_all_project_selector_requires_effective_skill_installed(
    tmp_path, capsys, monkeypatch
) -> None:
    _, _, project_target, user_target = write_shadowed_scope(tmp_path, monkeypatch)

    async def fake_installed_skills(options, runner):
        del runner
        if options.directory == project_target:
            return ()
        if options.directory == user_target:
            return (InstalledSkill(name="wrangler", path=user_target / "wrangler"),)
        raise AssertionError(f"unexpected skill directory: {options.directory}")

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["update", "-a", "project/skills", "wrangler", "--dry-run"]) == 2
    assert "selected skill is not installed: project/skills@wrangler" in capsys.readouterr().err


def test_update_all_user_selector_skips_shadowed_skill_but_user_scope_can_force_it(
    tmp_path, capsys, monkeypatch
) -> None:
    _, _, project_target, user_target = write_shadowed_scope(tmp_path, monkeypatch)

    async def fake_installed_skills(options, runner):
        del runner
        if options.directory == project_target:
            return (InstalledSkill(name="wrangler", path=project_target / "wrangler"),)
        if options.directory == user_target:
            return (InstalledSkill(name="wrangler", path=user_target / "wrangler"),)
        raise AssertionError(f"unexpected skill directory: {options.directory}")

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "update", "-a", "cloudflare/skills", "wrangler", "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["steps"] == []
    assert_shadow_warning(payload)

    assert main(["--json", "-g", "update", "cloudflare/skills", "wrangler", "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "warnings" not in payload
    assert [(step["scope"], step["label"]) for step in payload["steps"]] == [
        ("user", "cloudflare/skills@wrangler"),
    ]


def test_update_source_selector_only_updates_selected_manifest_source(
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
            InstalledSkill(name="wrangler", path=target / "wrangler"),
            InstalledSkill(name="tenzir-ecs", path=target / "tenzir-ecs"),
            InstalledSkill(name="clacks", path=target / "clacks"),
            InstalledSkill(name="tenzir-docs", path=target / "tenzir-docs"),
        )

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert main(["--json", "--manifest", str(path), "update", "tenzir/skills", "--dry-run"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [step["label"] for step in payload["steps"]] == [
        "tenzir/skills@tenzir-docs",
        "tenzir/skills@tenzir-ecs",
    ]


def test_update_skill_selector_only_updates_selected_manifest_skill(
    tmp_path, capsys, monkeypatch
) -> None:
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
                "update",
                "tenzir/skills",
                "tenzir-ecs",
                "--dry-run",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert [step["label"] for step in payload["steps"]] == ["tenzir/skills@tenzir-ecs"]
    assert payload["steps"][0]["command"] == [
        "gh",
        "skill",
        "update",
        "tenzir-ecs",
        "--dir",
        str(target),
        "--all",
    ]


def test_update_selector_requires_manifest_match(tmp_path, capsys, monkeypatch) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  tenzir/skills:
    - tenzir-docs
""",
    )
    monkeypatch.chdir(tmp_path)

    assert main(["--manifest", str(path), "update", "cloudflare/skills", "--dry-run"]) == 2
    assert "no manifest entry matches: cloudflare/skills@*" in capsys.readouterr().err

    assert (
        main(["--manifest", str(path), "update", "tenzir/skills", "tenzir-ecs", "--dry-run"]) == 2
    )
    assert "no manifest entry matches: tenzir/skills@tenzir-ecs" in capsys.readouterr().err


def test_update_selector_requires_installed_skill(tmp_path, capsys, monkeypatch) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  tenzir/skills:
    - tenzir-docs
""",
    )
    target = tmp_path / ".agents" / "skills"
    target.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    async def fake_installed_skills(options, runner):
        assert options.directory == target
        return ()

    monkeypatch.setattr("skeel.cli.installed_skills", fake_installed_skills)

    assert (
        main(
            [
                "--manifest",
                str(path),
                "update",
                "tenzir/skills",
                "tenzir-docs",
                "--dry-run",
            ]
        )
        == 2
    )

    assert "selected skill is not installed: tenzir/skills@tenzir-docs" in capsys.readouterr().err
