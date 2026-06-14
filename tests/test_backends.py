from pathlib import Path

from skeel.backends import GhSkillBackend, manual_install_steps, quote_command, symlink_step
from skeel.manifest import Manifest, SkillSpec, SourceSpec


def test_gh_install_step() -> None:
    manifest = Manifest(
        path=Path("manifest.yaml"),
        agents=("universal", "claude-code"),
        sources=(),
        shared_dir=Path("/tmp/agents/skills"),
        claude_dir=Path("/tmp/claude/skills"),
    )
    source = SourceSpec(
        source="openclaw/gogcli",
        skills=(SkillSpec(spec="gog", name="gog"),),
        allow_hidden_dirs=True,
    )

    step = GhSkillBackend().install_steps(manifest, source, source.skills[0])[0]

    assert step.command == [
        "gh",
        "skill",
        "install",
        "openclaw/gogcli",
        "gog",
        "--dir",
        "/tmp/agents/skills",
        "--force",
        "--allow-hidden-dirs",
    ]


def test_manual_install_steps() -> None:
    source = SourceSpec(
        source="downstairs-dawgs/clacks",
        skills=(SkillSpec(spec="clacks", name="clacks"),),
        install=(("uvx", "--from", "slack-clacks", "clacks", "skill", "--mode", "universal"),),
    )

    steps = manual_install_steps(source)

    assert steps[0].label == "downstairs-dawgs/clacks"
    assert steps[0].command == [
        "uvx",
        "--from",
        "slack-clacks",
        "clacks",
        "skill",
        "--mode",
        "universal",
    ]


def test_symlink_step_for_claude_code() -> None:
    manifest = Manifest(
        path=Path("manifest.yaml"),
        agents=("universal", "claude-code"),
        sources=(),
        shared_dir=Path("/Users/me/.agents/skills"),
        claude_dir=Path("/Users/me/.claude/skills"),
    )

    step = symlink_step(manifest, SkillSpec(spec="mavam", name="mavam"))

    assert step is not None
    assert step.command == [
        "ln",
        "-sfn",
        "../../.agents/skills/mavam",
        "/Users/me/.claude/skills/mavam",
    ]


def test_quote_command() -> None:
    assert quote_command(["gh", "skill", "install", "owner/repo", "skills/foo/SKILL.md"]) == (
        "gh skill install owner/repo skills/foo/SKILL.md"
    )
