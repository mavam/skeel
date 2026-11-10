from dataclasses import replace
from pathlib import Path

import pytest
from rich.console import Console
from rich.progress import Progress

from skeel.gh import SkillStep, scoped_steps
from skeel.io import (
    MARKER_UPDATED,
    StepDescriptionColumn,
    StepResult,
    Terminal,
    append_targets,
    collapse_update_rows,
    target_label,
)
from skeel.targets import SkillTarget


@pytest.fixture
def targets(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return (
        SkillTarget(tmp_path / ".agents/skills", scope="user", agent="universal"),
        SkillTarget(tmp_path / ".claude/skills", scope="user", agent="claude-code"),
    )


def updated(target, **kwargs):
    return replace(
        StepResult(
            label="rex@*",
            command=[],
            returncode=0,
            status="updated",
            detail="custom installer",
            scope="user",
            target=target,
        ),
        **kwargs,
    )


def test_identical_results_share_a_row_but_counts_remain_per_operation(targets, capsys):
    Terminal().render_update_summary([updated(target) for target in targets], verbose=False)
    output = capsys.readouterr().err
    normalized = " ".join(output.split())
    assert "~/" not in output
    assert str(Path.home()) not in output
    assert normalized.count("↑ ⌂ rex custom installer universal, claude-code") == 1
    assert "2 updated" in output
    assert "2 operations: 2 updated  universal, claude-code" in output
    assert "[" not in output
    assert "]" not in output


@pytest.mark.parametrize("verbose", [False, True])
def test_different_outcomes_stay_separate(targets, capsys, verbose):
    results = [updated(targets[0]), updated(targets[1], status="current")]
    Terminal().render_update_summary(results, verbose=verbose)
    output = capsys.readouterr().err
    normalized = " ".join(output.split())
    assert "↑ ⌂ rex custom installer universal" in normalized
    assert ("= ⌂ rex custom installer claude-code" in normalized) == verbose
    assert "universal, claude-code" not in output.split("\n\n", 1)[0]
    assert "1 updated" in output
    assert "1 current" in output


@pytest.mark.parametrize(
    "different",
    [
        {"label": "other@*"},
        {"scope": "project"},
        {"detail": "main@old → main@new"},
        {"status": "skipped", "detail": "pinned"},
        {"returncode": 1, "stderr": "failed"},
        {"warnings": ("could not prune",)},
        {"removed_paths": (Path("removed"),)},
    ],
)
def test_collapse_preserves_distinct_results(targets, different):
    first = updated(targets[0])
    second = updated(targets[1], **different)
    assert collapse_update_rows([first, second]) == [[first], [second]]


def test_collapse_never_hides_repeated_operations_in_one_target(targets):
    first = updated(targets[0])
    assert collapse_update_rows([first, first]) == [[first], [first]]


def test_failures_remain_individual_even_with_the_same_diagnostic(targets, capsys):
    results = [updated(target, returncode=1, stderr="failed") for target in targets]
    terminal = Terminal()
    terminal.render_update_summary(results, verbose=False)
    output = capsys.readouterr().err
    normalized = " ".join(output.split())
    assert "✘ ⌂ rex failed universal" in normalized
    assert "✘ ⌂ rex failed claude-code" in normalized
    assert "2 failed" in output
    assert "universal, claude-code" not in output.split("\n\n", 1)[0]
    terminal.failure_output(results[1])
    output = capsys.readouterr().err
    assert "  claude-code\n" in output
    assert "skills" not in output
    assert "  failed" in output


def test_identical_warnings_are_deduplicated_without_losing_target_context(targets, capsys):
    results = [updated(target, warnings=("could not prune",)) for target in targets]
    Terminal().render_update_summary(results, verbose=False)
    output = capsys.readouterr().err
    assert output.count("could not prune") == 1
    assert "could not prune  universal, claude-code" in output


def test_scope_distinguishes_the_same_agent_without_paths(targets, capsys):
    user = targets[1]
    project = replace(user, directory=Path(".claude/skills"), scope="project")
    results = [updated(user), updated(project, scope="project")]
    Terminal().render_update_summary(results, verbose=False)
    output = capsys.readouterr().err
    normalized = " ".join(output.split())
    assert "↑ ⌂ rex custom installer claude-code" in normalized
    assert "↑ ★ rex custom installer claude-code" in normalized
    assert ".claude/skills" not in output


def test_single_target_stays_compact(targets, capsys):
    Terminal().render_update_summary([updated(targets[0])], verbose=False)
    assert capsys.readouterr().err == (
        "↑ ⌂ rex  custom installer  universal\n\n1 updated  universal\n"
    )


@pytest.mark.parametrize("width", [40, 60, 100])
def test_plain_output_keeps_targets_readable_at_narrow_widths(targets, capsys, monkeypatch, width):
    monkeypatch.setenv("NO_COLOR", "1")
    terminal = Terminal()
    terminal.error_console.width = width
    terminal.render_update_summary([updated(target) for target in targets], verbose=False)
    output = capsys.readouterr().err
    normalized = " ".join(output.split())
    assert "rex custom installer universal, claude-code" in normalized
    assert "2 operations: 2 updated universal, claude-code" in normalized
    assert "\x1b" not in output
    assert "[" not in output


def test_color_hierarchy_keeps_target_names_muted_after_green_version():
    console = Console(color_system="standard", force_terminal=True)
    text = Terminal().status_text(
        MARKER_UPDATED,
        "example/skills@helper",
        detail="main@old → main@new",
        scope="user",
    )
    append_targets(text, ["universal", "claude-code"])
    skill_style = text.get_style_at_offset(console, text.plain.index("helper"))
    source_style = text.get_style_at_offset(console, text.plain.index("example/skills"))
    version_style = text.get_style_at_offset(console, text.plain.index("main@new"))
    target_style = text.get_style_at_offset(console, text.plain.index("universal"))
    assert skill_style.bold
    assert skill_style.color.name == "default"
    assert source_style.color.name == "cyan"
    assert version_style.color.name == "green"
    assert target_style.dim
    assert not target_style.bold
    assert target_style.color.name == "default"
    assert text.plain.endswith("main@new  universal, claude-code")


def test_progress_includes_target_without_brackets(tmp_path):
    target = SkillTarget(tmp_path / "skills", agent="claude-code")
    progress = Progress()
    task_id = progress.add_task("rex@*", scope="user", target=target, detail="custom installer")
    text = StepDescriptionColumn().render(progress.tasks[task_id])
    assert text.plain == "⌂ rex custom installer  claude-code"


def test_custom_directory_is_explicit_in_json_and_display():
    target = SkillTarget(Path("some/skills"))
    steps = scoped_steps([SkillStep(label="rex@*", command=["generate"])], "project", target=target)
    step = steps[0]
    assert step.scope == "custom"
    assert step.target == target
    result = StepResult(
        label=step.label,
        command=step.command,
        returncode=None,
        scope=step.scope,
        target=step.target,
    )
    payload = result.json()
    assert payload["scope"] == "custom"
    assert payload["directory"] == "some/skills"
    assert "agent" not in payload
    assert target_label(target) == "custom  some/skills"


def test_pinned_rows_align_fields_and_use_a_single_summary_line(targets, capsys):
    skills = {
        "apple-reminders": "openclaw/openclaw",
        "gog": "openclaw/gogcli",
        "openhue": "openclaw/openclaw",
        "skill-creator": "anthropics/skills",
        "tenzir-technical-writing": "tenzir/dev-skills",
        "tenzir-update-docs": "tenzir/dev-skills",
    }
    results = [
        updated(targets[0], label=f"{source}@{name}", status="skipped", detail="pinned")
        for name, source in skills.items()
    ]
    results.append(updated(targets[1], status="current"))
    terminal = Terminal()
    terminal.error_console.width = 80
    terminal.render_update_summary(results, verbose=False)
    output = capsys.readouterr().err
    rows = [line for line in output.splitlines() if line.startswith("= ⌂")]
    assert len(rows) == len(skills)
    assert len({row.index("pinned") for row in rows}) == 1
    assert len({row.index("universal") for row in rows}) == 1
    assert len({row.index(source) for row, source in zip(rows, skills.values(), strict=True)}) == 1
    assert output.splitlines()[-1] == "7 operations: 1 current, 6 pinned  universal, claude-code"
    assert "!" not in output
    assert "·" not in output
    assert "skipped" not in output


def test_pinned_presentation_does_not_hide_real_skips_or_change_json(targets, capsys):
    results = [
        updated(targets[0], status="skipped", detail="pinned"),
        updated(targets[1], status="skipped", detail="missing GitHub metadata"),
    ]
    terminal = Terminal()
    terminal.render_update_summary(results, verbose=False)
    output = capsys.readouterr().err
    normalized = " ".join(output.split())
    assert "= ⌂ rex pinned universal" in normalized
    assert "! ⌂ rex missing GitHub metadata claude-code" in normalized
    assert "2 operations: 1 pinned, 1 skipped  universal, claude-code" in output
    assert results[0].json()["status"] == "skipped"
    assert results[0].json()["detail"] == "pinned"


def test_apply_output_identifies_agent_without_a_directory(targets, capsys):
    Terminal().render_step_result(updated(targets[1]))
    assert capsys.readouterr().err == "↑ ⌂ rex custom installer  claude-code\n"


def test_quiet_current_summary_identifies_agents_without_paths(targets, capsys):
    results = [updated(target, status="current") for target in targets]
    Terminal().render_update_summary(results, verbose=False)
    assert capsys.readouterr().err == "2 operations: 2 current  universal, claude-code\n"
