"""Internal source-file preflight for normalized primary data."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from scopecat.measurement_records._primary_table_summary import count_primary_csv_rows
from scopecat.measurement_records._storage import (
    ensure_no_symlink_parents,
    path_under,
    sha256,
)


class PrimaryDataSourceLike(Protocol):
    content_ref: str
    declared_digest: str
    size_bytes: int
    rows_recorded: int
    primary_data_format: str


def read_reviewed_primary_data_source(
    source: PrimaryDataSourceLike,
    *,
    content_root: Path,
    owner: str,
) -> bytes:
    """Read and verify one reviewed normalized primary-data source file."""

    if source.primary_data_format != "csv_table":
        raise ValueError(f"{owner} format is unsupported")
    path = path_under(content_root, source.content_ref, owner)
    ensure_no_symlink_parents(content_root, source.content_ref, owner)
    if path.is_symlink():
        raise ValueError(f"{owner} must not be a symlink")
    try:
        content = path.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError(f"{owner} is unavailable") from exc
    if sha256(content) != source.declared_digest:
        raise ValueError(f"{owner} digest does not match")
    if len(content) != source.size_bytes:
        raise ValueError(f"{owner} size does not match")
    rows = count_primary_csv_rows(content, owner=owner)
    if rows != source.rows_recorded:
        raise ValueError(f"{owner} row count does not match")
    return content
