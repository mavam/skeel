from pathlib import Path

from skeel.backends import BackendOptions
from skeel.cli import build_parser, command_apply, command_update, diff_sets, iter_install_plan
from skeel.manifest import Manifest, SkillSpec, SourceSpec


def test_iter_install_plan_combines_backend_and_manual_steps() -> None:
    manifest = Manifest(
        path=Path("manifest.yaml"),
        sources=(
            SourceSpec(
                source="tenzir/skills",
                skills=(SkillSpec(spec="tenzir-docs", name="tenzir-docs"),),
            ),
            SourceSpec(source="mavam/quarto-brief", skills=(), install_all=True),
            SourceSpec(
                source=None,
                skills=(SkillSpec(spec="clacks", name="clacks"),),
                install=(("uvx", "--from", "slack-clacks", "clacks", "skill"),),
            ),
        ),
    )

    steps = list(iter_install_plan(manifest, BackendOptions(agent="codex", scope="user")))

    assert [step.command for step in steps] == [
        [
            "gh",
            "skill",
            "install",
            "tenzir/skills",
            "tenzir-docs",
            "--agent",
            "codex",
            "--scope",
            "user",
            "--force",
        ],
        [
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
        ],
        ["uvx", "--from", "slack-clacks", "clacks", "skill"],
    ]


def test_diff_reports_missing_and_extra_skills(monkeypatch) -> None:
    manifest = Manifest(
        path=Path("manifest.yaml"),
        sources=(
            SourceSpec(
                source="tenzir/skills",
                skills=(SkillSpec(spec="tenzir-docs", name="tenzir-docs"),),
            ),
        ),
    )
    monkeypatch.setattr("skeel.cli.installed_skill_names", lambda target: {"wrangler"})

    assert diff_sets(manifest, BackendOptions()) == (["tenzir-docs"], ["wrangler"])


def test_diff_suppresses_extras_when_manifest_has_dynamic_sources(monkeypatch) -> None:
    manifest = Manifest(
        path=Path("manifest.yaml"),
        sources=(
            SourceSpec(
                source="tenzir/skills",
                skills=(SkillSpec(spec="tenzir-docs", name="tenzir-docs"),),
            ),
            SourceSpec(source="mavam/quarto-brief", skills=(), install_all=True),
        ),
    )
    monkeypatch.setattr(
        "skeel.cli.installed_skill_names",
        lambda target: {"tenzir-docs", "quarto-brief"},
    )

    assert diff_sets(manifest, BackendOptions()) == ([], [])


def test_dry_run_parses_before_or_after_mutating_command() -> None:
    parser = build_parser()

    for command in ["apply", "sync", "update"]:
        before = parser.parse_args(["--dry-run", command])
        after = parser.parse_args([command, "--dry-run"])

        assert before.dry_run is True
        assert after.dry_run is True


def test_apply_dry_run_message(capsys, monkeypatch) -> None:
    manifest = Manifest(
        path=Path("manifest.yaml"),
        sources=(
            SourceSpec(
                source="tenzir/skills",
                skills=(SkillSpec(spec="tenzir-docs", name="tenzir-docs"),),
            ),
        ),
    )
    monkeypatch.setattr("skeel.cli.print_diff", lambda *args, **kwargs: False)

    assert command_apply(manifest, BackendOptions(agent="codex"), dry_run=True) == 0

    output = capsys.readouterr().out
    assert "Would install tenzir/skills/tenzir-docs" in output
    assert "Dry run complete." in output
    assert "Skills applied." not in output


def test_update_dry_run_message(capsys, monkeypatch) -> None:
    manifest = Manifest(
        path=Path("manifest.yaml"),
        sources=(SourceSpec(source="tenzir/skills", skills=(), install_all=True),),
    )
    monkeypatch.setattr("skeel.cli.print_diff", lambda *args, **kwargs: False)

    assert command_update(manifest, BackendOptions(agent="codex"), dry_run=True) == 0

    output = capsys.readouterr().out
    assert "Would update skills" in output
    assert "Dry run complete." in output
    assert "Skills updated." not in output
