from __future__ import annotations

import copy
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml


class FrontmatterError(ValueError):
    pass


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
    dumped = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=4096)
    return f"---\n{dumped}---\n{body}"


def update_skill_frontmatter(
    path: Path,
    *,
    disable_model_invocation: bool | None = None,
    managed_metadata: Mapping[str, Any] | None = None,
    root: Path | None = None,
) -> bool:
    if root is not None:
        validate_frontmatter_target(path, root)
    original_text = path.read_text(encoding="utf-8")
    raw_yaml, body = read_frontmatter_body(original_text)
    if disable_model_invocation is not None:
        raw_yaml["disable-model-invocation"] = disable_model_invocation
    if managed_metadata:
        metadata = raw_yaml.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            raw_yaml["metadata"] = metadata
        for key, value in managed_metadata.items():
            if value is None:
                metadata.pop(key, None)
            else:
                metadata[key] = copy.deepcopy(value)
    merged_text = serialize_frontmatter(raw_yaml, body)
    if merged_text == original_text:
        return False
    atomic_write(path, merged_text)
    return True


def model_invocation_needs_update(
    path: Path,
    disabled: bool,
    *,
    root: Path | None = None,
) -> bool:
    try:
        if root is not None:
            validate_frontmatter_target(path, root)
        raw_yaml, _ = read_frontmatter_body(path.read_text(encoding="utf-8"))
    except OSError, UnicodeError, yaml.YAMLError, FrontmatterError:
        return True
    return raw_yaml.get("disable-model-invocation") is not disabled


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
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
