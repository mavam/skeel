from pathlib import Path

import pytest

from skeel.gh import InstalledSkill
from skeel.manifest import Manifest, SkillSpec, SourceSpec
from skeel.reconcile import RemoveTarget, apply_plan, remove_steps
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


def test_remove_steps_refuses_symlinked_skills(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    real = tmp_path / "real-skill"
    write_skill(real)
    root.mkdir()
    (root / "linked").symlink_to(real)

    target = SkillTarget(directory=root, scope="project")
    skill = InstalledSkill(name="linked", path=root / "linked")
    with pytest.raises(ValueError, match="symlinked"):
        remove_steps((skill,), target)


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
