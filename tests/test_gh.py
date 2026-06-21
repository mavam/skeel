import asyncio
from pathlib import Path

import pytest

from skeel.gh import (
    GhOptions,
    InstalledSkill,
    SkillProvenance,
    SkillStep,
    fast_update_outcome,
    install_steps,
    installed_skills,
    manual_install_steps,
    parse_gh_version,
    read_skill_provenance,
    update_outcome,
    update_steps,
)
from skeel.io import ProcessResult
from skeel.manifest import Manifest, SkillSpec, SourceSpec


class FakeRunner:
    def __init__(self, result: ProcessResult) -> None:
        self.result = result
        self.calls: list[list[str]] = []

    async def run(self, command, **kwargs):
        self.calls.append(command)
        assert kwargs == {"capture_output": True}
        return self.result


class SequenceRunner:
    def __init__(self, *results: ProcessResult) -> None:
        self.results = list(results)
        self.calls: list[list[str]] = []

    async def run(self, command, **kwargs):
        self.calls.append(command)
        assert kwargs == {"capture_output": True}
        return self.results.pop(0)


def write_skill(path: Path, frontmatter: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(frontmatter.strip())


def test_install_steps_cover_selected_and_all_skills() -> None:
    selected = SourceSpec(
        source="openclaw/gogcli",
        skills=(SkillSpec(spec="gog", name="gog"),),
    )
    dynamic = SourceSpec(source="mavam/quarto-brief", skills=(), install_all=True)

    selected_step = install_steps(selected, GhOptions(directory=Path("/tmp/skills")))[0]
    dynamic_step = install_steps(dynamic, GhOptions(directory=Path("/tmp/skills")))[0]

    assert selected_step.label == "openclaw/gogcli@gog"
    assert selected_step.command == [
        "gh",
        "skill",
        "install",
        "openclaw/gogcli",
        "gog",
        "--allow-hidden-dirs",
        "--dir",
        "/tmp/skills",
        "--force",
    ]
    assert dynamic_step.label == "mavam/quarto-brief@*"
    assert "--all" in dynamic_step.command


def test_pinned_install_steps_use_archive_installer() -> None:
    source = SourceSpec(
        source="tenzir/skills",
        skills=(SkillSpec(spec="tenzir-asim", name="tenzir-asim", pin="main"),),
        pin="main",
    )

    step = install_steps(source, GhOptions(directory=Path("/tmp/skills")))[0]

    assert step.label == "tenzir/skills@tenzir-asim"
    assert step.command == ["gh", "api", "repos/tenzir/skills/tarball/main"]
    assert step.executor is not None


def test_manual_install_steps() -> None:
    source = SourceSpec(
        source="slack-clacks/clacks",
        skills=(SkillSpec(spec="clacks", name="clacks"),),
        install=(
            ("uvx", "--from", "slack-clacks", "clacks", "skill", "--mode", "universal", "--force"),
        ),
    )

    step = manual_install_steps(source)[0]

    assert step.label == "slack-clacks/clacks"
    assert step.command == [
        "uvx",
        "--from",
        "slack-clacks",
        "clacks",
        "skill",
        "--mode",
        "universal",
        "--force",
    ]


def test_installed_skills_prefers_frontmatter_provenance(tmp_path: Path) -> None:
    skill_path = tmp_path / "skills" / "caveman"
    write_skill(
        skill_path,
        """
---
metadata:
  github-path: skills/productivity/caveman
  github-ref: refs/heads/main
  github-repo: https://github.com/mattpocock/skills
  github-tree-sha: abcdef1234567890
name: caveman
---
# Caveman
""",
    )
    runner = SequenceRunner(
        ProcessResult(command=[], returncode=0, stdout="gh version 2.94.0", stderr=""),
        ProcessResult(
            command=[],
            returncode=0,
            stdout=(
                f'[{{"skillName": "productivity/caveman", "path": "{skill_path}",'
                ' "sourceURL": "", "version": "", "pinned": false}]'
            ),
            stderr="",
        ),
    )

    skills = asyncio.run(installed_skills(GhOptions(directory=tmp_path / "skills"), runner))

    assert skills[0].basename == "caveman"
    assert skills[0].update_name == "caveman"
    assert skills[0].github_source == "mattpocock/skills"
    assert skills[0].label == "mattpocock/skills@caveman"
    assert skills[0].version_label == "main@abcdef1"


def test_parse_gh_version() -> None:
    assert parse_gh_version("gh version 2.94.0 (2026-06-14)") == (2, 94, 0)
    assert parse_gh_version("unexpected") is None


def test_installed_skills_rejects_old_gh_version(tmp_path: Path) -> None:
    (tmp_path / "skills").mkdir()
    runner = SequenceRunner(
        ProcessResult(command=[], returncode=0, stdout="gh version 2.93.0", stderr=""),
    )

    with pytest.raises(RuntimeError, match="requires GitHub CLI 2.94.0"):
        asyncio.run(installed_skills(GhOptions(directory=tmp_path / "skills"), runner))

    assert runner.calls == [["gh", "--version"]]


def test_update_steps_use_manifest_labels_and_report_version_transition(tmp_path: Path) -> None:
    skill_path = tmp_path / "wrangler"
    write_skill(
        skill_path,
        """
---
metadata:
  github-ref: refs/heads/main
  github-repo: https://github.com/cloudflare/skills
  github-tree-sha: old123456789
name: wrangler
---
# Wrangler
""",
    )
    manifest = Manifest(
        path=Path("manifest.yaml"),
        sources=(
            SourceSpec(
                source="cloudflare/skills",
                skills=(SkillSpec(spec="wrangler", name="wrangler"),),
            ),
        ),
    )
    skill = InstalledSkill(
        name="wrangler",
        path=skill_path,
        provenance=read_skill_provenance(skill_path),
    )
    step = update_steps([skill], GhOptions(directory=tmp_path), manifest=manifest)[0]
    write_skill(
        skill_path,
        """
---
metadata:
  github-ref: refs/heads/main
  github-repo: https://github.com/cloudflare/skills
  github-tree-sha: new123456789
name: wrangler
---
# Wrangler
""",
    )

    assert step.label == "cloudflare/skills@wrangler"
    assert step.command == ["gh", "skill", "update", "wrangler", "--dir", str(tmp_path)]
    assert step.outcome is not None
    outcome = step.outcome(ProcessResult(command=[], returncode=0, stdout="Updated wrangler"))
    assert outcome.status == "updated"
    assert outcome.detail == "main@old1234 → main@new1234"


def test_update_steps_use_archive_installer_for_pinned_manifest_skills(tmp_path: Path) -> None:
    skill_path = tmp_path / "tenzir-asim"
    write_skill(
        skill_path,
        """
---
metadata:
  github-ref: refs/heads/main
  github-repo: https://github.com/tenzir/skills
  github-tree-sha: old123456789
  github-path: skills/tenzir-asim
  github-pinned: main
name: tenzir-asim
---
# ASIM
""",
    )
    manifest = Manifest(
        path=Path("manifest.yaml"),
        sources=(
            SourceSpec(
                source="tenzir/skills",
                skills=(SkillSpec(spec="tenzir-asim", name="tenzir-asim", pin="main"),),
                pin="main",
            ),
        ),
    )
    skill = InstalledSkill(
        name="tenzir-asim",
        path=skill_path,
        provenance=read_skill_provenance(skill_path),
    )

    step = update_steps([skill], GhOptions(directory=tmp_path), manifest=manifest)[0]

    assert step.label == "tenzir/skills@tenzir-asim"
    assert step.command == ["gh", "api", "repos/tenzir/skills/tarball/main"]
    assert step.executor is not None
    assert step.outcome is not None


def test_fast_update_outcome_marks_unchanged_pinned_skill_current(tmp_path: Path) -> None:
    skill_path = tmp_path / "tenzir-asim"
    write_skill(
        skill_path,
        """
---
metadata:
  github-ref: refs/heads/main
  github-repo: https://github.com/tenzir/skills
  github-tree-sha: old123456789
name: tenzir-asim
---
# ASIM
""",
    )
    skill = InstalledSkill(
        name="tenzir-asim",
        path=skill_path,
        provenance=read_skill_provenance(skill_path),
    )

    outcome = fast_update_outcome(skill)(ProcessResult(command=[], returncode=0))

    assert outcome.status == "current"
    assert outcome.detail is None


def test_fast_update_outcome_marks_changed_pinned_skill_updated(tmp_path: Path) -> None:
    skill_path = tmp_path / "tenzir-asim"
    write_skill(
        skill_path,
        """
---
metadata:
  github-ref: refs/heads/main
  github-repo: https://github.com/tenzir/skills
  github-tree-sha: old123456789
name: tenzir-asim
---
# ASIM
""",
    )
    skill = InstalledSkill(
        name="tenzir-asim",
        path=skill_path,
        provenance=read_skill_provenance(skill_path),
    )
    write_skill(
        skill_path,
        """
---
metadata:
  github-ref: refs/heads/main
  github-repo: https://github.com/tenzir/skills
  github-tree-sha: new123456789
name: tenzir-asim
---
# ASIM
""",
    )

    outcome = fast_update_outcome(skill)(ProcessResult(command=[], returncode=0))

    assert outcome.status == "updated"
    assert outcome.detail == "main@old1234 → main@new1234"


def test_missing_provenance_has_no_version_transition() -> None:
    from skeel.gh import version_transition

    assert version_transition(SkillProvenance(), SkillProvenance()) is None


def test_version_transition_hides_detail_for_unchanged_versions() -> None:
    from skeel.gh import version_transition

    provenance = SkillProvenance(ref="refs/heads/main", tree_sha="old123456789")

    assert version_transition(provenance, provenance) is None


def test_update_outcome_detail_carries_only_version_transition(tmp_path: Path) -> None:
    skill_path = tmp_path / "wrangler"
    write_skill(
        skill_path,
        """
---
metadata:
  github-ref: refs/heads/main
  github-repo: https://github.com/cloudflare/skills
  github-tree-sha: old123456789
name: wrangler
---
# Wrangler
""",
    )
    skill = InstalledSkill(
        name="wrangler",
        path=skill_path,
        provenance=read_skill_provenance(skill_path),
    )

    # Unchanged: no version noise, and scope is never smuggled into the detail.
    outcome = update_outcome(skill)(
        ProcessResult(command=[], returncode=0, stdout="All skills are up to date")
    )
    assert outcome.detail is None

    write_skill(
        skill_path,
        """
---
metadata:
  github-ref: refs/heads/main
  github-repo: https://github.com/cloudflare/skills
  github-tree-sha: new123456789
name: wrangler
---
# Wrangler
""",
    )

    # Changed: the detail is the bare version transition, with no scope marker.
    outcome = update_outcome(skill)(
        ProcessResult(command=[], returncode=0, stdout="Updated wrangler")
    )
    assert outcome.detail == "main@old1234 → main@new1234"


def test_scoped_steps_stamps_scope_onto_every_step() -> None:
    from skeel.gh import scoped_steps

    steps = [SkillStep(label="a", command=["a"]), SkillStep(label="b", command=["b"])]

    user_steps = scoped_steps(steps, "user")
    assert [step.scope for step in user_steps] == ["user", "user"]

    # Project (and unscoped) steps carry no marker.
    assert [step.scope for step in scoped_steps(steps, "project")] == ["project", "project"]
    assert [step.scope for step in scoped_steps(steps, None)] == [None, None]
