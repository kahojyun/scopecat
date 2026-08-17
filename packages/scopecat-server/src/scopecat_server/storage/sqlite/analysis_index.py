"""Shared relational index operations for run and project analyses."""

from __future__ import annotations

import sqlite3
from typing import cast

from scopecat.analysis.repository import (
    AnalysisPublication,
    AnalysisPublicationPage,
    AnalysisPublicationSummary,
)
from scopecat.records.analysis import ProjectAnalysisSubject, RunAnalysisSubject
from scopecat.records.content import ContentEntry


class AnalysisIndexConflict(ValueError):
    """An immutable publication identity already has different metadata."""


def insert_publication(
    connection: sqlite3.Connection,
    publication: AnalysisPublication,
) -> tuple[int, bool]:
    """Insert one immutable index row and return its sequence and creation state."""

    subject_kind, run_id = _owner(publication)
    existing = cast(
        "sqlite3.Row | None",
        connection.execute(
            """
            SELECT sequence, record_entry_json, analysis_key, revision,
                   publication_hash, title, step_id, input_count, output_count
            FROM analysis_publications
            WHERE subject_kind = ?
              AND record_id = ?
              AND ((run_id IS NULL AND ? IS NULL) OR run_id = ?)
            """,
            (subject_kind, publication.record.id, run_id, run_id),
        ).fetchone(),
    )
    expected = _publication_values(publication)
    if existing is not None:
        actual = tuple(existing[key] for key in _PUBLICATION_VALUE_KEYS)
        if actual != expected:
            raise AnalysisIndexConflict(publication.record.id)
        return cast("int", existing["sequence"]), False

    inserted = connection.execute(
        """
        INSERT INTO analysis_publications(
            subject_kind, run_id, record_id, record_entry_json, analysis_key,
            revision, publication_hash, title, step_id, input_count, output_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            subject_kind,
            run_id,
            publication.record.id,
            *expected,
        ),
    )
    return cast("int", inserted.lastrowid), True


def list_publications(
    connection: sqlite3.Connection,
    *,
    run_id: str | None,
    limit: int,
    before: int | None,
) -> AnalysisPublicationPage:
    clauses = [_owner_clause(run_id)]
    parameters: list[str | int] = [] if run_id is None else [run_id]
    if before is not None:
        clauses.append("sequence < ?")
        parameters.append(before)
    parameters.append(limit + 1)
    rows = cast(
        "list[sqlite3.Row]",
        connection.execute(
            f"""
            SELECT sequence, subject_kind, run_id, record_entry_json, title,
                   analysis_key, revision, publication_hash, step_id,
                   input_count, output_count
            FROM analysis_publications
            WHERE {" AND ".join(clauses)}
            ORDER BY sequence DESC
            LIMIT ?
            """,  # noqa: S608 - clauses are fixed internal SQL fragments
            parameters,
        ).fetchall(),
    )
    selected = rows[:limit]
    return AnalysisPublicationPage(
        items=tuple(summary_from_row(row) for row in selected),
        next_cursor=(
            cast("int", selected[-1]["sequence"]) if len(rows) > limit else None
        ),
    )


def read_publication(
    connection: sqlite3.Connection,
    *,
    run_id: str | None,
    record_id: str,
) -> AnalysisPublicationSummary | None:
    parameters: list[str] = [] if run_id is None else [run_id]
    parameters.append(record_id)
    row = cast(
        "sqlite3.Row | None",
        connection.execute(
            f"""
            SELECT subject_kind, run_id, record_entry_json, title, analysis_key,
                   revision, publication_hash, step_id, input_count, output_count
            FROM analysis_publications
            WHERE {_owner_clause(run_id)} AND record_id = ?
            """,  # noqa: S608 - owner clause is a fixed internal SQL fragment
            parameters,
        ).fetchone(),
    )
    return None if row is None else summary_from_row(row)


def latest_publication(
    connection: sqlite3.Connection,
    *,
    run_id: str | None,
    analysis_key: str,
) -> AnalysisPublicationSummary | None:
    parameters: list[str] = [] if run_id is None else [run_id]
    parameters.append(analysis_key)
    row = cast(
        "sqlite3.Row | None",
        connection.execute(
            f"""
            SELECT subject_kind, run_id, record_entry_json, title, analysis_key,
                   revision, publication_hash, step_id, input_count, output_count
            FROM analysis_publications
            WHERE {_owner_clause(run_id)} AND analysis_key = ?
            ORDER BY revision DESC
            LIMIT 1
            """,  # noqa: S608 - owner clause is a fixed internal SQL fragment
            parameters,
        ).fetchone(),
    )
    return None if row is None else summary_from_row(row)


def summary_from_row(row: sqlite3.Row) -> AnalysisPublicationSummary:
    run_id = cast("str | None", row["run_id"])
    subject = (
        ProjectAnalysisSubject()
        if run_id is None
        else RunAnalysisSubject(run_id=run_id)
    )
    return AnalysisPublicationSummary(
        subject=subject,
        record=ContentEntry.model_validate_json(cast("str", row["record_entry_json"])),
        title=cast("str", row["title"]),
        analysis_key=cast("str", row["analysis_key"]),
        revision=cast("int", row["revision"]),
        publication_hash=cast("str", row["publication_hash"]),
        step_id=cast("str | None", row["step_id"]),
        input_count=cast("int", row["input_count"]),
        output_count=cast("int", row["output_count"]),
    )


_PUBLICATION_VALUE_KEYS = (
    "record_entry_json",
    "analysis_key",
    "revision",
    "publication_hash",
    "title",
    "step_id",
    "input_count",
    "output_count",
)


def _publication_values(publication: AnalysisPublication) -> tuple[object, ...]:
    return (
        publication.record.model_dump_json(),
        publication.analysis_key,
        publication.revision,
        publication.publication_hash,
        publication.title,
        publication.step_id,
        publication.input_count,
        publication.output_count,
    )


def _owner(publication: AnalysisPublication) -> tuple[str, str | None]:
    subject = publication.subject
    if isinstance(subject, RunAnalysisSubject):
        return "run", subject.run_id
    return "project", None


def _owner_clause(run_id: str | None) -> str:
    if run_id is None:
        return "subject_kind = 'project' AND run_id IS NULL"
    return "subject_kind = 'run' AND run_id = ?"


__all__ = [
    "AnalysisIndexConflict",
    "insert_publication",
    "latest_publication",
    "list_publications",
    "read_publication",
]
