from pathlib import Path

import yaml

from skeel.frontmatter import model_invocation_needs_update, update_skill_frontmatter


def read_frontmatter(path: Path) -> dict[str, object]:
    return yaml.safe_load(path.read_text().split("---", 2)[1])


def test_update_skill_frontmatter_sets_model_invocation_flag(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text("---\nname: deploy\n---\n# Deploy\n")

    assert update_skill_frontmatter(path, disable_model_invocation=True)
    assert read_frontmatter(path)["disable-model-invocation"] is True
    assert path.read_text().endswith("# Deploy\n")

    assert update_skill_frontmatter(path, disable_model_invocation=False)
    assert read_frontmatter(path)["disable-model-invocation"] is False
    assert not update_skill_frontmatter(path, disable_model_invocation=False)


def test_update_skill_frontmatter_preserves_managed_github_metadata(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text("---\nname: test\nmetadata:\n  catalog: upstream\n---\n# Test\n")

    update_skill_frontmatter(
        path,
        managed_metadata={
            "github-repo": "https://github.com/owner/repo",
            "github-ref": "refs/heads/main",
        },
    )

    metadata = read_frontmatter(path)["metadata"]
    assert metadata["catalog"] == "upstream"  # type: ignore[index]
    assert metadata["github-repo"] == "https://github.com/owner/repo"  # type: ignore[index]


def test_update_skill_frontmatter_preserves_readable_unicode(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        "---\nname: deploy\ndescription: Use when the user says “ship it” — 🚀\n---\n# Deploy\n",
        encoding="utf-8",
    )

    update_skill_frontmatter(path, disable_model_invocation=True)

    text = path.read_text(encoding="utf-8")
    assert "Use when the user says “ship it” — 🚀" in text
    assert "\\u201" not in text


def test_model_invocation_needs_update_compares_only_configured_value(
    tmp_path: Path,
) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        "---\nname: deploy\ndisable-model-invocation: true\n"
        "metadata: {catalog: upstream}\n---\n# Deploy\n"
    )

    assert not model_invocation_needs_update(path, True)
    assert model_invocation_needs_update(path, False)
