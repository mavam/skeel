from pathlib import Path
from types import SimpleNamespace

from skeel.backends import (
    BackendOptions,
    GhSkillBackend,
    desired_skill_names,
    installed_skill_names,
    manual_install_steps,
    quote_command,
)
from skeel.manifest import Manifest, SkillSpec, SourceSpec


def test_gh_install_step_uses_universal_directory_by_default(monkeypatch) -> None:
    source = SourceSpec(
        source="openclaw/gogcli",
        skills=(SkillSpec(spec="gog", name="gog"),),
    )
    monkeypatch.setattr(
        "skeel.backends.universal_skills_dir",
        lambda scope: Path("/tmp/skills"),
    )

    step = GhSkillBackend().install_steps(
        source,
        BackendOptions(),
    )[0]

    assert step.command == [
        "gh",
        "skill",
        "install",
        "openclaw/gogcli",
        "gog",
        "--dir",
        "/tmp/skills",
        "--force",
    ]


def test_gh_install_all_step() -> None:
    source = SourceSpec(
        source="mavam/quarto-brief",
        skills=(),
        install_all=True,
    )

    step = GhSkillBackend().install_steps(
        source,
        BackendOptions(agent="codex", scope="user"),
    )[0]

    assert step.command == [
        "gh",
        "skill",
        "install",
        "mavam/quarto-brief",
        "--all",
        "--agent",
        "codex",
        "--scope",
        "user",
        "--force",
    ]


def test_manual_install_steps() -> None:
    source = SourceSpec(
        source=None,
        skills=(SkillSpec(spec="clacks", name="clacks"),),
        install=(("uvx", "--from", "slack-clacks", "clacks", "skill", "--mode", "universal"),),
    )

    steps = manual_install_steps(source)

    assert steps[0].label == "clacks"
    assert steps[0].command == [
        "uvx",
        "--from",
        "slack-clacks",
        "clacks",
        "skill",
        "--mode",
        "universal",
    ]


def test_installed_skill_names_uses_backend_options_for_named_agent(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        assert kwargs == {"check": False, "capture_output": True, "text": True}
        return SimpleNamespace(returncode=0, stdout='[{"skillName": "gog"}]', stderr="")

    monkeypatch.setattr("skeel.backends.subprocess.run", fake_run)

    names = installed_skill_names(BackendOptions(agent="codex", scope="user"))

    assert names == {"gog"}
    assert calls == [
        [
            "gh",
            "skill",
            "list",
            "--json",
            "skillName",
            "--agent",
            "codex",
            "--scope",
            "user",
        ]
    ]


def test_installed_skill_names_uses_universal_directory(monkeypatch) -> None:
    calls: list[list[str]] = []
    directory = Path("/tmp/skills")

    def fake_run(command, **kwargs):
        calls.append(command)
        assert kwargs == {"check": False, "capture_output": True, "text": True}
        return SimpleNamespace(returncode=0, stdout='[{"skillName": "gog"}]', stderr="")

    monkeypatch.setattr("skeel.backends.subprocess.run", fake_run)
    monkeypatch.setattr(Path, "exists", lambda self: self == directory)
    monkeypatch.setattr(
        "skeel.backends.universal_skills_dir",
        lambda scope: directory,
    )

    assert installed_skill_names(BackendOptions()) == {"gog"}
    assert calls == [
        [
            "gh",
            "skill",
            "list",
            "--json",
            "skillName",
            "--dir",
            "/tmp/skills",
        ]
    ]


def test_installed_skill_names_treats_missing_directory_as_empty(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout='[{"skillName": "gog"}]', stderr="")

    monkeypatch.setattr("skeel.backends.subprocess.run", fake_run)
    monkeypatch.setattr(
        "skeel.backends.universal_skills_dir",
        lambda scope: Path("/tmp/missing-skills"),
    )

    assert installed_skill_names(BackendOptions()) == set()
    assert calls == []


def test_desired_skill_names() -> None:
    manifest = Manifest(
        path=Path("manifest.yaml"),
        sources=(
            SourceSpec(
                source="openclaw/gogcli",
                skills=(SkillSpec(spec="gog", name="gog"),),
            ),
        ),
    )

    names = desired_skill_names(manifest)

    assert names == {"gog"}


def test_quote_command() -> None:
    assert quote_command(["gh", "skill", "install", "owner/repo", "skills/foo/SKILL.md"]) == (
        "gh skill install owner/repo skills/foo/SKILL.md"
    )
