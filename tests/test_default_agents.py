import json
from pathlib import Path

import pytest

from skeel.cli import main
from skeel.gh import InstalledSkill
from skeel.manifest import load_manifest, parse_manifest_data


@pytest.mark.parametrize("agents", [None, [], "claude-code", [1], ["unknown"]])
def test_invalid_agents(agents):
    with pytest.raises(ValueError):
        parse_manifest_data({"agents": agents}, Path("skills.yaml"))


def test_duplicate_agents_are_collapsed():
    manifest = parse_manifest_data(
        {"agents": ["universal", "claude-code", "universal"]}, Path("skills.yaml")
    )
    assert manifest.agents == ("universal", "claude-code")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    (home / ".agents").mkdir(parents=True)
    path = home / ".agents/skills.yaml"
    path.write_text("agents: [universal, claude-code]\nsources:\n  example/skills:\n    - helper\n")
    monkeypatch.chdir(project)
    monkeypatch.setattr("skeel.cli.Path.home", lambda: home)
    monkeypatch.delenv("SKEEL_MANIFEST", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    return home, project, path


@pytest.mark.parametrize("operation", ["apply", "update", "diff", "list"])
def test_commands_use_default_agents(setup, monkeypatch, capsys, operation):
    home, _, _ = setup
    seen = []

    async def installed(target, runner):
        seen.append(target.directory)
        if operation == "update":
            return (
                InstalledSkill(
                    name="helper",
                    path=target.directory / "helper",
                    source_url="https://github.com/example/skills",
                ),
            )
        return ()

    monkeypatch.setattr("skeel.cli.installed_skills", installed)
    assert main(["-g", "--json", operation, "--dry-run"]) == (1 if operation == "diff" else 0)
    assert seen == [home / ".agents/skills", home / ".claude/skills"]
    payload = json.loads(capsys.readouterr().out)
    if operation in ("apply", "update"):
        assert len(payload["steps"]) == 2
        assert [step["agent"] for step in payload["steps"]] == ["universal", "claude-code"]
        assert [step["directory"] for step in payload["steps"]] == [
            str(home / ".agents/skills"),
            str(home / ".claude/skills"),
        ]


@pytest.mark.parametrize("selector", [["--agent", "universal"], ["--dir", "custom"]])
def test_explicit_target_overrides_defaults(setup, monkeypatch, capsys, selector):
    home, _, _ = setup
    seen = []

    async def installed(target, runner):
        seen.append(target.directory)
        return ()

    monkeypatch.setattr("skeel.cli.installed_skills", installed)
    assert main(["-g", *selector, "apply", "--dry-run"]) == (2 if selector[0] == "--dir" else 0)
    if selector[0] == "--dir":
        # --dir is a complete target; select the manifest explicitly instead of -g.
        assert main(["-m", str(home / ".agents/skills.yaml"), *selector, "apply", "--dry-run"]) == 0
        assert seen == [Path("custom")]
    else:
        assert seen == [home / ".agents/skills"]


def test_shared_directories_are_processed_once(setup, monkeypatch, capsys):
    home, _, path = setup
    path.write_text(path.read_text().replace("universal, claude-code", "universal, cline, warp"))
    seen = []

    async def installed(target, runner):
        seen.append(target.directory)
        return ()

    monkeypatch.setattr("skeel.cli.installed_skills", installed)
    assert main(["-g", "apply", "--dry-run"]) == 0
    assert seen == [home / ".agents/skills"]


def test_symlinked_targets_are_processed_once(setup, monkeypatch, capsys):
    home, _, _ = setup
    (home / ".agents/skills").mkdir()
    (home / ".claude").mkdir()
    (home / ".claude/skills").symlink_to(home / ".agents/skills", target_is_directory=True)
    seen = []

    async def installed(target, runner):
        seen.append(target.directory)
        return ()

    monkeypatch.setattr("skeel.cli.installed_skills", installed)
    assert main(["-g", "apply", "--dry-run"]) == 0
    assert seen == [home / ".agents/skills"]


@pytest.mark.parametrize("operation", ["add", "remove"])
def test_manifest_edits_apply_to_both_agents(setup, monkeypatch, capsys, operation):
    home, _, path = setup
    seen = []

    async def installed(target, runner):
        seen.append(target.directory)
        return ()

    monkeypatch.setattr("skeel.cli.installed_skills", installed)
    args = ["add", "example/skills", "another"] if operation == "add" else ["remove", "helper"]
    original = path.read_text()
    assert main(["-g", *args, "--apply", "--dry-run", "--json"]) == 0
    assert seen == [home / ".agents/skills", home / ".claude/skills"]
    assert path.read_text() == original
    assert load_manifest(path).agents == ("universal", "claude-code")


def test_scopes_keep_shadowing_per_agent(setup, monkeypatch, capsys):
    home, project, _ = setup
    (project / ".agents").mkdir()
    (project / ".agents/skills.yaml").write_text(
        "agents: [universal, claude-code]\nsources:\n  example/skills:\n    - helper\n"
    )

    async def installed(target, runner):
        return ()

    monkeypatch.setattr("skeel.cli.installed_skills", installed)
    assert main(["-a", "apply", "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    # Universal user skills are shadowed; Claude's user copy is still installed.
    assert len(payload["steps"]) == 3
    assert {warning["type"] for warning in payload["warnings"]} == {
        "shadowed-skill",
        "duplicate-skill",
    }


def test_remove_all_edits_each_manifest_once(setup, monkeypatch, capsys):
    _, _, path = setup
    from skeel import cli

    original_remove = cli.remove_manifest_source
    calls = []

    def remove(*args, **kwargs):
        calls.append(args[0])
        return original_remove(*args, **kwargs)

    monkeypatch.setattr(cli, "remove_manifest_source", remove)
    assert main(["-a", "remove", "helper", "--json"]) == 0
    assert calls == [path]
    assert load_manifest(path).agents == ("universal", "claude-code")
    assert load_manifest(path).sources == ()


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("json_output", [False, True])
def test_custom_update_uses_each_target(setup, monkeypatch, capsys, dry_run, json_output):
    from skeel.io import ProcessResult

    home, _, path = setup
    path.write_text(
        "agents: [universal, claude-code]\nsources:\n  rex:\n"
        "    skills: [rex]\n    install: [[generate-rex]]\n"
    )
    calls = []

    async def installed(target, runner):
        skill = target.directory / "rex"
        skill.mkdir(parents=True, exist_ok=True)
        (skill / "SKILL.md").write_text("---\nname: rex\n---\n# Rex\n")
        return (InstalledSkill(name="rex", path=skill),)

    async def run(self, command, *, capture_output, env):
        assert command == ["generate-rex"]
        calls.append((env["SKEEL_AGENT"], env["SKEEL_SKILLS_DIR"]))
        return ProcessResult(command=command, returncode=0)

    monkeypatch.setattr("skeel.cli.installed_skills", installed)
    monkeypatch.setattr("skeel.gh.ProcessRunner.run", run)
    args = ["-g", "update", "rex", "-v"]
    if dry_run:
        args.append("--dry-run")
    if json_output:
        args.append("--json")
    assert main(args) == 0
    expected = [
        ("universal", str(home / ".agents/skills")),
        ("claude-code", str(home / ".claude/skills")),
    ]
    assert calls == ([] if dry_run else expected)
    captured = capsys.readouterr()
    if json_output:
        assert captured.err == ""
        payload = json.loads(captured.out)
        assert [(step["agent"], step["directory"]) for step in payload["steps"]] == expected
        assert all(step["label"] == "rex@*" for step in payload["steps"])
        if not dry_run:
            assert all(step["status"] == "current" for step in payload["steps"])
    else:
        output = " ".join((captured.out if dry_run else captured.err).split())
        assert "missing GitHub metadata" not in output
        assert "universal" in output
        assert "claude-code" in output
        assert "skills" not in output
        assert str(home) not in output
        if not dry_run:
            assert output.count("= ⌂ rex custom installer") == 1
            assert "universal, claude-code" in output
            assert "universal, claude-code: 2 up to date" in output


def test_custom_skill_selector_refreshes_and_verifies_whole_source(setup, monkeypatch, capsys):
    from skeel.io import ProcessResult

    home, _, path = setup
    path.write_text(
        "sources:\n  local:\n    skills:\n      - alpha\n      - name: beta\n"
        "        frontmatter: {description: Managed}\n    install: [[generate]]\n"
    )
    target = home / ".agents/skills"
    for name in ("alpha", "beta"):
        (target / name).mkdir(parents=True)
        (target / name / "SKILL.md").write_text(f"---\nname: {name}\n---\n# Original\n")

    async def installed(options, runner):
        return tuple(InstalledSkill(name=name, path=target / name) for name in ("alpha", "beta"))

    async def run(self, command, **kwargs):
        assert command == ["generate"]
        return ProcessResult(command=command, returncode=0)

    monkeypatch.setattr("skeel.cli.installed_skills", installed)
    monkeypatch.setattr("skeel.gh.ProcessRunner.run", run)
    assert main(["-g", "update", "local", "alpha", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["steps"]) == 1
    assert payload["steps"][0]["status"] == "updated"
    assert "description: Managed" in (target / "beta/SKILL.md").read_text()
