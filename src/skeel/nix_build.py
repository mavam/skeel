"""Build an immutable skill tree from local sources, without installers or network IO."""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from skeel.frontmatter import load_skill_frontmatter, update_skill_frontmatter
from skeel.manifest import parse_skill, validate_skill_name

# Hidden agent directories are deliberately discoverable.
IGNORED_DIRECTORIES = {".git", ".hg", ".svn", ".venv", "__pycache__", "node_modules"}


def discover(root: Path) -> Iterator[Path]:
    """Stop at each skill root so bundled examples are not installed as extra skills."""
    if (root / "SKILL.md").is_symlink():
        raise ValueError(f"skills must be self-contained; refusing symlink: {root / 'SKILL.md'}")
    if (root / "SKILL.md").is_file():
        yield root
        return
    for child in sorted(root.iterdir()):
        if child.is_dir() and not child.is_symlink() and child.name not in IGNORED_DIRECTORIES:
            yield from discover(child)


def skill_directory(root: Path, relative: str) -> Path:
    path = Path(relative)
    if not relative or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"skill path must be relative to its source: {relative}")
    candidate = root / path
    # Do not follow symlinked components, even when they point inside the source.
    for parent in [candidate, *candidate.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError(f"symlinked skill directory: {candidate}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_dir():
        raise ValueError(f"skill directory escapes its source: {candidate}")
    if not (resolved / "SKILL.md").is_file():
        raise ValueError(f"missing SKILL.md in {candidate}")
    return resolved


def copy_skill(source: Path, destination: Path) -> None:
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"skills must be self-contained; refusing symlink: {path}")
        if not path.is_file() and not path.is_dir():
            raise ValueError(f"unsupported file in skill: {path}")
    shutil.copytree(source, destination)
    # Nix inputs are read-only. Allow the build to patch the copied frontmatter.
    for path in [destination, *destination.rglob("*")]:
        path.chmod(path.stat().st_mode | 0o200)


def build_skills(sources: Mapping[str, Any], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    owners: dict[str, str] = {}
    for label, specification in sorted(sources.items()):
        root = Path(specification["src"]).resolve(strict=True)
        if not root.is_dir():
            raise ValueError(f"source {label} is not a directory: {root}")
        selections = specification["skills"]
        if selections is None:
            selections = {}
            for directory in discover(root):
                metadata = load_skill_frontmatter(directory / "SKILL.md")
                name = metadata.get("name")
                if not isinstance(name, str):
                    raise ValueError(f"missing frontmatter name: {directory / 'SKILL.md'}")
                validate_skill_name(name)
                if name in selections:
                    raise ValueError(f"duplicate skill {name} in source {label}")
                selections[name] = {"path": str(directory.relative_to(root)), "frontmatter": {}}
        for name, settings in sorted(selections.items()):
            spec = parse_skill(
                {"spec": settings["path"], "name": name, "frontmatter": settings["frontmatter"]}
            )
            if name in owners:
                raise ValueError(f"duplicate skill {name} in sources {owners[name]} and {label}")
            owners[name] = label
            source = skill_directory(root, settings["path"])
            destination = output / name
            copy_skill(source, destination)
            metadata = load_skill_frontmatter(destination / "SKILL.md")
            if metadata.get("name") != name or spec.frontmatter:
                update_skill_frontmatter(
                    destination / "SKILL.md",
                    overrides={**spec.frontmatter, "name": name},
                    root=destination,
                )


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m skeel.nix_build SOURCES.json OUTPUT")
    try:
        build_skills(json.loads(Path(sys.argv[1]).read_text()), Path(sys.argv[2]))
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
