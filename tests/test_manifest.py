from pathlib import Path

import pytest

from skeel.manifest import (
    infer_skill_name,
    load_manifest,
    manifest_path,
    remove_manifest_source,
    upsert_manifest_source,
)


def write_manifest(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "skills.yaml"
    path.write_text(content.strip())
    return path


@pytest.mark.parametrize(
    ("spec", "name"),
    [
        ("mavam", "mavam"),
        ("skills/foo/SKILL.md", "foo"),
        ("packages/agent-skills/code-review", "code-review"),
    ],
)
def test_infer_skill_name(spec: str, name: str) -> None:
    assert infer_skill_name(spec) == name


def test_load_manifest_sources(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  tenzir/skills:
    - tenzir-docs
  mavam/quarto-brief:
  mattpocock/skills:
    pin: v1
    skills:
      - caveman
      - grill-me
  slack-clacks/clacks:
    skills:
      - clacks
    install:
      - uvx --from slack-clacks clacks skill --mode universal --force
""",
    )

    manifest = load_manifest(path)

    assert manifest.path == path
    assert manifest_path() == Path(".agents/skills.yaml")
    assert manifest.desired_skill_names == {"tenzir-docs", "caveman", "grill-me", "clacks"}
    assert [(skill.name, skill.source) for skill in manifest.desired_skills] == [
        ("tenzir-docs", "tenzir/skills"),
        ("caveman", "mattpocock/skills"),
        ("grill-me", "mattpocock/skills"),
        ("clacks", "slack-clacks/clacks"),
    ]

    selected, dynamic, pinned, manual = manifest.sources
    assert (selected.source, selected.skills[0].name, selected.install_all) == (
        "tenzir/skills",
        "tenzir-docs",
        False,
    )
    assert (dynamic.source, dynamic.skills, dynamic.install_all) == (
        "mavam/quarto-brief",
        (),
        True,
    )
    assert [skill.pin for skill in pinned.skills] == ["v1", "v1"]
    assert manual.install == (
        ("uvx", "--from", "slack-clacks", "clacks", "skill", "--mode", "universal", "--force"),
    )


def test_old_source_list_is_rejected(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  - tenzir/skills
""",
    )

    with pytest.raises(ValueError, match="sources must be a mapping"):
        load_manifest(path)


def test_manual_install_source_requires_skills(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  slack-clacks/clacks:
    install:
      - uvx --from slack-clacks clacks skill --mode universal --force
""",
    )

    with pytest.raises(ValueError, match="has no skills"):
        load_manifest(path)


def test_empty_manifest_has_no_desired_skills(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, "sources: {}")

    manifest = load_manifest(path)

    assert manifest.sources == ()
    assert manifest.desired_skill_names == set()


def test_upsert_manifest_source_writes_keyed_schema(tmp_path: Path) -> None:
    path = tmp_path / ".agents" / "skills.yaml"

    result = upsert_manifest_source(path, "tenzir/skills", "tenzir-docs")
    assert result.changed is True
    assert path.read_text() == "sources:\n  tenzir/skills:\n    - tenzir-docs\n"

    result = upsert_manifest_source(path, "tenzir/skills", "tenzir-docs")
    assert result.changed is False

    result = upsert_manifest_source(path, "tenzir/skills", "tenzir-docs@main")
    assert result.changed is True
    result = upsert_manifest_source(path, "mavam/quarto-brief")
    assert result.changed is True

    assert path.read_text() == (
        "sources:\n  tenzir/skills:\n    - tenzir-docs@main\n  mavam/quarto-brief:\n"
    )


def test_upsert_manifest_source_dry_run_does_not_write(tmp_path: Path) -> None:
    path = tmp_path / ".agents" / "skills.yaml"

    result = upsert_manifest_source(path, "tenzir/skills", "tenzir-docs", dry_run=True)

    assert result.changed is True
    assert not path.exists()
    assert result.manifest.desired_skill_names == {"tenzir-docs"}


def test_remove_manifest_source_updates_keyed_schema(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  tenzir/skills:
    - tenzir-docs
    - tenzir-ecs
  mavam/quarto-brief:
""",
    )

    result = remove_manifest_source(path, "tenzir/skills", "tenzir-docs")
    assert result.changed is True
    assert path.read_text() == (
        "sources:\n  tenzir/skills:\n    - tenzir-ecs\n  mavam/quarto-brief:\n"
    )

    result = remove_manifest_source(path, "mavam/quarto-brief")
    assert result.changed is True
    assert path.read_text() == "sources:\n  tenzir/skills:\n    - tenzir-ecs\n"
