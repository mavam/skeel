import asyncio
from pathlib import Path

import pytest
import yaml

from skeel.fast_install import RepositoryTree, ResolvedRef
from skeel.frontmatter import FrontmatterAmbiguityError
from skeel.gh import (
    InstalledSkill,
    SkillProvenance,
    SkillStep,
    SkillTarget,
    classify_source_inventory_change,
    classify_update_output,
    fast_update_outcome,
    install_steps,
    installed_skills,
    manual_install_steps,
    parse_gh_version,
    read_skill_provenance,
    resolve_installed_frontmatter_path,
    source_update_outcome,
    update_outcome,
    update_steps,
)
from skeel.io import ProcessResult
from skeel.manifest import Manifest, SkillSpec, SourceSpec
from skeel.reconcile import filter_source


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

    selected_step = install_steps(selected, SkillTarget(directory=Path("/tmp/skills")))[0]
    dynamic_step = install_steps(dynamic, SkillTarget(directory=Path("/tmp/skills")))[0]

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


def test_install_steps_apply_frontmatter_after_install(tmp_path: Path) -> None:
    source = SourceSpec(
        source="example/skills",
        skills=(
            SkillSpec(
                spec="deploy",
                name="deploy-alias",
                frontmatter={"disable-model-invocation": True},
            ),
        ),
    )
    target = SkillTarget(directory=tmp_path / "skills")
    skill_path = target.directory / "deploy"
    write_skill(skill_path, "---\nname: deploy\n---\n# Deploy")

    step = install_steps(source, target)[0]

    assert step.label == "example/skills@deploy-alias"
    assert step.command == ["gh", "api", "repos/example/skills/tarball/HEAD"]
    assert step.executor is not None
    assert step.postprocess is not None
    assert step.preview_detail == "disable-model-invocation, name (deploy)"
    result = step.postprocess(ProcessResult(command=step.command, returncode=0))
    assert result.returncode == 0
    frontmatter = (skill_path / "SKILL.md").read_text().split("---", 2)[1]
    assert yaml.safe_load(frontmatter)["disable-model-invocation"] is True


def test_resolve_installed_frontmatter_path_scans_aliases(tmp_path: Path) -> None:
    target = SkillTarget(directory=tmp_path)
    installed = tmp_path / "renamed"
    write_skill(installed, "---\nname: deploy\n---\n# Deploy")

    resolved = resolve_installed_frontmatter_path(
        "example/skills",
        target,
        SkillSpec(spec="catalog/deploy", name="deploy"),
    )

    assert resolved == installed / "SKILL.md"


def test_resolve_installed_frontmatter_path_rejects_ambiguity(tmp_path: Path) -> None:
    target = SkillTarget(directory=tmp_path)
    write_skill(tmp_path / "first", "---\nname: deploy\n---\n# Deploy")
    write_skill(tmp_path / "second", "---\nname: deploy\n---\n# Deploy")

    with pytest.raises(FrontmatterAmbiguityError, match="ambiguous"):
        resolve_installed_frontmatter_path(
            "example/skills",
            target,
            SkillSpec(spec="catalog/deploy", name="deploy"),
        )


def test_pinned_install_steps_use_archive_installer() -> None:
    source = SourceSpec(
        source="tenzir/skills",
        skills=(SkillSpec(spec="tenzir-asim", name="tenzir-asim", pin="main"),),
        pin="main",
    )

    step = install_steps(source, SkillTarget(directory=Path("/tmp/skills")))[0]

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

    target = SkillTarget(directory=Path("/tmp/skills"), scope="project")
    manifest = Manifest(path=Path("/tmp/skills.yaml"), sources=(source,))
    step = manual_install_steps(source, target, manifest)[0]

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
    assert step.executor is not None


def test_manual_install_steps_apply_frontmatter(tmp_path: Path) -> None:
    source = SourceSpec(
        source="custom/installer",
        skills=(
            SkillSpec(
                spec="deploy",
                name="deploy",
                frontmatter={"disable-model-invocation": True},
            ),
        ),
        install=(("install-custom",),),
    )
    target = SkillTarget(directory=tmp_path / "skills", scope="project")
    manifest = Manifest(path=tmp_path / "skills.yaml", sources=(source,))
    write_skill(target.directory / "deploy", "---\nname: deploy\n---\n# Deploy")

    step = manual_install_steps(source, target, manifest)[0]

    assert step.postprocess is not None
    result = step.postprocess(ProcessResult(command=step.command, returncode=0))
    assert result.returncode == 0
    text = (target.directory / "deploy" / "SKILL.md").read_text()
    assert yaml.safe_load(text.split("---", 2)[1])["disable-model-invocation"] is True


def test_manual_install_reports_ambiguous_frontmatter_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = SourceSpec(
        source="custom/installer",
        skills=(
            SkillSpec(
                spec="catalog/deploy",
                name="deploy",
                frontmatter={"compatibility": "Requires Docker"},
            ),
        ),
        install=(("install-custom",),),
    )
    target = SkillTarget(directory=tmp_path / "skills", scope="project")
    manifest = Manifest(path=tmp_path / "skills.yaml", sources=(source,))
    write_skill(target.directory / "first", "---\nname: deploy\n---\n# Deploy")
    write_skill(target.directory / "second", "---\nname: deploy\n---\n# Deploy")

    class SuccessfulRunner:
        async def run(self, command, **kwargs):
            return ProcessResult(command=command, returncode=0)

    monkeypatch.setattr("skeel.gh.ProcessRunner", SuccessfulRunner)
    step = manual_install_steps(source, target, manifest)[0]

    assert step.executor is not None
    result = asyncio.run(step.executor())
    assert result.returncode == 1
    assert result.stderr == 'frontmatter target for skill "deploy" is ambiguous'
    assert "did not produce" not in result.stderr


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

    skills = asyncio.run(installed_skills(SkillTarget(directory=tmp_path / "skills"), runner))

    assert skills[0].basename == "caveman"
    assert skills[0].update_name == "caveman"
    assert skills[0].github_source == "mattpocock/skills"
    assert skills[0].label == "mattpocock/skills@caveman"
    assert skills[0].version_label == "main@abcdef1"


def test_installed_skills_includes_skill_directory_symlinks(tmp_path: Path) -> None:
    universal = tmp_path / ".agents" / "skills" / "worktrunk"
    write_skill(
        universal,
        """
---
metadata:
  github-ref: refs/tags/v0.73.0
  github-repo: https://github.com/max-sixty/worktrunk
  github-tree-sha: abcdef1234567890
name: worktrunk
---
# Worktrunk
""",
    )
    target = tmp_path / ".claude" / "skills"
    target.mkdir(parents=True)
    linked = target / "worktrunk"
    linked.symlink_to(universal, target_is_directory=True)
    runner = SequenceRunner(
        ProcessResult(command=[], returncode=0, stdout="gh version 2.94.0", stderr=""),
        ProcessResult(command=[], returncode=0, stdout="[]", stderr=""),
    )

    skills = asyncio.run(installed_skills(SkillTarget(directory=target), runner))

    assert len(skills) == 1
    assert skills[0].name == "worktrunk"
    assert skills[0].path == linked
    assert skills[0].github_source == "max-sixty/worktrunk"
    assert skills[0].version_label == "v0.73.0@abcdef1"


def test_installed_skills_deduplicates_links_through_symlinked_target(
    tmp_path: Path,
) -> None:
    universal = tmp_path / ".agents" / "skills" / "worktrunk"
    write_skill(universal, "---\nname: worktrunk\n---\n# Worktrunk")
    target = tmp_path / ".claude" / "skills"
    target.mkdir(parents=True)
    linked = target / "worktrunk"
    linked.symlink_to(universal, target_is_directory=True)
    linked_target = tmp_path / "linked-skills"
    linked_target.symlink_to(target, target_is_directory=True)
    runner = SequenceRunner(
        ProcessResult(command=[], returncode=0, stdout="gh version 2.94.0", stderr=""),
        ProcessResult(
            command=[],
            returncode=0,
            stdout=(
                f'[{{"skillName": "worktrunk", "path": "{linked}",'
                ' "sourceURL": "", "version": "", "pinned": false}]'
            ),
            stderr="",
        ),
    )

    skills = asyncio.run(installed_skills(SkillTarget(directory=linked_target), runner))

    assert len(skills) == 1
    assert skills[0].path == linked


def test_installed_skills_includes_dangling_links_as_unusable(tmp_path: Path) -> None:
    target = tmp_path / "skills"
    target.mkdir()
    linked = target / "missing"
    linked.symlink_to(tmp_path / "gone", target_is_directory=True)
    runner = SequenceRunner(
        ProcessResult(command=[], returncode=0, stdout="gh version 2.94.0", stderr=""),
        ProcessResult(command=[], returncode=0, stdout="[]", stderr=""),
    )

    skills = asyncio.run(installed_skills(SkillTarget(directory=target), runner))

    assert [(skill.name, skill.path, skill.usable) for skill in skills] == [
        ("missing", linked, False)
    ]


def test_installed_skills_ignores_links_to_non_skill_directories(tmp_path: Path) -> None:
    target = tmp_path / "skills"
    target.mkdir()
    not_a_skill = tmp_path / "not-a-skill"
    not_a_skill.mkdir()
    (target / "linked").symlink_to(not_a_skill, target_is_directory=True)
    runner = SequenceRunner(
        ProcessResult(command=[], returncode=0, stdout="gh version 2.94.0", stderr=""),
        ProcessResult(command=[], returncode=0, stdout="[]", stderr=""),
    )

    skills = asyncio.run(installed_skills(SkillTarget(directory=target), runner))

    assert skills == ()


def test_parse_gh_version() -> None:
    assert parse_gh_version("gh version 2.94.0 (2026-06-14)") == (2, 94, 0)
    assert parse_gh_version("unexpected") is None


def test_installed_skills_rejects_old_gh_version(tmp_path: Path) -> None:
    (tmp_path / "skills").mkdir()
    runner = SequenceRunner(
        ProcessResult(command=[], returncode=0, stdout="gh version 2.93.0", stderr=""),
    )

    with pytest.raises(RuntimeError, match="requires GitHub CLI 2.94.0"):
        asyncio.run(installed_skills(SkillTarget(directory=tmp_path / "skills"), runner))

    assert runner.calls == [["gh", "--version"]]


def test_update_steps_reapply_frontmatter(tmp_path: Path) -> None:
    skill_path = tmp_path / "deploy"
    write_skill(
        skill_path,
        "---\nmetadata:\n  github-repo: https://github.com/example/skills\nname: deploy\n---\n",
    )
    installed = InstalledSkill(
        name="deploy-service",
        path=skill_path,
        provenance=read_skill_provenance(skill_path),
    )
    manifest = Manifest(
        path=tmp_path / "skills.yaml",
        sources=(
            SourceSpec(
                source="example/skills",
                skills=(
                    SkillSpec(
                        spec="deploy",
                        name="deploy",
                        frontmatter={"disable-model-invocation": True},
                    ),
                ),
            ),
        ),
    )

    step = update_steps([installed], SkillTarget(directory=tmp_path), manifest=manifest)[0]

    assert step.label == "example/skills@deploy-service"
    assert step.postprocess is not None
    assert step.preview_detail == "disable-model-invocation"
    result = step.postprocess(ProcessResult(command=step.command, returncode=0))
    assert result.returncode == 0
    frontmatter = yaml.safe_load((skill_path / "SKILL.md").read_text().split("---", 2)[1])
    assert frontmatter["disable-model-invocation"] is True


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
    step = update_steps([skill], SkillTarget(directory=tmp_path), manifest=manifest)[0]
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
    assert step.command == ["gh", "skill", "update", "wrangler", "--dir", str(tmp_path), "--all"]
    assert step.outcome is not None
    outcome = step.outcome(ProcessResult(command=[], returncode=0, stdout="Updated wrangler"))
    assert outcome.status == "updated"
    assert outcome.detail == "main@old1234 → main@new1234"


def test_update_steps_reinstalls_unpinned_github_skill_missing_metadata(tmp_path: Path) -> None:
    skill_path = tmp_path / "metadata-repair"
    write_skill(
        skill_path,
        """
---
name: metadata-repair
---
# Metadata Repair
""",
    )
    manifest = Manifest(
        path=Path("manifest.yaml"),
        sources=(
            SourceSpec(
                source="example/skill-catalog",
                skills=(SkillSpec(spec="metadata-repair", name="metadata-repair"),),
            ),
        ),
    )
    skill = InstalledSkill(
        name="metadata-repair",
        path=skill_path,
        provenance=read_skill_provenance(skill_path),
    )

    step = update_steps([skill], SkillTarget(directory=tmp_path), manifest=manifest)[0]
    write_skill(
        skill_path,
        """
---
metadata:
  github-ref: refs/heads/main
  github-repo: https://github.com/example/skill-catalog
  github-tree-sha: abcdef1234567890
name: metadata-repair
---
# Metadata Repair
""",
    )

    assert step.label == "example/skill-catalog@metadata-repair"
    assert step.command == [
        "gh",
        "skill",
        "install",
        "example/skill-catalog",
        "metadata-repair",
        "--allow-hidden-dirs",
        "--dir",
        str(tmp_path),
        "--force",
    ]
    assert step.outcome is not None
    outcome = step.outcome(
        ProcessResult(command=[], returncode=0, stdout="Installed metadata-repair")
    )
    assert outcome.status == "updated"
    assert outcome.detail == "unknown → main@abcdef1"


def test_update_steps_keep_manual_install_skill_with_missing_metadata_on_gh_update(
    tmp_path: Path,
) -> None:
    skill_path = tmp_path / "manual-helper"
    write_skill(
        skill_path,
        """
---
name: manual-helper
---
# Manual Helper
""",
    )
    manifest = Manifest(
        path=Path("manifest.yaml"),
        sources=(
            SourceSpec(
                source="example/manual-skills",
                skills=(SkillSpec(spec="manual-helper", name="manual-helper"),),
                install=(("custom-installer", "install", "manual-helper"),),
            ),
        ),
    )
    skill = InstalledSkill(
        name="manual-helper",
        path=skill_path,
        provenance=read_skill_provenance(skill_path),
    )

    step = update_steps([skill], SkillTarget(directory=tmp_path), manifest=manifest)[0]

    assert step.label == "example/manual-skills@manual-helper"
    assert step.command == [
        "gh",
        "skill",
        "update",
        "manual-helper",
        "--dir",
        str(tmp_path),
        "--all",
    ]


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

    step = update_steps([skill], SkillTarget(directory=tmp_path), manifest=manifest)[0]

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


def test_update_output_classification_is_case_insensitive_for_skips() -> None:
    classification = classify_update_output("Pinned skill, skipping update")

    assert classification.status == "skipped"
    assert classification.skipped_detail == "pinned"


def test_detail_text_renders_full_version_transition() -> None:
    from skeel.io import detail_text

    assert detail_text("main@old1234 → main@new1234").plain == "main@old1234 → main@new1234"


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


def dynamic_skill(
    tmp_path: Path,
    name: str,
    *,
    ref: str = "refs/heads/main",
    sha: str = "old123456789",
) -> InstalledSkill:
    path = tmp_path / name
    write_skill(
        path,
        f"""
---
metadata:
  github-ref: {ref}
  github-repo: https://github.com/example/skill-catalog
  github-tree-sha: {sha}
  github-path: skills/{name}
name: {name}
---
# {name}
""",
    )
    return InstalledSkill(
        name=name,
        path=path,
        provenance=read_skill_provenance(path),
    )


def dynamic_manifest(*, pin: str | None = None) -> Manifest:
    return Manifest(
        path=Path("manifest.yaml"),
        sources=(
            SourceSpec(
                source="example/skill-catalog",
                skills=(),
                install_all=True,
                pin=pin,
            ),
        ),
    )


def test_update_steps_refresh_unpinned_dynamic_source_once(tmp_path: Path) -> None:
    installed = [dynamic_skill(tmp_path, "skill-alpha"), dynamic_skill(tmp_path, "skill-beta")]

    steps = update_steps(installed, SkillTarget(directory=tmp_path), manifest=dynamic_manifest())

    assert len(steps) == 1
    assert steps[0].label == "example/skill-catalog@*"
    assert steps[0].command == [
        "gh",
        "skill",
        "install",
        "example/skill-catalog",
        "--all",
        "--allow-hidden-dirs",
        "--dir",
        str(tmp_path),
        "--force",
    ]
    assert steps[0].executor is None


def test_update_steps_refresh_branch_pinned_dynamic_source_once(tmp_path: Path) -> None:
    installed = [dynamic_skill(tmp_path, "skill-alpha"), dynamic_skill(tmp_path, "skill-beta")]

    steps = update_steps(
        installed,
        SkillTarget(directory=tmp_path),
        manifest=dynamic_manifest(pin="main"),
    )

    assert len(steps) == 1
    assert steps[0].label == "example/skill-catalog@*"
    assert steps[0].command == ["gh", "api", "repos/example/skill-catalog/tarball/main"]
    assert steps[0].executor is not None
    assert steps[0].parallel is False


def test_update_steps_exclude_dynamic_skills_from_per_skill_updates(tmp_path: Path) -> None:
    installed = [dynamic_skill(tmp_path, "skill-alpha"), dynamic_skill(tmp_path, "skill-beta")]

    steps = update_steps(installed, SkillTarget(directory=tmp_path), manifest=dynamic_manifest())

    assert [step.label for step in steps] == ["example/skill-catalog@*"]
    assert all(step.command[:3] != ["gh", "skill", "update"] for step in steps)


def test_update_steps_keep_explicit_sources_per_skill(tmp_path: Path) -> None:
    installed = [dynamic_skill(tmp_path, "skill-alpha"), dynamic_skill(tmp_path, "skill-beta")]
    manifest = Manifest(
        path=Path("manifest.yaml"),
        sources=(
            SourceSpec(
                source="example/skill-catalog",
                skills=(
                    SkillSpec(spec="skill-alpha", name="skill-alpha"),
                    SkillSpec(spec="skill-beta", name="skill-beta"),
                ),
            ),
        ),
    )

    steps = update_steps(installed, SkillTarget(directory=tmp_path), manifest=manifest)

    assert [step.label for step in steps] == [
        "example/skill-catalog@skill-alpha",
        "example/skill-catalog@skill-beta",
    ]
    assert all(step.command[:3] == ["gh", "skill", "update"] for step in steps)


def test_dynamic_source_filtered_to_skill_uses_targeted_install(tmp_path: Path) -> None:
    installed = [dynamic_skill(tmp_path, "skill-alpha"), dynamic_skill(tmp_path, "skill-beta")]
    source = filter_source(dynamic_manifest(pin="main").sources[0], "skill-alpha")
    assert source is not None
    manifest = Manifest(path=Path("manifest.yaml"), sources=(source,))

    steps = update_steps(installed[:1], SkillTarget(directory=tmp_path), manifest=manifest)

    assert len(steps) == 1
    assert steps[0].label == "example/skill-catalog@skill-alpha"
    assert steps[0].command == ["gh", "api", "repos/example/skill-catalog/tarball/main"]


def test_dynamic_source_missing_metadata_uses_unified_source_step(tmp_path: Path) -> None:
    path = tmp_path / "metadata-repair"
    write_skill(path, "---\nname: metadata-repair\n---\n# Metadata Repair")
    installed = [InstalledSkill(name="metadata-repair", path=path)]

    steps = update_steps(installed, SkillTarget(directory=tmp_path), manifest=dynamic_manifest())

    assert len(steps) == 1
    assert steps[0].label == "example/skill-catalog@*"
    assert steps[0].command[:5] == [
        "gh",
        "skill",
        "install",
        "example/skill-catalog",
        "--all",
    ]


def test_multiple_dynamic_sources_do_not_share_orphan_attribution(tmp_path: Path) -> None:
    path = tmp_path / "metadata-repair"
    write_skill(path, "---\nname: metadata-repair\n---\n# Metadata Repair")
    installed = [InstalledSkill(name="metadata-repair", path=path)]
    manifest = Manifest(
        path=Path("manifest.yaml"),
        sources=(
            SourceSpec(source="example/catalog-a", skills=(), install_all=True),
            SourceSpec(source="example/catalog-b", skills=(), install_all=True),
        ),
    )

    steps = update_steps(installed, SkillTarget(directory=tmp_path), manifest=manifest)
    write_skill(
        path,
        """
---
metadata:
  github-ref: refs/heads/main
  github-repo: https://github.com/example/catalog-a
  github-tree-sha: new123456789
  github-path: skills/metadata-repair
name: metadata-repair
---
# Metadata Repair
""",
    )

    assert [step.label for step in steps] == [
        "example/catalog-a@*",
        "example/catalog-b@*",
        "metadata-repair",
    ]
    assert steps[0].outcome is not None
    assert steps[1].outcome is not None
    assert steps[0].outcome(ProcessResult(command=[], returncode=0)).status == "updated"
    assert steps[1].outcome(ProcessResult(command=[], returncode=0)).status == "current"


def test_source_update_outcome_classifies_inventory_changes(tmp_path: Path) -> None:
    source = dynamic_manifest().sources[0]
    skill = dynamic_skill(tmp_path, "skill-alpha")
    options = SkillTarget(directory=tmp_path)

    unchanged = source_update_outcome(source, [skill], options)
    assert unchanged(ProcessResult(command=[], returncode=0)).status == "current"

    changed = source_update_outcome(source, [skill], options)
    dynamic_skill(tmp_path, "skill-alpha", sha="new123456789")
    changed_result = changed(ProcessResult(command=[], returncode=0))
    assert changed_result.status == "updated"
    assert changed_result.detail == "main@old1234 → main@new1234"

    current_skill = dynamic_skill(tmp_path, "skill-alpha", sha="new123456789")
    added = source_update_outcome(source, [current_skill], options)
    dynamic_skill(tmp_path, "skill-beta", sha="other123456789")
    added_result = added(ProcessResult(command=[], returncode=0))
    assert added_result.status == "updated"
    assert added_result.detail == "+1 skill"


def test_source_inventory_classifier_summarizes_nonuniform_changes() -> None:
    before = {
        Path("a"): SkillProvenance(ref="refs/heads/main", tree_sha="old-a"),
        Path("b"): SkillProvenance(ref="refs/heads/main", tree_sha="old-b"),
    }
    after = {
        Path("a"): SkillProvenance(ref="refs/heads/main", tree_sha="new-a"),
        Path("b"): SkillProvenance(ref="refs/heads/main", tree_sha="new-b"),
    }

    outcome = classify_source_inventory_change(before, after)

    assert outcome.status == "updated"
    assert outcome.detail == "2 changed"


def test_source_inventory_classifier_reports_mixed_changes() -> None:
    before = {
        Path("skill-alpha"): SkillProvenance(ref="refs/heads/main", tree_sha="old-a"),
        Path("skill-beta"): SkillProvenance(ref="refs/heads/main", tree_sha="old-b"),
        Path("skill-gamma"): SkillProvenance(ref="refs/heads/main", tree_sha="old-c"),
        Path("skill-delta"): SkillProvenance(ref="refs/heads/main", tree_sha="old-d"),
    }
    after = {
        Path("skill-alpha"): SkillProvenance(ref="refs/heads/main", tree_sha="new-a"),
        Path("skill-beta"): SkillProvenance(ref="refs/heads/main", tree_sha="new-b"),
        Path("skill-delta"): SkillProvenance(ref="refs/heads/main", tree_sha="old-d"),
        Path("skill-epsilon"): SkillProvenance(ref="refs/heads/main", tree_sha="new-e"),
    }

    outcome = classify_source_inventory_change(before, after)

    assert outcome.status == "updated"
    assert outcome.detail == "+1 skill, -1 skill, 2 changed"


def test_immutable_dynamic_source_skips_unchanged_archive(
    tmp_path: Path,
    monkeypatch,
) -> None:
    skill = dynamic_skill(tmp_path, "skill-alpha", ref="refs/tags/v1.0.0")
    source = dynamic_manifest(pin="v1.0.0").sources[0]
    manifest = Manifest(path=Path("manifest.yaml"), sources=(source,))
    calls = {"download": 0}

    monkeypatch.setattr(
        "skeel.fast_install.resolve_ref",
        lambda source, pin: ResolvedRef(ref="refs/tags/v1.0.0", commit_sha="commit123"),
    )
    monkeypatch.setattr(
        "skeel.fast_install.fetch_repository_tree",
        lambda source, sha: RepositoryTree(
            directory_shas={"skills/skill-alpha": "old123456789"},
            skill_paths=frozenset({"skills/skill-alpha"}),
            complete=True,
        ),
    )

    def unexpected_download(source: str, commit_sha: str, directory: Path) -> Path:
        calls["download"] += 1
        raise AssertionError("unchanged immutable source should not download an archive")

    monkeypatch.setattr("skeel.fast_install.download_archive", unexpected_download)
    step = update_steps([skill], SkillTarget(directory=tmp_path), manifest=manifest)[0]
    assert step.executor is not None
    assert step.outcome is not None

    result = asyncio.run(step.executor())
    outcome = step.outcome(result)

    assert result.returncode == 0
    assert calls["download"] == 0
    assert outcome.status == "current"
    assert outcome.detail is None


def test_immutable_pin_bump_refreshes_identical_skill_tree(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("skeel.fast_install.Path.home", lambda: tmp_path / "home")
    skill = dynamic_skill(tmp_path, "skill-alpha", ref="refs/tags/v1.0.0")
    source = dynamic_manifest(pin="v1.0.1").sources[0]
    manifest = Manifest(path=Path("manifest.yaml"), sources=(source,))
    archive_root = tmp_path / "archive"
    archive_skill = archive_root / "skills" / "skill-alpha"
    write_skill(archive_skill, "---\nname: skill-alpha\n---\n# Skill Alpha")
    downloads: list[str] = []

    monkeypatch.setattr(
        "skeel.fast_install.resolve_ref",
        lambda source, pin: ResolvedRef(ref="refs/tags/v1.0.1", commit_sha="commit-new"),
    )
    monkeypatch.setattr(
        "skeel.fast_install.fetch_repository_tree",
        lambda source, sha: RepositoryTree(
            directory_shas={"skills/skill-alpha": "old123456789"},
            skill_paths=frozenset({"skills/skill-alpha"}),
            complete=True,
        ),
    )

    def download(source: str, commit_sha: str, directory: Path) -> Path:
        downloads.append(commit_sha)
        return archive_root

    monkeypatch.setattr("skeel.fast_install.download_archive", download)
    step = update_steps([skill], SkillTarget(directory=tmp_path), manifest=manifest)[0]
    assert step.executor is not None
    assert step.outcome is not None

    result = asyncio.run(step.executor())
    outcome = step.outcome(result)

    assert result.returncode == 0
    assert downloads == ["commit-new"]
    assert read_skill_provenance(skill.path).ref == "refs/tags/v1.0.1"
    assert outcome.status == "updated"
    assert outcome.detail == "v1.0.0@old1234 → v1.0.1@old1234"


def test_immutable_install_all_refresh_discovers_missing_remote_skill(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("skeel.fast_install.Path.home", lambda: tmp_path / "home")
    skill = dynamic_skill(tmp_path, "skill-alpha", ref="refs/tags/v1.0.0")
    source = dynamic_manifest(pin="v1.0.0").sources[0]
    manifest = Manifest(path=Path("manifest.yaml"), sources=(source,))
    archive_root = tmp_path / "archive"
    write_skill(
        archive_root / "skills" / "skill-alpha",
        "---\nname: skill-alpha\n---\n# Skill Alpha",
    )
    write_skill(
        archive_root / "skills" / "skill-beta",
        "---\nname: skill-beta\n---\n# Skill Beta",
    )
    downloads: list[str] = []

    monkeypatch.setattr(
        "skeel.fast_install.resolve_ref",
        lambda source, pin: ResolvedRef(ref="refs/tags/v1.0.0", commit_sha="commit-old"),
    )
    monkeypatch.setattr(
        "skeel.fast_install.fetch_repository_tree",
        lambda source, sha: RepositoryTree(
            directory_shas={
                "skills/skill-alpha": "old123456789",
                "skills/skill-beta": "new123456789",
            },
            skill_paths=frozenset({"skills/skill-alpha", "skills/skill-beta"}),
            complete=True,
        ),
    )

    def download(source: str, commit_sha: str, directory: Path) -> Path:
        downloads.append(commit_sha)
        return archive_root

    monkeypatch.setattr("skeel.fast_install.download_archive", download)
    step = update_steps([skill], SkillTarget(directory=tmp_path), manifest=manifest)[0]
    assert step.executor is not None
    assert step.outcome is not None

    result = asyncio.run(step.executor())
    outcome = step.outcome(result)

    assert result.returncode == 0
    assert downloads == ["commit-old"]
    assert read_skill_provenance(tmp_path / "skill-beta").tree_sha == "new123456789"
    assert outcome.status == "updated"
    assert outcome.detail == "+1 skill"


def test_pinned_install_all_refresh_reports_pruned_skill(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("skeel.fast_install.Path.home", lambda: tmp_path / "home")
    installed = [
        dynamic_skill(tmp_path, "skill-alpha"),
        dynamic_skill(tmp_path, "skill-beta"),
    ]
    source = dynamic_manifest(pin="main").sources[0]
    manifest = Manifest(path=Path("manifest.yaml"), sources=(source,))
    archive_root = tmp_path / "archive"
    write_skill(
        archive_root / "skills" / "skill-alpha",
        "---\nname: skill-alpha\n---\n# Skill Alpha",
    )

    monkeypatch.setattr(
        "skeel.fast_install.resolve_ref",
        lambda source, pin: ResolvedRef(ref="refs/heads/main", commit_sha="commit-new"),
    )
    monkeypatch.setattr(
        "skeel.fast_install.download_archive",
        lambda source, commit_sha, directory: archive_root,
    )
    monkeypatch.setattr(
        "skeel.fast_install.fetch_repository_tree",
        lambda source, sha: RepositoryTree(
            directory_shas={"skills/skill-alpha": "old123456789"},
            skill_paths=frozenset({"skills/skill-alpha"}),
            complete=True,
        ),
    )
    step = update_steps(installed, SkillTarget(directory=tmp_path), manifest=manifest)[0]
    assert step.executor is not None
    assert step.outcome is not None

    result = asyncio.run(step.executor())
    outcome = step.outcome(result)

    assert result.returncode == 0
    assert not (tmp_path / "skill-beta").exists()
    assert outcome.status == "updated"
    assert outcome.detail == "-1 skill (removed: skill-beta)"


def test_prune_warning_preserves_source_refresh_outcome(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("skeel.fast_install.Path.home", lambda: tmp_path / "home")
    installed = [
        dynamic_skill(tmp_path, "skill-alpha"),
        dynamic_skill(tmp_path, "skill-beta"),
    ]
    source = dynamic_manifest(pin="main").sources[0]
    manifest = Manifest(path=Path("manifest.yaml"), sources=(source,))
    archive_root = tmp_path / "archive"
    write_skill(
        archive_root / "skills" / "skill-alpha",
        "---\nname: skill-alpha\n---\n# Skill Alpha",
    )
    monkeypatch.setattr(
        "skeel.fast_install.resolve_ref",
        lambda source, pin: ResolvedRef(ref="refs/heads/main", commit_sha="commit-new"),
    )
    monkeypatch.setattr(
        "skeel.fast_install.download_archive",
        lambda source, commit_sha, directory: archive_root,
    )
    monkeypatch.setattr(
        "skeel.fast_install.fetch_repository_tree",
        lambda source, sha: RepositoryTree(
            directory_shas={"skills/skill-alpha": "new123456789"},
            skill_paths=frozenset({"skills/skill-alpha"}),
            complete=True,
        ),
    )

    def fail_stale_remove(path: Path, guard) -> None:
        raise PermissionError("permission denied")

    monkeypatch.setattr("skeel.fast_install.remove_guarded_directory", fail_stale_remove)
    step = update_steps(installed, SkillTarget(directory=tmp_path), manifest=manifest)[0]
    assert step.executor is not None
    assert step.outcome is not None

    result = asyncio.run(step.executor())
    outcome = step.outcome(result)

    assert result.returncode == 0
    assert len(result.warnings) == 1
    assert "permission denied" in result.warnings[0]
    assert (tmp_path / "skill-beta").exists()
    assert outcome.status == "updated"
    assert outcome.detail == "main@old1234 → main@new1234"
