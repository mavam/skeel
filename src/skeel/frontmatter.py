from __future__ import annotations

import copy
import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import frontmatter
import yaml


class FrontmatterError(ValueError):
    pass


class FrontmatterAmbiguityError(FrontmatterError):
    pass


def load_skill_frontmatter(path: Path) -> dict[str, Any]:
    return dict(frontmatter.load(path, encoding="utf-8").metadata)


def dump_skill_frontmatter(post: frontmatter.Post) -> str:
    text = frontmatter.dumps(
        post,
        Dumper=yaml.SafeDumper,
        sort_keys=False,
        allow_unicode=True,
        width=4096,
    )
    return text.rstrip("\n") + "\n"


def update_skill_frontmatter(
    path: Path,
    *,
    overrides: Mapping[str, Any] | None = None,
    managed_metadata: Mapping[str, Any] | None = None,
    root: Path | None = None,
) -> bool:
    if root is not None:
        validate_frontmatter_target(path, root)
    original_text = path.read_text(encoding="utf-8")
    post = frontmatter.loads(original_text, encoding="utf-8")
    if overrides:
        for key, value in overrides.items():
            if key == "metadata" and isinstance(value, Mapping):
                metadata = post.get("metadata")
                if not isinstance(metadata, dict):
                    metadata = {}
                    post["metadata"] = metadata
                metadata.update(copy.deepcopy(value))
            else:
                post[key] = copy.deepcopy(value)
    if managed_metadata:
        metadata = post.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            post["metadata"] = metadata
        for key, value in managed_metadata.items():
            if value is None:
                metadata.pop(key, None)
            else:
                metadata[key] = copy.deepcopy(value)
    merged_text = dump_skill_frontmatter(post)
    if merged_text == original_text:
        return False
    atomic_write(path, merged_text)
    return True


def frontmatter_needs_update(
    path: Path,
    overrides: Mapping[str, Any],
    *,
    root: Path | None = None,
) -> bool:
    try:
        if root is not None:
            validate_frontmatter_target(path, root)
        metadata = load_skill_frontmatter(path)
    except OSError, UnicodeError, yaml.YAMLError, FrontmatterError:
        return True
    for key, value in overrides.items():
        if key == "metadata" and isinstance(value, Mapping):
            installed = metadata.get("metadata")
            if not isinstance(installed, Mapping) or any(
                installed.get(metadata_key) != metadata_value
                for metadata_key, metadata_value in value.items()
            ):
                return True
        elif metadata.get(key) != value:
            return True
    return False


def validate_frontmatter_target(path: Path, root: Path) -> None:
    canonical_root = root.resolve()
    if path.is_symlink():
        raise FrontmatterError(f"refusing to replace symlinked SKILL.md: {path}")
    try:
        canonical_path = path.resolve(strict=True)
    except OSError as error:
        raise FrontmatterError(f"could not resolve frontmatter target {path}: {error}") from error
    if not canonical_path.is_relative_to(canonical_root):
        raise FrontmatterError(f"refusing to update frontmatter outside target directory: {path}")


def atomic_write(path: Path, text: str) -> None:
    mode = path.stat().st_mode
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(text)
        os.chmod(temporary, stat.S_IMODE(mode))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
