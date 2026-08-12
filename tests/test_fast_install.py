import asyncio
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
    RepositoryTree,
    ResolvedRef,
    fetch_repository_tree,
    install_skill,
    prune_removed_skills,
    removable_skill_provenance,
    remove_lockfile_skill,
    select_skill,
)
from skeel.gh import InstalledSkill, SkillTarget, read_skill_provenance, update_steps
from skeel.manifest import Manifest, SkillSpec, SourceSpec


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
    assert lockfile["skills"]["tenzir-asim"]["installPath"] == str(
        (tmp_path / "target" / "tenzir-asim").resolve()
    )


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


def test_fetch_repository_tree_identifies_skill_directories(monkeypatch) -> None:
    monkeypatch.setattr(
        "skeel.fast_install.gh_api_json",
        lambda path: {
            "truncated": False,
            "tree": [
                {"path": "skills/alpha", "type": "tree", "sha": "tree-alpha"},
                {"path": "skills/alpha/SKILL.md", "type": "blob", "sha": "blob-alpha"},
                {"path": "skills/alpha/README.md", "type": "blob", "sha": "blob-readme"},
                {"path": ".agents/beta", "type": "tree", "sha": "tree-beta"},
                {"path": ".agents/beta/SKILL.md", "type": "blob", "sha": "blob-beta"},
            ],
        },
    )

    tree = fetch_repository_tree("owner/repo", "commit123")

    assert tree.directory_shas == {
        "skills/alpha": "tree-alpha",
        ".agents/beta": "tree-beta",
    }
    assert tree.skill_paths == frozenset({"skills/alpha", ".agents/beta"})
    assert tree.complete is True


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
        "fetch_repository_tree": 0,
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

    def fake_fetch_repository_tree(source: str, commit_sha: str) -> RepositoryTree:
        assert source == "owner/repo"
        assert commit_sha == "commit123"
        count_call("fetch_repository_tree")
        return RepositoryTree(
            directory_shas={"skill-a": "tree-a", "skill-b": "tree-b"},
            skill_paths=frozenset({"skill-a", "skill-b"}),
            complete=True,
        )

    def fake_install_skill(**kwargs) -> None:
        with call_lock:
            installed.append(kwargs["skill"].name)

    monkeypatch.setattr("skeel.fast_install.resolve_ref", fake_resolve_ref)
    monkeypatch.setattr("skeel.fast_install.download_archive", fake_download_archive)
    monkeypatch.setattr(
        "skeel.fast_install.fetch_repository_tree",
        fake_fetch_repository_tree,
    )
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
        "fetch_repository_tree": 1,
    }
    assert sorted(installed) == ["skill-a", "skill-b"]


def test_pinned_install_all_refresh_discovers_new_skill(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    source_root = tmp_path / "source"
    discovered: dict[str, DiscoveredSkill] = {}
    for name in ("skill-a", "skill-b", "skill-c"):
        directory = source_root / "skills" / name
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(f"---\nname: {name}\n---\n# {name}\n")
        discovered[name] = DiscoveredSkill(
            name=name,
            path=f"skills/{name}",
            directory=directory,
        )

    target = tmp_path / "target"
    monkeypatch.setattr("skeel.fast_install.Path.home", lambda: home)
    for name in ("skill-a", "skill-b"):
        install_skill(
            source="owner/repo",
            pin="main",
            ref="refs/heads/main",
            tree_sha=f"old-{name}",
            skill=discovered[name],
            directory=target,
        )

    monkeypatch.setattr(
        "skeel.fast_install.resolve_ref",
        lambda source, pin: ResolvedRef(ref="refs/heads/main", commit_sha="commit-new"),
    )
    monkeypatch.setattr(
        "skeel.fast_install.download_archive",
        lambda source, commit_sha, directory: source_root,
    )
    monkeypatch.setattr(
        "skeel.fast_install.fetch_repository_tree",
        lambda source, commit_sha: RepositoryTree(
            directory_shas={f"skills/{name}": f"new-{name}" for name in discovered},
            skill_paths=frozenset(f"skills/{name}" for name in discovered),
            complete=True,
        ),
    )

    installed = tuple(
        InstalledSkill(
            name=name,
            path=target / name,
            provenance=read_skill_provenance(target / name),
        )
        for name in ("skill-a", "skill-b")
    )
    manifest = Manifest(
        path=Path("manifest.yaml"),
        sources=(
            SourceSpec(
                source="owner/repo",
                skills=(),
                install_all=True,
                pin="main",
            ),
        ),
    )
    step = update_steps(installed, SkillTarget(directory=target), manifest=manifest)[0]
    assert step.executor is not None
    assert step.outcome is not None

    result = asyncio.run(step.executor())
    outcome = step.outcome(result)

    assert result.returncode == 0
    assert outcome.status == "updated"
    assert sorted(path.name for path in target.iterdir()) == ["skill-a", "skill-b", "skill-c"]
    for name in discovered:
        provenance = read_skill_provenance(target / name)
        assert provenance.source == "owner/repo"
        assert provenance.ref == "refs/heads/main"
        assert provenance.path == f"skills/{name}"
        assert provenance.tree_sha == f"new-{name}"

    lockfile = json.loads((home / ".agents" / ".skill-lock.json").read_text())
    assert sorted(lockfile["skills"]) == ["skill-a", "skill-b", "skill-c"]
    assert all(lockfile["skills"][name]["skillFolderHash"] == f"new-{name}" for name in discovered)


def test_pinned_install_all_prunes_only_owned_removed_skills(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    source_root = tmp_path / "source"
    target = tmp_path / "target"
    monkeypatch.setattr("skeel.fast_install.Path.home", lambda: home)

    remote_dir = source_root / "skills" / "skill-alpha"
    remote_dir.mkdir(parents=True)
    (remote_dir / "SKILL.md").write_text("---\nname: skill-alpha\n---\n# Skill Alpha\n")
    remote_skill = DiscoveredSkill(
        name="skill-alpha",
        path="skills/skill-alpha",
        directory=remote_dir,
    )
    removed_dir = tmp_path / "fixtures" / "skill-beta"
    removed_dir.mkdir(parents=True)
    (removed_dir / "SKILL.md").write_text("---\nname: skill-beta\n---\n# Skill Beta\n")
    removed_skill = DiscoveredSkill(
        name="skill-beta",
        path="skills/skill-beta",
        directory=removed_dir,
    )
    other_dir = tmp_path / "fixtures" / "skill-other"
    other_dir.mkdir(parents=True)
    (other_dir / "SKILL.md").write_text("---\nname: skill-other\n---\n# Other\n")
    other_skill = DiscoveredSkill(
        name="skill-other",
        path="skills/skill-other",
        directory=other_dir,
    )

    install_skill(
        source="example/skill-catalog",
        pin="main",
        ref="refs/heads/main",
        tree_sha="tree-alpha",
        skill=remote_skill,
        directory=target,
    )
    install_skill(
        source="example/skill-catalog",
        pin="main",
        ref="refs/heads/main",
        tree_sha="tree-beta",
        skill=removed_skill,
        directory=target,
    )
    install_skill(
        source="example/other-catalog",
        pin="main",
        ref="refs/heads/main",
        tree_sha="tree-other",
        skill=other_skill,
        directory=target,
    )
    removed_skill_md = target / "skill-beta" / "SKILL.md"
    removed_skill_md.write_text(
        removed_skill_md.read_text().replace(
            "https://github.com/example/skill-catalog",
            "https://github.com/example/skill-catalog.git",
        )
    )
    linked = target / "linked-skill"
    linked.symlink_to(other_dir, target_is_directory=True)
    malformed = target / "malformed"
    malformed.mkdir()
    (malformed / "SKILL.md").write_text("---\nname: [oops\n---\n# Malformed\n")
    non_utf8 = target / "non-utf8"
    non_utf8.mkdir()
    (non_utf8 / "SKILL.md").write_bytes(b"---\nname: \xff\n---\n")
    metadata_less = target / "metadata-less"
    metadata_less.mkdir()
    (metadata_less / "SKILL.md").write_text("---\nname: metadata-less\n---\n# Metadata Less\n")
    missing_path = target / "missing-path"
    missing_path.mkdir()
    (missing_path / "SKILL.md").write_text(
        """---
metadata:
  github-repo: https://github.com/example/skill-catalog
  github-ref: refs/heads/main
  github-tree-sha: tree-missing
name: missing-path
---
# Missing Path
"""
    )

    monkeypatch.setattr(
        "skeel.fast_install.resolve_ref",
        lambda source, pin: ResolvedRef(ref="refs/heads/main", commit_sha="commit-new"),
    )
    monkeypatch.setattr(
        "skeel.fast_install.download_archive",
        lambda source, commit_sha, directory: source_root,
    )
    monkeypatch.setattr(
        "skeel.fast_install.fetch_repository_tree",
        lambda source, commit_sha: RepositoryTree(
            directory_shas={"skills/skill-alpha": "tree-alpha"},
            skill_paths=frozenset({"skills/skill-alpha"}),
            complete=True,
        ),
    )
    source = SourceSpec(
        source="example/skill-catalog",
        skills=(),
        install_all=True,
        pin="main",
    )

    result = FastInstallSession(source.source).install(
        source,
        None,
        target,
        prune=True,
    )

    assert result.removed_paths == (target / "skill-beta",)
    assert result.warnings == ()
    assert sorted(path.name for path in target.iterdir()) == [
        "linked-skill",
        "malformed",
        "metadata-less",
        "missing-path",
        "non-utf8",
        "skill-alpha",
        "skill-other",
    ]
    lockfile = json.loads((home / ".agents" / ".skill-lock.json").read_text())
    assert sorted(lockfile["skills"]) == ["skill-alpha", "skill-other"]


def test_pinned_install_all_keeps_removed_skills_without_prune(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("skeel.fast_install.Path.home", lambda: tmp_path / "home")
    source_root = tmp_path / "source"
    remote_dir = source_root / "skills" / "skill-alpha"
    remote_dir.mkdir(parents=True)
    (remote_dir / "SKILL.md").write_text("---\nname: skill-alpha\n---\n# Skill Alpha\n")
    target = tmp_path / "target"
    stale_dir = target / "skill-beta"
    stale_dir.mkdir(parents=True)
    (stale_dir / "SKILL.md").write_text(
        """---
metadata:
  github-repo: https://github.com/example/skill-catalog
  github-ref: refs/heads/main
  github-tree-sha: tree-beta
  github-path: skills/skill-beta
name: skill-beta
---
# Skill Beta
"""
    )
    monkeypatch.setattr(
        "skeel.fast_install.resolve_ref",
        lambda source, pin: ResolvedRef(ref="refs/heads/main", commit_sha="commit-new"),
    )
    monkeypatch.setattr(
        "skeel.fast_install.download_archive",
        lambda source, commit_sha, directory: source_root,
    )
    monkeypatch.setattr(
        "skeel.fast_install.fetch_repository_tree",
        lambda source, commit_sha: RepositoryTree(
            directory_shas={"skills/skill-alpha": "tree-alpha"},
            skill_paths=frozenset({"skills/skill-alpha"}),
            complete=True,
        ),
    )
    source = SourceSpec(
        source="example/skill-catalog",
        skills=(),
        install_all=True,
        pin="main",
    )

    FastInstallSession(source.source).install(source, None, target)

    assert stale_dir.exists()


def test_incomplete_repository_tree_disables_pruning(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("skeel.fast_install.Path.home", lambda: tmp_path / "home")
    source_root = tmp_path / "source"
    remote_dir = source_root / "skills" / "skill-alpha"
    remote_dir.mkdir(parents=True)
    (remote_dir / "SKILL.md").write_text("---\nname: skill-alpha\n---\n# Skill Alpha\n")
    target = tmp_path / "target"
    stale_dir = target / "skill-beta"
    stale_dir.mkdir(parents=True)
    (stale_dir / "SKILL.md").write_text(
        """---
metadata:
  github-repo: https://github.com/example/skill-catalog
  github-ref: refs/heads/main
  github-tree-sha: tree-beta
  github-path: skills/skill-beta
name: skill-beta
---
# Skill Beta
"""
    )
    monkeypatch.setattr(
        "skeel.fast_install.resolve_ref",
        lambda source, pin: ResolvedRef(ref="refs/heads/main", commit_sha="commit-new"),
    )
    monkeypatch.setattr(
        "skeel.fast_install.download_archive",
        lambda source, commit_sha, directory: source_root,
    )
    monkeypatch.setattr(
        "skeel.fast_install.fetch_repository_tree",
        lambda source, commit_sha: RepositoryTree(
            directory_shas={"skills/skill-alpha": "tree-alpha"},
            skill_paths=frozenset({"skills/skill-alpha"}),
            complete=False,
        ),
    )
    source = SourceSpec(
        source="example/skill-catalog",
        skills=(),
        install_all=True,
        pin="main",
    )

    result = FastInstallSession(source.source).install(source, None, target, prune=True)

    assert result.removed_paths == ()
    assert stale_dir.exists()


def test_prune_refuses_skill_replaced_after_provenance_check(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "target"
    stale_dir = target / "skill-beta"
    stale_dir.mkdir(parents=True)
    metadata = """---
metadata:
  github-repo: https://github.com/example/skill-catalog
  github-path: skills/skill-beta
name: skill-beta
---
# Skill Beta
"""
    (stale_dir / "SKILL.md").write_text(metadata)
    original = target / "skill-beta-original"
    calls = 0

    def replace_after_guard(candidate: Path):
        nonlocal calls
        calls += 1
        provenance = removable_skill_provenance(candidate)
        if calls == 2:
            candidate.rename(original)
            candidate.mkdir()
            (candidate / "SKILL.md").write_text(metadata)
        return provenance

    monkeypatch.setattr(
        "skeel.fast_install.removable_skill_provenance",
        replace_after_guard,
    )

    result = prune_removed_skills(
        source="example/skill-catalog",
        remote_skill_paths=frozenset(),
        directory=target,
    )

    assert result.removed_paths == ()
    assert len(result.warnings) == 1
    assert "replaced skill" in result.warnings[0]
    assert original.is_dir()
    assert stale_dir.is_dir()


def test_prune_failure_returns_warning(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "target"
    stale_dir = target / "skill-beta"
    stale_dir.mkdir(parents=True)
    (stale_dir / "SKILL.md").write_text(
        """---
metadata:
  github-repo: https://github.com/example/skill-catalog
  github-path: skills/skill-beta
name: skill-beta
---
# Skill Beta
"""
    )

    def fail_remove(path: Path, guard) -> None:
        raise PermissionError("permission denied")

    monkeypatch.setattr("skeel.fast_install.remove_guarded_directory", fail_remove)

    result = prune_removed_skills(
        source="example/skill-catalog",
        remote_skill_paths=frozenset(),
        directory=target,
    )

    assert result.removed_paths == ()
    assert len(result.warnings) == 1
    assert "permission denied" in result.warnings[0]
    assert stale_dir.exists()


def test_lockfile_removal_requires_matching_install_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr("skeel.fast_install.Path.home", lambda: home)
    lockfile_path = home / ".agents" / ".skill-lock.json"
    lockfile_path.parent.mkdir(parents=True)
    user_path = home / ".agents" / "skills" / "skill-alpha"
    lockfile_path.write_text(
        json.dumps(
            {
                "version": 3,
                "skills": {
                    "skill-alpha": {
                        "source": "example/skill-catalog",
                        "installPath": str(user_path.resolve()),
                    }
                },
            }
        )
    )

    remove_lockfile_skill(
        skill_name="skill-alpha",
        source="example/skill-catalog",
        install_path=tmp_path / "project" / ".agents" / "skills" / "skill-alpha",
    )
    assert "skill-alpha" in json.loads(lockfile_path.read_text())["skills"]

    remove_lockfile_skill(
        skill_name="skill-alpha",
        source="example/skill-catalog",
        install_path=user_path,
    )
    assert json.loads(lockfile_path.read_text())["skills"] == {}
