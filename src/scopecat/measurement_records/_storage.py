"""Shared storage-path primitives for measurement records."""

from __future__ import annotations

import hashlib
from pathlib import Path

from scopecat.measurement_records.creation import validate_relative_path


def existing_directory_root(root: Path, owner: str) -> Path:
    if root.is_symlink():
        raise ValueError(f"{owner} must not be a symlink")
    if not root.is_dir():
        raise ValueError(f"{owner} must be an existing directory")
    return root.resolve()


def path_under(root: Path, relative_path: str, path_owner: str) -> Path:
    return root.joinpath(*Path(validate_relative_path(relative_path, path_owner)).parts)


def ensure_no_symlink_parents(root: Path, relative_path: str, label: str) -> None:
    current = root
    parts = Path(validate_relative_path(relative_path, label)).parts
    for part in parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} parent is a symlink")
        if current.exists() and not current.is_dir():
            raise ValueError(f"{label} parent is not a directory")


def validate_strict_child_path(value: str, parent: str, owner: str) -> None:
    value_parts = Path(validate_relative_path(value, owner)).parts
    parent_parts = Path(validate_relative_path(parent, f"{owner} parent")).parts
    if len(value_parts) <= len(parent_parts) or value_parts[: len(parent_parts)] != parent_parts:
        raise ValueError(f"{owner} must stay under record_dir")


def validate_non_overlapping_paths(
    paths: tuple[str, ...],
    owner: str,
    *,
    reject_parent_child: bool,
) -> None:
    path_parts = [(path, Path(validate_relative_path(path, owner)).parts) for path in paths]
    if not reject_parent_child:
        if len({parts for _, parts in path_parts}) != len(path_parts):
            raise ValueError(f"{owner} must not overlap")
        return

    for left_index, (left_path, left_parts) in enumerate(path_parts):
        for right_path, right_parts in path_parts[left_index + 1 :]:
            shared_length = min(len(left_parts), len(right_parts))
            if left_parts[:shared_length] == right_parts[:shared_length]:
                raise ValueError(f"{owner} must not overlap: {left_path}, {right_path}")


def sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"
