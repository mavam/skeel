from pathlib import Path

import yaml

from skeel.frontmatter import frontmatter_needs_update, update_skill_frontmatter


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
