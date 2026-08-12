from pathlib import Path

import pytest

from skeel.targets import (
    AGENT_HOSTS,
    find_agent,
    git_root,
    resolve_target,
)


def test_universal_project_target_uses_cwd(tmp_path: Path) -> None:
    target = resolve_target(scope="project", cwd=tmp_path, home=tmp_path / "home")
    assert target.directory == tmp_path / ".agents" / "skills"
    assert target.scope == "project"
    assert target.agent == "universal"
    assert target.universal


def test_universal_user_target_uses_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    target = resolve_target(scope="user", cwd=tmp_path, home=home)
    assert target.directory == home / ".agents" / "skills"
    assert target.scope == "user"


def test_explicit_universal_project_target_keeps_cwd_anchor(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    nested = repo / "nested"
    nested.mkdir(parents=True)
    (repo / ".git").mkdir()

    target = resolve_target(scope="project", agent="universal", cwd=nested, home=tmp_path)
    assert target.directory == nested / ".agents" / "skills"
    assert target.agent == "universal"
    assert target.universal


def test_agent_project_target_anchors_at_git_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    subdir = repo / "src" / "nested"
    subdir.mkdir(parents=True)
    (repo / ".git").mkdir()

    target = resolve_target(scope="project", agent="claude-code", cwd=subdir, home=tmp_path)
    assert target.directory == repo / ".claude" / "skills"
    assert target.agent == "claude-code"
    assert target.scope == "project"


def test_agent_project_target_falls_back_to_cwd_outside_repo(tmp_path: Path) -> None:
    target = resolve_target(scope="project", agent="pi", cwd=tmp_path, home=tmp_path / "home")
    assert target.directory == tmp_path / ".pi" / "skills"


def test_agent_user_target_uses_registry_user_dir(tmp_path: Path) -> None:
    home = tmp_path / "home"
    target = resolve_target(scope="user", agent="pi", cwd=tmp_path, home=home)
    assert target.directory == home / ".pi" / "agent" / "skills"
    assert target.scope == "user"


def test_claude_code_user_target_honors_config_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))
    target = resolve_target(scope="user", agent="claude-code", cwd=tmp_path, home=tmp_path)
    assert target.directory == tmp_path / "claude-config" / "skills"


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ("~/claude-config", Path("claude-config/skills")),
        ("claude-config", Path("claude-config/skills")),
    ],
)
def test_claude_code_user_target_expands_config_dir(
    tmp_path: Path, monkeypatch, config: str, expected: Path
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", config)

    target = resolve_target(scope="user", agent="claude-code", cwd=tmp_path, home=home)

    assert target.directory == home / expected


def test_explicit_directory_is_custom_scope(tmp_path: Path) -> None:
    target = resolve_target(
        scope="project",
        agent=None,
        directory=str(tmp_path / "custom"),
        cwd=tmp_path,
        home=tmp_path,
    )
    assert target.directory == tmp_path / "custom"
    assert target.scope == "custom"
    assert target.agent is None


def test_unknown_agent_error_is_actionable() -> None:
    with pytest.raises(ValueError, match="skeel agents"):
        find_agent("hal-9000")


def test_git_root_finds_enclosing_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    nested = repo / "a" / "b"
    nested.mkdir(parents=True)
    (repo / ".git").mkdir()
    assert git_root(nested) == repo.resolve()
    assert git_root(tmp_path) is None


def test_registry_ids_are_unique() -> None:
    ids = [host.id for host in AGENT_HOSTS]
    assert len(ids) == len(set(ids))
    assert "claude-code" in ids
    assert "universal" in ids
