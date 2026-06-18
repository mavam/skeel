import json
import threading
import time
from pathlib import Path

import pytest
import yaml

from skeel.fast_install import (
    DiscoveredSkill,
    FastInstallError,
    FastInstallSession,
    ResolvedRef,
    install_skill,
    select_skill,
)
from skeel.manifest import SkillSpec, SourceSpec


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


def test_select_skill_reports_source_when_skill_is_missing(tmp_path: Path) -> None:
    with pytest.raises(FastInstallError, match='skill "missing-skill" not found in example/skills'):
        select_skill(
            (DiscoveredSkill(name="other-skill", path="skills/other-skill", directory=tmp_path),),
            SkillSpec(spec="missing-skill", name="missing-skill"),
            source="example/skills",
        )


def test_fast_install_session_reuses_remote_cache_concurrently(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_root = tmp_path / "source"
    for name in ("skill-a", "skill-b"):
        skill_dir = source_root / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(f"# {name}\n")

    call_counts = {
        "resolve_ref": 0,
        "download_archive": 0,
        "fetch_tree_shas": 0,
    }
    call_lock = threading.Lock()
    installed: list[str] = []

    def count_call(name: str) -> None:
        with call_lock:
            call_counts[name] += 1
        time.sleep(0.01)

    def fake_resolve_ref(source: str, pin: str) -> ResolvedRef:
        assert source == "owner/repo"
        assert pin == "main"
        count_call("resolve_ref")
        return ResolvedRef(ref="refs/heads/main", commit_sha="commit123")

    def fake_download_archive(source: str, commit_sha: str, directory: Path) -> Path:
        assert source == "owner/repo"
        assert commit_sha == "commit123"
        assert directory.exists()
        count_call("download_archive")
        return source_root

    def fake_fetch_tree_shas(source: str, commit_sha: str) -> dict[str, str]:
        assert source == "owner/repo"
        assert commit_sha == "commit123"
        count_call("fetch_tree_shas")
        return {"skill-a": "tree-a", "skill-b": "tree-b"}

    def fake_install_skill(**kwargs) -> None:
        with call_lock:
            installed.append(kwargs["skill"].name)

    monkeypatch.setattr("skeel.fast_install.resolve_ref", fake_resolve_ref)
    monkeypatch.setattr("skeel.fast_install.download_archive", fake_download_archive)
    monkeypatch.setattr("skeel.fast_install.fetch_tree_shas", fake_fetch_tree_shas)
    monkeypatch.setattr("skeel.fast_install.install_skill", fake_install_skill)

    session = FastInstallSession("owner/repo")
    source = SourceSpec(
        source="owner/repo",
        skills=(
            SkillSpec(spec="skill-a", name="skill-a", pin="main"),
            SkillSpec(spec="skill-b", name="skill-b", pin="main"),
        ),
        pin="main",
    )
    errors: list[BaseException] = []

    def run_install(skill: SkillSpec) -> None:
        try:
            session.install(source, skill, tmp_path / "target")
        except BaseException as error:
            with call_lock:
                errors.append(error)

    threads = [
        threading.Thread(
            target=run_install,
            args=(skill,),
        )
        for skill in source.skills
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert call_counts == {
        "resolve_ref": 1,
        "download_archive": 1,
        "fetch_tree_shas": 1,
    }
    assert sorted(installed) == ["skill-a", "skill-b"]
