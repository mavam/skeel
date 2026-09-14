from pathlib import Path

import pytest

from skeel.frontmatter import load_skill_frontmatter
from skeel.nix_build import build_skills


def make_skill(root: Path, name: str = "original") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Test skill\n"
        "metadata:\n  kept: yes\n  changed: old\n---\n\nBody.\n"
    )
    return root


def selection(path: str, **frontmatter: object) -> dict:
    return {"path": path, "frontmatter": frontmatter}


def test_discover_frontmatter_names_and_hidden_directories(tmp_path: Path) -> None:
    source = tmp_path / "source"
    alpha = make_skill(source / "different-directory", "alpha")
    make_skill(source / ".agents/skills/beta", "beta")
    make_skill(source / ".git/ignored", "ignored")
    make_skill(alpha / "examples/nested", "nested")
    output = tmp_path / "out"
    build_skills({"upstream": {"src": str(source), "skills": None}}, output)
    assert sorted(p.name for p in output.iterdir()) == ["alpha", "beta"]
    assert (output / "alpha/SKILL.md").read_bytes() == (alpha / "SKILL.md").read_bytes()
    assert (output / "alpha/examples/nested/SKILL.md").exists()


def test_selection_rename_and_overrides(tmp_path: Path) -> None:
    source = make_skill(tmp_path / "source")
    helper = source / "helper.sh"
    helper.write_text("#!/bin/sh\necho hello\n")
    helper.chmod(0o755)
    (source / "SKILL.md").chmod(0o444)
    output = tmp_path / "out"
    build_skills(
        {
            "upstream": {
                "src": str(source),
                "skills": {
                    "renamed": selection(
                        ".", **{"disable-model-invocation": True, "metadata": {"changed": "new"}}
                    )
                },
            }
        },
        output,
    )
    metadata = load_skill_frontmatter(output / "renamed/SKILL.md")
    assert metadata["name"] == "renamed"
    assert metadata["disable-model-invocation"] is True
    assert metadata["metadata"] == {"kept": True, "changed": "new"}
    assert (output / "renamed/helper.sh").stat().st_mode & 0o111
    assert load_skill_frontmatter(source / "SKILL.md")["name"] == "original"


def test_empty_selection(tmp_path: Path) -> None:
    source = make_skill(tmp_path / "source")
    output = tmp_path / "out"
    build_skills({"upstream": {"src": str(source), "skills": {}}}, output)
    assert list(output.iterdir()) == []


@pytest.mark.parametrize("path", ["", "../other", "/tmp/other", "nested/../../other"])
def test_reject_escaping_paths(tmp_path: Path, path: str) -> None:
    source = make_skill(tmp_path / "source")
    with pytest.raises(ValueError, match="relative"):
        build_skills(
            {"upstream": {"src": str(source), "skills": {"safe": selection(path)}}},
            tmp_path / "out",
        )


@pytest.mark.parametrize("name", ["../bad", "bad/name", "BAD", "two--hyphens"])
def test_reject_unsafe_names(tmp_path: Path, name: str) -> None:
    source = make_skill(tmp_path / "source")
    with pytest.raises(ValueError, match="invalid local skill name"):
        build_skills(
            {"upstream": {"src": str(source), "skills": {name: selection(".")}}}, tmp_path / "out"
        )


@pytest.mark.parametrize("field,value", [("name", "other"), ("metadata", {"github-repo": "fake"})])
def test_reject_protected_overrides(tmp_path: Path, field: str, value: object) -> None:
    source = make_skill(tmp_path / "source")
    with pytest.raises(ValueError, match="cannot override"):
        build_skills(
            {
                "upstream": {
                    "src": str(source),
                    "skills": {"safe": selection(".", **{field: value})},
                }
            },
            tmp_path / "out",
        )


def test_duplicate_across_sources(tmp_path: Path) -> None:
    source = make_skill(tmp_path / "source")
    with pytest.raises(ValueError, match="duplicate skill"):
        build_skills(
            {name: {"src": str(source), "skills": None} for name in ["one", "two"]},
            tmp_path / "out",
        )


def test_duplicate_within_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    make_skill(source / "one")
    make_skill(source / "two")
    with pytest.raises(ValueError, match="duplicate skill"):
        build_skills({"upstream": {"src": str(source), "skills": None}}, tmp_path / "out")


def test_missing_skill(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ValueError, match="missing SKILL.md"):
        build_skills(
            {"upstream": {"src": str(source), "skills": {"missing": selection(".")}}},
            tmp_path / "out",
        )


def test_missing_discovered_name(tmp_path: Path) -> None:
    source = make_skill(tmp_path / "source")
    (source / "SKILL.md").write_text("---\ndescription: Missing name\n---\nBody\n")
    with pytest.raises(ValueError, match="missing frontmatter name"):
        build_skills({"upstream": {"src": str(source), "skills": None}}, tmp_path / "out")


def test_symlinked_content_is_rejected(tmp_path: Path) -> None:
    source = make_skill(tmp_path / "source")
    (source / "secret").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="refusing symlink"):
        build_skills({"upstream": {"src": str(source), "skills": None}}, tmp_path / "out")


def test_symlinked_skill_directory_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "linked").symlink_to(make_skill(tmp_path / "outside"), target_is_directory=True)
    with pytest.raises(ValueError, match="symlinked skill directory"):
        build_skills(
            {"upstream": {"src": str(source), "skills": {"safe": selection("linked")}}},
            tmp_path / "out",
        )


def test_symlinked_skill_file_is_rejected_before_reading(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "SKILL.md").symlink_to(tmp_path / "does-not-exist")
    with pytest.raises(ValueError, match="refusing symlink"):
        build_skills({"upstream": {"src": str(source), "skills": None}}, tmp_path / "out")
