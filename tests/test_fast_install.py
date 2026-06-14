import json
from pathlib import Path

import yaml

from skeel.fast_install import DiscoveredSkill, install_skill, select_skill
from skeel.manifest import SkillSpec


def test_install_skill_copies_files_and_injects_github_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    source = tmp_path / "source" / "skills" / "tenzir-asim"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text(
        """---
name: tenzir-asim
description: ASIM reference
---
# ASIM
"""
    )
    (source / "docs").mkdir()
    (source / "docs" / "schema.md").write_text("schema")
    monkeypatch.setattr("skeel.fast_install.Path.home", lambda: home)

    install_skill(
        source="tenzir/skills",
        pin="main",
        ref="refs/heads/main",
        tree_sha="tree123",
        skill=DiscoveredSkill(
            name="tenzir-asim",
            path="skills/tenzir-asim",
            directory=source,
        ),
        directory=tmp_path / "target",
    )

    skill_md = tmp_path / "target" / "tenzir-asim" / "SKILL.md"
    frontmatter = yaml.safe_load(skill_md.read_text().split("---", 2)[1])
    assert frontmatter["metadata"] == {
        "github-repo": "https://github.com/tenzir/skills",
        "github-ref": "refs/heads/main",
        "github-tree-sha": "tree123",
        "github-path": "skills/tenzir-asim",
        "github-pinned": "main",
    }
    assert (tmp_path / "target" / "tenzir-asim" / "docs" / "schema.md").read_text() == "schema"

    lockfile = json.loads((home / ".agents" / ".skill-lock.json").read_text())
    assert lockfile["skills"]["tenzir-asim"]["source"] == "tenzir/skills"
    assert lockfile["skills"]["tenzir-asim"]["skillPath"] == "skills/tenzir-asim/SKILL.md"
    assert lockfile["skills"]["tenzir-asim"]["skillFolderHash"] == "tree123"
    assert lockfile["skills"]["tenzir-asim"]["pinnedRef"] == "main"


def test_select_skill_matches_hidden_and_namespaced_paths(tmp_path: Path) -> None:
    hidden = DiscoveredSkill(name="gog", path=".agents/skills/gog", directory=tmp_path)
    namespaced = DiscoveredSkill(
        name="caveman",
        path="skills/productivity/caveman",
        directory=tmp_path,
    )

    assert select_skill((hidden, namespaced), SkillSpec(spec="gog@main", name="gog")) == hidden
    assert (
        select_skill(
            (hidden, namespaced),
            SkillSpec(spec="productivity/caveman", name="caveman"),
        )
        == namespaced
    )
