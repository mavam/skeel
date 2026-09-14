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
