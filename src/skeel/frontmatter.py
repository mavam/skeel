from __future__ import annotations

import copy
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

OVERRIDE_STATE_KEY = "skeel-overrides"
OVERRIDE_STATE_VERSION = 1
_PROTECTED_GITHUB_METADATA = {
    "github-owner",
    "github-repo",
    "github-ref",
    "github-sha",
    "github-tree-sha",
    "github-path",
    "github-pinned",
}


class FrontmatterError(ValueError):
    pass


def validate_frontmatter_overrides(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("skill frontmatter must be a mapping")
    validate_mapping_keys(value, path="frontmatter")
    metadata = value.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            raise ValueError("skill frontmatter metadata must be a mapping")
        for key in metadata:
            if key == OVERRIDE_STATE_KEY or key in _PROTECTED_GITHUB_METADATA:
                raise ValueError(f"skill frontmatter cannot override metadata.{key}")
    return copy.deepcopy(value)


def validate_mapping_keys(value: Mapping[object, object], *, path: str) -> None:
    for key, nested in value.items():
        if not isinstance(key, str):
            raise ValueError(f"{path} keys must be strings")
        if isinstance(nested, dict):
            validate_mapping_keys(nested, path=f"{path}.{key}")


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


def merge_skill_frontmatter(
    path: Path,
    overrides: Mapping[str, Any],
    *,
    managed_metadata: Mapping[str, Any] | None = None,
) -> bool:
    original_text = path.read_text()
    raw_yaml, body = read_frontmatter_body(original_text)
    merge_frontmatter_data(raw_yaml, overrides, managed_metadata=managed_metadata)
    merged_text = serialize_frontmatter(raw_yaml, body)
    if merged_text == original_text:
        return False
    atomic_write(path, merged_text)
    return True


def frontmatter_needs_merge(path: Path, overrides: Mapping[str, Any]) -> bool:
    try:
        original_text = path.read_text()
        raw_yaml, body = read_frontmatter_body(original_text)
        metadata = raw_yaml.get("metadata")
        if not overrides and (not isinstance(metadata, dict) or OVERRIDE_STATE_KEY not in metadata):
            return False
        merge_frontmatter_data(raw_yaml, overrides)
    except OSError, UnicodeError, yaml.YAMLError, FrontmatterError:
        return True
    return serialize_frontmatter(raw_yaml, body) != original_text


def merge_frontmatter_data(
    raw_yaml: dict[str, Any],
    overrides: Mapping[str, Any],
    *,
    managed_metadata: Mapping[str, Any] | None = None,
) -> None:
    desired = validate_frontmatter_overrides(dict(overrides))
    previous = load_override_state(raw_yaml)
    restore_originals(raw_yaml, previous)

    originals: list[dict[str, Any]] = []
    for path, value in override_units(desired):
        present, original = read_path(raw_yaml, path)
        record: dict[str, Any] = {"path": list(path), "present": present}
        if present:
            record["value"] = copy.deepcopy(original)
        originals.append(record)
        merged = deep_merge(original, value) if present else copy.deepcopy(value)
        write_path(raw_yaml, path, merged)

    if managed_metadata:
        metadata = ensure_metadata(raw_yaml)
        for key, value in managed_metadata.items():
            if value is None:
                metadata.pop(key, None)
            else:
                metadata[key] = copy.deepcopy(value)

    current_metadata = raw_yaml.get("metadata")
    if originals:
        current_metadata = ensure_metadata(raw_yaml)
        current_metadata[OVERRIDE_STATE_KEY] = {
            "version": OVERRIDE_STATE_VERSION,
            "originals": originals,
        }
    elif isinstance(current_metadata, dict):
        current_metadata.pop(OVERRIDE_STATE_KEY, None)
        if not current_metadata:
            raw_yaml.pop("metadata", None)


def override_units(overrides: Mapping[str, Any]) -> list[tuple[tuple[str, ...], Any]]:
    units: list[tuple[tuple[str, ...], Any]] = []
    for key, value in overrides.items():
        if key != "metadata":
            units.append(((key,), value))
            continue
        if not isinstance(value, Mapping):
            raise FrontmatterError("skill frontmatter metadata must be a mapping")
        for metadata_key, metadata_value in value.items():
            units.append((("metadata", metadata_key), metadata_value))
    return units


def load_override_state(raw_yaml: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = raw_yaml.get("metadata")
    if not isinstance(metadata, dict) or OVERRIDE_STATE_KEY not in metadata:
        return []
    state = metadata.pop(OVERRIDE_STATE_KEY)
    if not isinstance(state, dict) or state.get("version") != OVERRIDE_STATE_VERSION:
        raise FrontmatterError("invalid skeel frontmatter override state")
    originals = state.get("originals")
    if not isinstance(originals, list):
        raise FrontmatterError("invalid skeel frontmatter override originals")

    parsed: list[dict[str, Any]] = []
    for record in originals:
        if not isinstance(record, dict):
            raise FrontmatterError("invalid skeel frontmatter override record")
        path = record.get("path")
        present = record.get("present")
        if (
            not isinstance(path, list)
            or not path
            or not all(isinstance(part, str) for part in path)
            or not isinstance(present, bool)
            or (present and "value" not in record)
        ):
            raise FrontmatterError("invalid skeel frontmatter override record")
        parsed.append(record)
    return parsed


def restore_originals(raw_yaml: dict[str, Any], originals: list[dict[str, Any]]) -> None:
    for record in originals:
        path = tuple(record["path"])
        if record["present"]:
            write_path(raw_yaml, path, copy.deepcopy(record["value"]))
        else:
            delete_path(raw_yaml, path)


def read_path(data: dict[str, Any], path: tuple[str, ...]) -> tuple[bool, Any]:
    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return False, None
        current = current[key]
    return True, current


def write_path(data: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    current = data
    for key in path[:-1]:
        nested = current.get(key)
        if not isinstance(nested, dict):
            nested = {}
            current[key] = nested
        current = nested
    current[path[-1]] = value


def delete_path(data: dict[str, Any], path: tuple[str, ...]) -> None:
    current: Any = data
    parents: list[tuple[dict[str, Any], str]] = []
    for key in path[:-1]:
        if not isinstance(current, dict) or key not in current:
            return
        parents.append((current, key))
        current = current[key]
    if not isinstance(current, dict):
        return
    current.pop(path[-1], None)
    for parent, key in reversed(parents):
        nested = parent.get(key)
        if isinstance(nested, dict) and not nested:
            parent.pop(key)


def deep_merge(original: Any, override: Any) -> Any:
    if not isinstance(original, Mapping) or not isinstance(override, Mapping):
        return copy.deepcopy(override)
    merged = copy.deepcopy(dict(original))
    for key, value in override.items():
        if key in merged:
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def ensure_metadata(raw_yaml: dict[str, Any]) -> dict[str, Any]:
    metadata = raw_yaml.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        raw_yaml["metadata"] = metadata
    return metadata


def atomic_write(path: Path, text: str) -> None:
    mode = path.stat().st_mode
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(text)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
