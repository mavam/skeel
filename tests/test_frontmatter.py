from pathlib import Path

import pytest
import yaml

from skeel.frontmatter import FrontmatterError, frontmatter_needs_update, update_skill_frontmatter


def read_frontmatter(path: Path) -> dict[str, object]:
    return yaml.safe_load(path.read_text().split("---", 2)[1])


def test_update_skill_frontmatter_applies_shallow_overrides(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        "---\nname: deploy\ndescription: Upstream\nallowed-tools: [Read]\n---\n# Deploy\n"
    )
    overrides = {
        "description": "Local description",
        "allowed-tools": ["Read", "Bash"],
        "disable-model-invocation": True,
    }

    assert update_skill_frontmatter(path, overrides=overrides)
    assert read_frontmatter(path) == {"name": "deploy", **overrides}
    assert path.read_text().endswith("# Deploy\n")
    assert not update_skill_frontmatter(path, overrides=overrides)


def test_update_skill_frontmatter_merges_metadata(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text("---\nname: test\nmetadata:\n  catalog: upstream\n---\n# Test\n")

    update_skill_frontmatter(
        path,
        overrides={"metadata": {"category": "deployment"}},
        managed_metadata={
            "github-repo": "https://github.com/owner/repo",
            "github-ref": "refs/heads/main",
        },
    )

    metadata = read_frontmatter(path)["metadata"]
    assert metadata == {  # type: ignore[comparison-overlap]
        "catalog": "upstream",
        "category": "deployment",
        "github-repo": "https://github.com/owner/repo",
        "github-ref": "refs/heads/main",
    }


def test_update_skill_frontmatter_creates_metadata_map(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text("---\nname: test\n---\n# Test\n")

    update_skill_frontmatter(path, overrides={"metadata": {"category": "deployment"}})

    assert read_frontmatter(path)["metadata"] == {"category": "deployment"}


def test_update_skill_frontmatter_rejects_symlinked_file(tmp_path: Path) -> None:
    real = tmp_path / "real.md"
    real.write_text("---\nname: test\n---\n# Test\n")
    path = tmp_path / "SKILL.md"
    path.symlink_to(real)

    with pytest.raises(FrontmatterError, match="symlinked SKILL.md"):
        update_skill_frontmatter(
            path,
            overrides={"compatibility": "Requires Docker"},
            root=tmp_path,
        )


def test_update_skill_frontmatter_rejects_missing_target(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"

    with pytest.raises(FrontmatterError, match="could not resolve frontmatter target"):
        update_skill_frontmatter(
            path,
            overrides={"compatibility": "Requires Docker"},
            root=tmp_path,
        )


def test_update_skill_frontmatter_preserves_readable_unicode(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        "---\nname: deploy\ndescription: Use when the user says “ship it” — 🚀\n---\n# Deploy\n",
        encoding="utf-8",
    )

    update_skill_frontmatter(path, overrides={"compatibility": "macOS ≥ 15"})

    text = path.read_text(encoding="utf-8")
    assert "Use when the user says “ship it” — 🚀" in text
    assert "macOS ≥ 15" in text
    assert "\\u201" not in text


def test_frontmatter_needs_update_compares_only_configured_values(
    tmp_path: Path,
) -> None:
    path = tmp_path / "SKILL.md"
    path.write_text(
        "---\nname: deploy\ndisable-model-invocation: true\n"
        "metadata: {catalog: upstream, category: deployment}\n---\n# Deploy\n"
    )

    assert not frontmatter_needs_update(
        path,
        {
            "disable-model-invocation": True,
            "metadata": {"category": "deployment"},
        },
    )
    assert frontmatter_needs_update(path, {"compatibility": "Requires Docker"})
    assert frontmatter_needs_update(path, {"metadata": {"category": "other"}})
    assert frontmatter_needs_update(path, {"metadata": {"missing": "value"}})
