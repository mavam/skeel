from pathlib import Path

import pytest
import yaml

from skeel.frontmatter import (
    FrontmatterError,
    frontmatter_needs_merge,
    merge_skill_frontmatter,
)


def read_frontmatter(path: Path) -> dict[str, object]:
    return yaml.safe_load(path.read_text().split("---", 2)[1])


def test_merge_skill_frontmatter_applies_and_restores_overrides(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        """---
name: deploy
disable-model-invocation: false
metadata:
  catalog: upstream
---
# Deploy
"""
    )

    assert merge_skill_frontmatter(
        path,
        {
            "disable-model-invocation": True,
            "metadata": {"local": {"enabled": True}},
        },
    )
    frontmatter = read_frontmatter(path)
    assert frontmatter["disable-model-invocation"] is True
    assert frontmatter["metadata"]["catalog"] == "upstream"  # type: ignore[index]
    assert frontmatter["metadata"]["local"] == {"enabled": True}  # type: ignore[index]
    assert "skeel-overrides" in frontmatter["metadata"]  # type: ignore[operator]
    assert path.read_text().endswith("# Deploy\n")

    assert merge_skill_frontmatter(path, {})
    assert read_frontmatter(path) == {
        "name": "deploy",
        "disable-model-invocation": False,
        "metadata": {"catalog": "upstream"},
    }
    assert not merge_skill_frontmatter(path, {})


def test_merge_skill_frontmatter_preserves_managed_github_metadata(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text("---\nname: test\n---\n# Test\n")

    merge_skill_frontmatter(
        path,
        {"disable-model-invocation": True, "metadata": {"catalog": "local"}},
        managed_metadata={
            "github-repo": "https://github.com/owner/repo",
            "github-ref": "refs/heads/main",
        },
    )

    frontmatter = read_frontmatter(path)
    assert frontmatter["disable-model-invocation"] is True
    assert frontmatter["metadata"]["catalog"] == "local"  # type: ignore[index]
    assert frontmatter["metadata"]["github-repo"] == "https://github.com/owner/repo"  # type: ignore[index]


def test_frontmatter_without_overrides_does_not_need_reformatting(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text("---\nname: deploy\nmetadata: {catalog: upstream}\n---\n# Deploy\n")

    assert not frontmatter_needs_merge(path, {})


def test_merge_skill_frontmatter_rejects_invalid_skeel_state(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text("---\nmetadata:\n  skeel-overrides:\n    version: 999\n---\n# Test\n")

    with pytest.raises(FrontmatterError, match="invalid skeel frontmatter override state"):
        merge_skill_frontmatter(path, {"disable-model-invocation": True})
