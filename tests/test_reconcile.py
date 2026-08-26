import asyncio
from pathlib import Path

import pytest
import yaml

from skeel.gh import InstalledSkill
from skeel.io import Terminal
from skeel.manifest import Manifest, SkillSpec, SourceSpec
from skeel.reconcile import (
    RemoveTarget,
    apply_plan,
    diff_installed_skills,
    expand_remove_target,
    remove_steps,
)
from skeel.targets import SkillTarget


def write_skill(path: Path) -> None:
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text("---\nname: test\n---\n")


def manifest_with(*sources: SourceSpec) -> Manifest:
    return Manifest(path=Path("/tmp/skills.yaml"), sources=sources)


def installed(name: str, root: Path, source: str = "") -> InstalledSkill:
    return InstalledSkill(
        name=name,
        path=root / name,
        source_url=f"https://github.com/{source}" if source else "",
    )


def test_apply_preserves_extras_by_default(tmp_path: Path) -> None:
    target = SkillTarget(directory=tmp_path, scope="project")
    manifest = manifest_with(
        SourceSpec(source="example/skills", skills=(SkillSpec(spec="alpha", name="alpha"),))
    )
    extras = (installed("obsolete", tmp_path),)

    plan = apply_plan(manifest, target, extras)
    assert [step.kind for step in plan] == ["command"]

    pruned = apply_plan(manifest, target, extras, prune=True)
    assert [step.kind for step in pruned] == ["command", "remove"]


def test_apply_reconciles_model_invocation_setting(tmp_path: Path) -> None:
    target = SkillTarget(directory=tmp_path, scope="project")
    skill_path = tmp_path / "deploy"
    skill_path.mkdir()
    (skill_path / "SKILL.md").write_text(
        "---\nname: deploy\ndisable-model-invocation: false\n---\n# Deploy\n"
    )
    current = (installed("deploy", tmp_path, source="example/skills"),)
    overridden = manifest_with(
        SourceSpec(
            source="example/skills",
            skills=(
                SkillSpec(
                    spec="deploy",
                    name="deploy",
                    disable_model_invocation=True,
                ),
            ),
        )
    )

    plan = apply_plan(overridden, target, current)

    assert [step.kind for step in plan] == ["frontmatter"]
    assert plan[0].command == []
    assert plan[0].executor is not None
    assert asyncio.run(plan[0].executor()).returncode == 0
    frontmatter = yaml.safe_load((skill_path / "SKILL.md").read_text().split("---", 2)[1])
    assert frontmatter["disable-model-invocation"] is True
    assert apply_plan(overridden, target, current) == []

    unmanaged = manifest_with(
        SourceSpec(
            source="example/skills",
            skills=(SkillSpec(spec="deploy", name="deploy"),),
        )
    )
    assert apply_plan(unmanaged, target, current) == []


def test_frontmatter_diff_reports_pending_override(tmp_path: Path) -> None:
    target = SkillTarget(directory=tmp_path, scope="project")
    skill_path = tmp_path / "deploy"
    skill_path.mkdir()
    (skill_path / "SKILL.md").write_text("---\nname: deploy\n---\n# Deploy\n")
    current = (installed("deploy", tmp_path, source="example/skills"),)
    manifest = manifest_with(
        SourceSpec(
            source="example/skills",
            skills=(
                SkillSpec(
                    spec="deploy",
                    name="deploy",
                    disable_model_invocation=True,
                ),
            ),
        )
    )

    diff = diff_installed_skills(manifest, current)

    assert [skill.name for skill in diff.changed] == ["deploy"]
    assert not diff.in_sync
    assert len(apply_plan(manifest, target, current)) == 1


def test_apply_refuses_frontmatter_override_through_external_symlink(tmp_path: Path) -> None:
    target = SkillTarget(directory=tmp_path / "skills", scope="project")
    target.directory.mkdir()
    external = tmp_path / "external" / "deploy"
    external.mkdir(parents=True)
    skill_md = external / "SKILL.md"
    original = (
        "---\nname: deploy\nmetadata:\n"
        "  github-repo: https://github.com/example/skills\n---\n# Deploy\n"
    )
    skill_md.write_text(original)
    linked = target.directory / "deploy"
    linked.symlink_to(external, target_is_directory=True)
    current = (
        InstalledSkill(
            name="deploy",
            path=linked,
            source_url="https://github.com/example/skills",
        ),
    )
    manifest = manifest_with(
        SourceSpec(
            source="example/skills",
            skills=(
                SkillSpec(
                    spec="deploy",
                    name="deploy",
                    disable_model_invocation=True,
                ),
            ),
        )
    )

    plan = apply_plan(manifest, target, current)

    assert len(plan) == 1
    assert plan[0].executor is not None
    result = asyncio.run(plan[0].executor())
    assert result.returncode == 1
    assert "outside target directory" in result.stderr
    assert skill_md.read_text() == original
    assert [skill.name for skill in diff_installed_skills(manifest, current).changed] == ["deploy"]


def test_apply_repairs_declared_dangling_symlink_before_install(tmp_path: Path) -> None:
    target = SkillTarget(directory=tmp_path, scope="project")
    linked = tmp_path / "alpha"
    linked.symlink_to(tmp_path / "gone", target_is_directory=True)
    manifest = manifest_with(
        SourceSpec(source="example/skills", skills=(SkillSpec(spec="alpha", name="alpha"),))
    )

    plan = apply_plan(
        manifest,
        target,
        (InstalledSkill(name="alpha", path=linked, usable=False),),
    )

    assert [step.command[0] for step in plan] == ["unlink", "gh"]


def test_apply_removals_delete_exactly_the_selected_skill(tmp_path: Path) -> None:
    target = SkillTarget(directory=tmp_path, scope="project")
    manifest = manifest_with()
    extras = (
        installed("deselected", tmp_path, source="example/skills"),
        installed("hand-authored", tmp_path),
    )

    plan = apply_plan(
        manifest,
        target,
        extras,
        removals=(RemoveTarget(source="example/skills", skill="deselected"),),
    )
    removes = [step for step in plan if step.kind == "remove"]
    assert [step.remove_path for step in removes] == [tmp_path / "deselected"]


def test_custom_source_removal_expands_to_declared_skills(tmp_path: Path) -> None:
    source = SourceSpec(
        source="custom/installer",
        skills=(
            SkillSpec(spec="one", name="one"),
            SkillSpec(spec="two", name="two"),
        ),
        install=(("install-custom",),),
    )
    manifest = manifest_with(source)

    removals = expand_remove_target(manifest, RemoveTarget(source=source.source))

    assert removals == (
        RemoveTarget(source=source.source),
        RemoveTarget(source=source.source, skill="one"),
        RemoveTarget(source=source.source, skill="two"),
    )


def test_apply_removals_for_whole_source(tmp_path: Path) -> None:
    target = SkillTarget(directory=tmp_path, scope="project")
    extras = (
        installed("one", tmp_path, source="example/skills"),
        installed("two", tmp_path, source="example/skills"),
        installed("other", tmp_path, source="other/skills"),
    )

    plan = apply_plan(
        manifest_with(),
        target,
        extras,
        removals=(RemoveTarget(source="example/skills"),),
    )
    removes = sorted(step.remove_path for step in plan if step.kind == "remove")
    assert removes == [tmp_path / "one", tmp_path / "two"]


def test_remove_steps_refuses_target_root(tmp_path: Path) -> None:
    target = SkillTarget(directory=tmp_path, scope="project")
    skill = InstalledSkill(name="root", path=tmp_path)
    with pytest.raises(ValueError, match="outside target directory"):
        remove_steps((skill,), target)


def test_remove_steps_refuses_paths_outside_target(tmp_path: Path) -> None:
    target = SkillTarget(directory=tmp_path / "skills", scope="project")
    skill = InstalledSkill(name="escape", path=tmp_path / "elsewhere" / "escape")
    with pytest.raises(ValueError, match="outside target directory"):
        remove_steps((skill,), target)


def test_remove_steps_unlinks_symlinked_skills_without_removing_target(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    real = tmp_path / "real-skill"
    write_skill(real)
    root.mkdir()
    linked = root / "linked"
    linked.symlink_to(real)

    target = SkillTarget(directory=root, scope="project")
    step = remove_steps((InstalledSkill(name="linked", path=linked),), target)[0]
    assert step.removal_guard is not None

    result = Terminal(json_output=True).execute_remove_step(
        step.label,
        step.command,
        step.remove_path,
        step.removal_guard,
    )

    assert result.returncode == 0
    assert step.command == ["unlink", str(linked)]
    assert not linked.exists()
    assert not linked.is_symlink()
    assert (real / "SKILL.md").is_file()


def test_remove_steps_unlinks_dangling_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    linked = root / "missing"
    linked.symlink_to(tmp_path / "gone", target_is_directory=True)

    step = remove_steps(
        (InstalledSkill(name="missing", path=linked, usable=False),),
        SkillTarget(directory=root, scope="project"),
    )[0]
    assert step.removal_guard is not None

    result = Terminal(json_output=True).execute_remove_step(
        step.label,
        step.command,
        step.remove_path,
        step.removal_guard,
    )

    assert result.returncode == 0
    assert step.command == ["unlink", str(linked)]
    assert not linked.is_symlink()


def test_remove_steps_accepts_symlinked_target_directory(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    write_skill(root / "helper")
    linked_root = tmp_path / "linked-skills"
    linked_root.symlink_to(root, target_is_directory=True)

    steps = remove_steps(
        (InstalledSkill(name="helper", path=linked_root / "helper"),),
        SkillTarget(directory=linked_root, scope="project"),
    )

    assert len(steps) == 1
    assert steps[0].removal_guard is not None
    assert steps[0].removal_guard.root == root.resolve()


def test_remove_steps_unlinks_skill_through_symlinked_target(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    real = tmp_path / "real-skill"
    write_skill(real)
    root.mkdir()
    (root / "linked").symlink_to(real, target_is_directory=True)
    linked_root = tmp_path / "linked-skills"
    linked_root.symlink_to(root, target_is_directory=True)
    linked = linked_root / "linked"

    step = remove_steps(
        (InstalledSkill(name="linked", path=linked),),
        SkillTarget(directory=linked_root, scope="project"),
    )[0]
    assert step.removal_guard is not None

    result = Terminal(json_output=True).execute_remove_step(
        step.label,
        step.command,
        step.remove_path,
        step.removal_guard,
    )

    assert result.returncode == 0
    assert not (root / "linked").is_symlink()
    assert (real / "SKILL.md").is_file()


def test_remove_steps_requires_skill_md(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    (root / "not-a-skill").mkdir(parents=True)

    target = SkillTarget(directory=root, scope="project")
    skill = InstalledSkill(name="not-a-skill", path=root / "not-a-skill")
    with pytest.raises(ValueError, match="SKILL.md"):
        remove_steps((skill,), target)


def test_remove_steps_allows_real_skill_directories(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    write_skill(root / "helper")

    target = SkillTarget(directory=root, scope="project")
    skill = InstalledSkill(name="helper", path=root / "helper")
    steps = remove_steps((skill,), target)
    assert [step.remove_path for step in steps] == [root / "helper"]


def test_remove_step_revalidates_skill_md_at_execution(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    skill_path = root / "helper"
    write_skill(skill_path)
    step = remove_steps(
        (InstalledSkill(name="helper", path=skill_path),),
        SkillTarget(directory=root, scope="project"),
    )[0]
    assert step.removal_guard is not None
    (skill_path / "SKILL.md").unlink()

    result = Terminal(json_output=True).execute_remove_step(
        step.label,
        step.command,
        step.remove_path,
        step.removal_guard,
    )

    assert result.returncode == 1
    assert skill_path.is_dir()


def test_remove_step_refuses_replaced_skill_at_execution(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    skill_path = root / "helper"
    write_skill(skill_path)
    step = remove_steps(
        (InstalledSkill(name="helper", path=skill_path),),
        SkillTarget(directory=root, scope="project"),
    )[0]
    assert step.removal_guard is not None

    original = root / "helper-original"
    skill_path.rename(original)
    replacement = tmp_path / "replacement"
    write_skill(replacement)
    replacement.rename(skill_path)

    result = Terminal(json_output=True).execute_remove_step(
        step.label,
        step.command,
        step.remove_path,
        step.removal_guard,
    )

    assert result.returncode == 1
    assert original.is_dir()
    assert skill_path.is_dir()


def test_remove_step_refuses_replaced_symlink_at_execution(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_skill(first)
    write_skill(second)
    root.mkdir()
    linked = root / "helper"
    linked.symlink_to(first)
    step = remove_steps(
        (InstalledSkill(name="helper", path=linked),),
        SkillTarget(directory=root, scope="project"),
    )[0]
    assert step.removal_guard is not None
    linked.unlink()
    linked.symlink_to(second)

    result = Terminal(json_output=True).execute_remove_step(
        step.label,
        step.command,
        step.remove_path,
        step.removal_guard,
    )

    assert result.returncode == 1
    assert linked.is_symlink()
    assert linked.resolve() == second


def test_remove_step_refuses_replaced_target_at_execution(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    skill_path = root / "helper"
    write_skill(skill_path)
    step = remove_steps(
        (InstalledSkill(name="helper", path=skill_path),),
        SkillTarget(directory=root, scope="project"),
    )[0]
    assert step.removal_guard is not None

    original = tmp_path / "skills-original"
    root.rename(original)
    unrelated = tmp_path / "unrelated"
    write_skill(unrelated / "helper")
    root.symlink_to(unrelated, target_is_directory=True)

    result = Terminal(json_output=True).execute_remove_step(
        step.label,
        step.command,
        step.remove_path,
        step.removal_guard,
    )

    assert result.returncode == 1
    assert (original / "helper").is_dir()
    assert (unrelated / "helper").is_dir()
