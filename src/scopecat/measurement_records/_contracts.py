"""Shared Measurement Records route-local contracts."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

PUBLIC_IDENTIFIER_MAX_LENGTH = 128
MANIFEST_SCHEMA = "measurement_record_creation_v0"
WRITER_RECEIPT_SCHEMA = "measurement_record_writer_receipt_v0"
FINALIZATION_RECEIPT_SCHEMA = "measurement_record_finalization_receipt_v0"
APPROVAL_STATES = {"approved", "rejected", "needs_review"}
INITIAL_LIFECYCLE_STATES = {"created", "in_progress", "review_needed"}
CREATION_SOURCE_KINDS = {"manual", "writer", "import", "handoff", "legacy_system"}
RECORD_MANIFEST_NAME = "record-manifest.json"

_PUBLIC_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PRIVATE_PATH_SEGMENTS = {"Users", "private"}
_PRIVATE_PATH_MARKERS = tuple(f"/{part}/" for part in _PRIVATE_PATH_SEGMENTS)


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


def validate_relative_path(value: Any, owner: str) -> str:
    if not _path_is_relative(value):
        raise ValueError(f"{owner} path must be relative")
    return value


def relative_path_parts(value: Any, owner: str = "path") -> tuple[str, ...]:
    return PurePosixPath(validate_relative_path(value, owner)).parts


def validate_text(value: Any, owner: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{owner} must be text")
    return value


def validate_positive_integer(value: Any, owner: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{owner} must be positive")
    return value


def validate_sha256_digest(value: Any, owner: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value.removeprefix("sha256:"))
    ):
        raise ValueError(f"{owner} must be a sha256-prefixed hex digest")
    return value


def validate_public_path_segments(value: str, owner: str) -> None:
    for segment in relative_path_parts(value, owner):
        if segment in _PRIVATE_PATH_SEGMENTS:
            raise ValueError(f"{owner} path segments must be public-safe")
        try:
            validate_public_identifier(segment, f"{owner} path segment")
        except ValueError as exc:
            raise ValueError(f"{owner} path segments must be public-safe") from exc


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
