"""Small shared contract primitives for parameter-state prototypes.

These helpers validate repeated low-level facts before prototype code uses
them as path segments, relation targets, manifest references, or write roots.
They intentionally do not define a measurement-record model, package schema, or
redaction engine.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

PUBLIC_IDENTIFIER_MAX_LENGTH = 128

_PUBLIC_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PRIVATE_PATH_MARKERS = tuple(f"/{part}/" for part in ("Users", "private"))


def _path_is_relative(path: Any) -> bool:
    if not isinstance(path, str):
        return False
    parsed = PurePosixPath(path)
    raw_parts = path.split("/")
    return (
        bool(path)
        and path != "."
        and "\\" not in path
        and not re.match(r"^[A-Za-z]:", path)
        and not parsed.is_absolute()
        and not any(part in {"", ".", ".."} for part in raw_parts)
    )


def validate_relative_path(value: Any, owner: str) -> str:
    if not _path_is_relative(value):
        raise ValueError(f"{owner} path must be relative")
    return value


def relative_path_parts(value: Any, owner: str = "path") -> tuple[str, ...]:
    return PurePosixPath(validate_relative_path(value, owner)).parts


def validate_strict_child_path(value: Any, parent: str, owner: str) -> str:
    path_parts = relative_path_parts(value, owner)
    parent_parts = relative_path_parts(parent, f"{owner} parent")
    if len(path_parts) <= len(parent_parts) or path_parts[: len(parent_parts)] != parent_parts:
        raise ValueError(f"{owner} must stay under {parent}")
    return value


def validate_public_identifier(value: Any, owner: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > PUBLIC_IDENTIFIER_MAX_LENGTH
        or value in {".", ".."}
        or not _PUBLIC_IDENTIFIER.fullmatch(value)
        or value.startswith(("/", "~"))
        or "/" in value
        or "\\" in value
        or re.match(r"^[A-Za-z]:", value)
        or any(marker in value for marker in _PRIVATE_PATH_MARKERS)
    ):
        raise ValueError(f"{owner} must be a public-safe identifier")
    return value


def validate_text(value: Any, owner: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{owner} must be text")
    return value


def validate_non_negative_integer(value: Any, owner: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{owner} must be a non-negative integer")
    return value


def validate_positive_integer(value: Any, owner: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{owner} must be positive")
    return value


def validate_sha256_digest(value: Any, owner: str) -> str:
    if not isinstance(value, str) or not _SHA256_DIGEST.fullmatch(value):
        raise ValueError(f"{owner} must be a sha256-prefixed hex digest")
    return value


def validate_redacted_display_ref(value: Any, owner: str, *, prefix: str) -> str:
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ValueError(f"{owner} must be a public-safe redacted display reference")

    payload = value.removeprefix(prefix)
    expected_prefix = "/redacted/"
    if not payload.startswith(expected_prefix):
        raise ValueError(f"{owner} must be a public-safe redacted display reference")

    redacted_id = payload.removeprefix(expected_prefix)
    if redacted_id in {"Users", "private"}:
        raise ValueError(f"{owner} must be a public-safe redacted display reference")
    try:
        validate_public_identifier(redacted_id, owner)
    except ValueError as exc:
        raise ValueError(f"{owner} must be a public-safe redacted display reference") from exc
    return value


def validate_package_primary_data_path(
    value: Any,
    *,
    measurement_record_id: str,
    owner: str,
) -> str:
    validate_public_identifier(measurement_record_id, "measurement_record_id")
    validate_relative_path(value, owner)
    expected_path = f"measurements/{measurement_record_id}/primary.csv"
    if value != expected_path:
        raise ValueError(f"{owner} path must be {expected_path}")
    return value


def validate_unique_reference_targets(
    value: Any,
    *,
    selected_ids: set[str],
    owner: str,
) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{owner} targets must be a list")
    for target_id in value:
        validate_public_identifier(target_id, f"{owner} measurement target")
    target_ids = set(value)
    if len(target_ids) != len(value):
        raise ValueError(f"{owner} targets must be unique")
    if not target_ids or not target_ids.issubset(selected_ids):
        raise ValueError(f"{owner} must reference selected measurements")
    return list(value)


def _path_same_or_under(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def validate_package_root_outside_storage(
    storage_root: Path,
    package_root: Path,
    *,
    owner: str,
) -> None:
    if _path_same_or_under(package_root, storage_root):
        raise ValueError(f"{owner} package root must be outside measurement storage")
