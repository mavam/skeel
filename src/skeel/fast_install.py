from __future__ import annotations

import json
import shutil
import subprocess
import tarfile
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .manifest import SkillSpec, SourceSpec


@dataclass(frozen=True)
class ResolvedRef:
    ref: str
    commit_sha: str


@dataclass(frozen=True)
class DiscoveredSkill:
    name: str
    path: str
    directory: Path


class FastInstallError(RuntimeError):
    pass


LOCKFILE_LOCK = threading.Lock()


class FastInstallSession:
    def __init__(self, source: str) -> None:
        self.source = source
        self._archives: dict[str, tuple[tempfile.TemporaryDirectory[str], Path, ResolvedRef]] = {}
        self._tree_shas: dict[str, dict[str, str]] = {}
        self._skills: dict[str, tuple[DiscoveredSkill, ...]] = {}
        self._lock = threading.RLock()

    def install(
        self,
        source: SourceSpec,
        skill: SkillSpec | None,
        directory: Path,
    ) -> None:
        pin = effective_pin(source, skill)
        if pin is None:
            raise FastInstallError("fast install requires an explicit pin")

        _, root, resolved = self._source_archive(pin)
        tree_shas = self._source_tree_shas(resolved.commit_sha)
        skills = self._source_skills(root)
        selected = skills if skill is None else (select_skill(skills, skill, source=source.source),)
        for selected_skill in selected:
            tree_sha = tree_shas.get(selected_skill.path)
            if not tree_sha:
                raise FastInstallError(f"could not resolve tree SHA for {selected_skill.path}")
            install_skill(
                source=source.source,
                pin=pin,
                ref=resolved.ref,
                tree_sha=tree_sha,
                skill=selected_skill,
                directory=directory,
            )

    def _source_archive(
        self,
        pin: str,
    ) -> tuple[tempfile.TemporaryDirectory[str], Path, ResolvedRef]:
        with self._lock:
            if pin in self._archives:
                return self._archives[pin]
            resolved = resolve_ref(self.source, pin)
            tempdir = tempfile.TemporaryDirectory(prefix="skeel-")
            root = download_archive(self.source, resolved.commit_sha, Path(tempdir.name))
            self._archives[pin] = (tempdir, root, resolved)
            return self._archives[pin]

    def _source_tree_shas(self, commit_sha: str) -> dict[str, str]:
        with self._lock:
            if commit_sha in self._tree_shas:
                return self._tree_shas[commit_sha]
            self._tree_shas[commit_sha] = fetch_tree_shas(self.source, commit_sha)
            return self._tree_shas[commit_sha]

    def _source_skills(self, root: Path) -> tuple[DiscoveredSkill, ...]:
        key = str(root)
        with self._lock:
            if key in self._skills:
                return self._skills[key]
            self._skills[key] = discover_skills(root)
            return self._skills[key]


def supports_fast_install(source: SourceSpec, skill: SkillSpec | None) -> bool:
    return (
        not source.install
        and is_github_source(source.source)
        and effective_pin(source, skill) is not None
    )


def fast_install_command(source: SourceSpec, skill: SkillSpec | None) -> list[str]:
    pin = effective_pin(source, skill) or "<pin>"
    return ["gh", "api", f"repos/{source.source}/tarball/{pin}"]


def effective_pin(source: SourceSpec, skill: SkillSpec | None) -> str | None:
    if skill is None:
        return source.pin
    _, inline_pin = split_inline_pin(skill.spec)
    return inline_pin or skill.pin or source.pin


def skill_command_label(skill: SkillSpec) -> str:
    spec, _ = split_inline_pin(skill.spec)
    return spec


def split_inline_pin(spec: str) -> tuple[str, str | None]:
    if "@" not in spec:
        return spec, None
    name, pin = spec.rsplit("@", 1)
    return name, pin or None


def is_github_source(source: str) -> bool:
    parts = source.split("/")
    return len(parts) == 2 and all(parts)


def resolve_ref(source: str, pin: str) -> ResolvedRef:
    for prefix in ("heads", "tags"):
        result = gh_api_json(f"repos/{source}/git/ref/{prefix}/{pin}", check=False)
        if result is None:
            continue
        ref = value_as_str(result.get("ref"))
        commit_sha = resolve_commit(source, value_as_str(nested(result, "object", "sha")) or pin)
        return ResolvedRef(ref=ref or pin, commit_sha=commit_sha)

    commit_sha = resolve_commit(source, pin)
    return ResolvedRef(ref=pin, commit_sha=commit_sha)


def resolve_commit(source: str, ref: str) -> str:
    result = gh_api_json(f"repos/{source}/commits/{ref}")
    assert result is not None
    sha = value_as_str(result.get("sha"))
    if not sha:
        raise FastInstallError(f"could not resolve commit for {source}@{ref}")
    return sha


def fetch_tree_shas(source: str, commit_sha: str) -> dict[str, str]:
    result = gh_api_json(f"repos/{source}/git/trees/{commit_sha}?recursive=1")
    assert result is not None
    tree = result.get("tree")
    if not isinstance(tree, list):
        raise FastInstallError(f"could not read repository tree for {source}@{commit_sha}")

    shas: dict[str, str] = {}
    for entry in tree:
        if not isinstance(entry, dict) or entry.get("type") != "tree":
            continue
        path = value_as_str(entry.get("path"))
        sha = value_as_str(entry.get("sha"))
        if path and sha:
            shas[path] = sha
    return shas


def download_archive(source: str, commit_sha: str, directory: Path) -> Path:
    archive = directory / "source.tar.gz"
    command = ["gh", "api", f"repos/{source}/tarball/{commit_sha}"]
    with archive.open("wb") as output:
        result = subprocess.run(command, stdout=output, stderr=subprocess.PIPE)
    if result.returncode:
        stderr = result.stderr.decode(errors="replace").strip()
        raise FastInstallError(stderr or f"could not download {source}@{commit_sha}")

    extract_dir = directory / "source"
    extract_dir.mkdir()
    with tarfile.open(archive) as tar:
        tar.extractall(extract_dir, filter="data")

    roots = [path for path in extract_dir.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise FastInstallError(f"could not find archive root for {source}@{commit_sha}")
    return roots[0]


def discover_skills(root: Path) -> tuple[DiscoveredSkill, ...]:
    skills = [
        DiscoveredSkill(
            name=skill_md.parent.name,
            path=skill_md.parent.relative_to(root).as_posix(),
            directory=skill_md.parent,
        )
        for skill_md in root.rglob("SKILL.md")
        if skill_md.is_file()
    ]
    return tuple(sorted(skills, key=lambda skill: skill.path))


def select_skill(
    skills: tuple[DiscoveredSkill, ...],
    requested: SkillSpec,
    *,
    source: str | None = None,
) -> DiscoveredSkill:
    spec = skill_command_label(requested).removesuffix("/SKILL.md").rstrip("/")
    by_path = [skill for skill in skills if skill.path == spec]
    if by_path:
        return by_path[0]

    by_suffix = [skill for skill in skills if "/" in spec and skill.path.endswith(f"/{spec}")]
    if by_suffix:
        return by_suffix[0]

    by_name = [skill for skill in skills if skill.name == requested.name or skill.name == spec]
    if by_name:
        return by_name[0]

    location = source or requested.spec
    raise FastInstallError(f'skill "{requested.name}" not found in {location}')


def install_skill(
    *,
    source: str,
    pin: str,
    ref: str,
    tree_sha: str,
    skill: DiscoveredSkill,
    directory: Path,
) -> None:
    owner, repo = source.split("/", 1)
    target = directory / skill.name
    if target.exists():
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()

    directory.mkdir(parents=True, exist_ok=True)
    shutil.copytree(skill.directory, target, symlinks=False, ignore=ignore_symlinks)
    inject_github_metadata(
        target / "SKILL.md",
        owner=owner,
        repo=repo,
        ref=ref,
        tree_sha=tree_sha,
        pinned_ref=pin,
        skill_path=skill.path,
    )
    record_lockfile(
        skill_name=skill.name,
        owner=owner,
        repo=repo,
        skill_path=f"{skill.path}/SKILL.md",
        tree_sha=tree_sha,
        pinned_ref=pin,
    )


def ignore_symlinks(directory: str, names: list[str]) -> set[str]:
    return {name for name in names if (Path(directory) / name).is_symlink()}


def inject_github_metadata(
    path: Path,
    *,
    owner: str,
    repo: str,
    ref: str,
    tree_sha: str,
    pinned_ref: str,
    skill_path: str,
) -> None:
    raw_yaml, body = read_frontmatter_body(path.read_text())
    metadata = raw_yaml.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    metadata.pop("github-owner", None)
    metadata["github-repo"] = f"https://github.com/{owner}/{repo}"
    metadata["github-ref"] = ref
    metadata.pop("github-sha", None)
    metadata["github-tree-sha"] = tree_sha
    metadata["github-path"] = skill_path
    if pinned_ref:
        metadata["github-pinned"] = pinned_ref
    else:
        metadata.pop("github-pinned", None)
    raw_yaml["metadata"] = metadata
    path.write_text(serialize_frontmatter(raw_yaml, body))


def read_frontmatter_body(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() != "---":
            continue
        data = yaml.safe_load("".join(lines[1:index])) or {}
        if not isinstance(data, dict):
            data = {}
        return dict(data), "".join(lines[index + 1 :])
    return {}, text


def serialize_frontmatter(data: dict[str, Any], body: str) -> str:
    return f"---\n{yaml.safe_dump(data, sort_keys=False)}---\n{body}"


def record_lockfile(
    *,
    skill_name: str,
    owner: str,
    repo: str,
    skill_path: str,
    tree_sha: str,
    pinned_ref: str,
) -> None:
    path = Path.home() / ".agents" / ".skill-lock.json"
    with LOCKFILE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = read_lockfile(path)
        skills = data.setdefault("skills", {})
        if not isinstance(skills, dict):
            skills = {}
            data["skills"] = skills

        now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        existing = skills.get(skill_name)
        installed_at = (
            value_as_str(existing.get("installedAt")) if isinstance(existing, dict) else ""
        ) or now
        entry = {
            "source": f"{owner}/{repo}",
            "sourceType": "github",
            "sourceUrl": f"https://github.com/{owner}/{repo}.git",
            "skillPath": skill_path,
            "skillFolderHash": tree_sha,
            "installedAt": installed_at,
            "updatedAt": now,
        }
        if pinned_ref:
            entry["pinnedRef"] = pinned_ref
        skills[skill_name] = entry
        path.write_text(json.dumps(data, indent=2) + "\n")


def read_lockfile(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 3, "skills": {}}
    try:
        data = json.loads(path.read_text())
    except OSError, json.JSONDecodeError:
        return {"version": 3, "skills": {}}
    if not isinstance(data, dict) or data.get("version") != 3:
        return {"version": 3, "skills": {}}
    data.setdefault("skills", {})
    return data


def gh_api_json(path: str, *, check: bool = True) -> dict[str, Any] | None:
    result = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if result.returncode:
        if check:
            raise FastInstallError(result.stderr.strip() or f"gh api failed: {path}")
        return None

    data = json.loads(result.stdout or "{}")
    if not isinstance(data, dict):
        raise FastInstallError(f"gh api returned invalid JSON for {path}")
    return data


def nested(data: dict[str, Any], *keys: str) -> object:
    current: object = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def value_as_str(value: object) -> str:
    return value if isinstance(value, str) else ""
