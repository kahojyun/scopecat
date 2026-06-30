"""Crash recovery and run resume boundary records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from scopecat._boundary import invalid_point_ids, plan_boundary, plan_point_count
from scopecat.diagnostics import Diagnostic
from scopecat.experiments import PlanSnapshot

RunPointStatus = Literal["ok", "failed", "skipped"]
RetryPointStatus = Literal["ok", "failed"]


class RunResumePlan(BaseModel):
    """Concrete point selection for resuming a run without mutating the plan."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.run_resume_plan.v1"] = (
        "scopecat.run_resume_plan.v1"
    )
    completed_point_ids: list[int] = Field(default_factory=list)
    retry_point_ids: list[int] = Field(default_factory=list)
    pending_point_ids: list[int] = Field(default_factory=list)
    terminal_failed_point_ids: list[int] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class RunResumeManifest(BaseModel):
    """Persistable audit record for a run resume decision."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.run_resume_manifest.v1"] = (
        "scopecat.run_resume_manifest.v1"
    )
    run_id: str
    plan_content_hash: str
    point_count: int
    status_ref: str | None = None
    completed_point_ids: list[int] = Field(default_factory=list)
    retry_point_ids: list[int] = Field(default_factory=list)
    pending_point_ids: list[int] = Field(default_factory=list)
    terminal_failed_point_ids: list[int] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class PointRetrySummary(BaseModel):
    """Attempt selection summary for one logical point."""

    model_config = ConfigDict(extra="forbid")

    point_id: int
    attempts: int
    selected_attempt: int | None = None
    status: RetryPointStatus


class RetryResultReport(BaseModel):
    """Logical rows selected from sparse retry attempts."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.retry_result_report.v1"] = (
        "scopecat.retry_result_report.v1"
    )
    rows: list[dict[str, Any]] = Field(default_factory=list)
    points: list[PointRetrySummary] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


def plan_run_resume(
    plan: PlanSnapshot,
    rows: Sequence[Mapping[str, Any]],
    *,
    status_column: str = "status",
    retry_failed: bool = True,
) -> RunResumePlan:
    point_count = plan_point_count(plan)
    completed: set[int] = set()
    failed: set[int] = set()
    skipped: set[int] = set()
    seen: set[int] = set()
    diagnostics: list[Diagnostic] = []

    for row_index, row in enumerate(rows):
        point_id = row.get("point_id")
        if not isinstance(point_id, int) or isinstance(point_id, bool):
            diagnostics.append(
                _diagnostic(
                    "invalid_resume_point",
                    f"row {row_index} has invalid point_id {point_id!r}",
                    f"rows.{row_index}.point_id",
                )
            )
            continue
        if invalid_point_ids([point_id], point_count=point_count):
            diagnostics.append(
                _diagnostic(
                    "invalid_resume_point",
                    f"row {row_index} point_id {point_id} is out of range",
                    f"rows.{row_index}.point_id",
                )
            )
            continue
        if point_id in seen:
            diagnostics.append(
                _diagnostic(
                    "duplicate_resume_point",
                    f"row {row_index} repeats point_id {point_id}",
                    f"rows.{row_index}.point_id",
                )
            )
            continue
        seen.add(point_id)

        status_value = row.get(status_column, "ok")
        if not isinstance(status_value, str):
            diagnostics.append(
                _diagnostic(
                    "invalid_resume_status",
                    f"row {row_index} has invalid status {status_value!r}",
                    f"rows.{row_index}.{status_column}",
                )
            )
            continue
        if status_value not in {"ok", "failed", "skipped"}:
            diagnostics.append(
                _diagnostic(
                    "invalid_resume_status",
                    f"row {row_index} has unknown status {status_value!r}",
                    f"rows.{row_index}.{status_column}",
                )
            )
            continue
        if status_value == "ok":
            completed.add(point_id)
        elif status_value == "failed":
            failed.add(point_id)
        elif status_value == "skipped":
            skipped.add(point_id)

    retry: set[int] = failed if retry_failed else set()
    terminal_failed: set[int] = set() if retry_failed else failed
    pending = [
        point_id
        for point_id in range(point_count)
        if point_id not in completed
        and point_id not in skipped
        and point_id not in terminal_failed
    ]
    return RunResumePlan(
        completed_point_ids=sorted(completed),
        retry_point_ids=sorted(retry),
        pending_point_ids=pending,
        terminal_failed_point_ids=sorted(terminal_failed),
        diagnostics=diagnostics,
    )


def build_run_resume_manifest(
    *,
    run_id: str,
    plan: PlanSnapshot,
    resume: RunResumePlan,
    status_ref: str | None = None,
) -> RunResumeManifest:
    boundary = plan_boundary(run_id=run_id, plan=plan)

    return RunResumeManifest(
        run_id=boundary.run_id,
        plan_content_hash=boundary.plan_content_hash,
        point_count=boundary.point_count,
        status_ref=status_ref,
        completed_point_ids=list(resume.completed_point_ids),
        retry_point_ids=list(resume.retry_point_ids),
        pending_point_ids=list(resume.pending_point_ids),
        terminal_failed_point_ids=list(resume.terminal_failed_point_ids),
        diagnostics=list(resume.diagnostics),
    )


def summarize_retry_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    point_count: int,
    max_attempts: int,
    status_column: str = "status",
    attempt_column: str = "attempt",
) -> RetryResultReport:
    if max_attempts <= 0:
        msg = "max_attempts must be positive"
        raise ValueError(msg)

    diagnostics: list[Diagnostic] = []
    grouped: dict[int, list[Mapping[str, Any]]] = {}
    for row_index, row in enumerate(rows):
        point_id = row.get("point_id")
        attempt = row.get(attempt_column)
        if not isinstance(point_id, int) or isinstance(point_id, bool):
            diagnostics.append(
                _diagnostic(
                    "invalid_retry_point",
                    f"row {row_index} has invalid point_id {point_id!r}",
                    f"rows.{row_index}.point_id",
                )
            )
            continue
        if invalid_point_ids([point_id], point_count=point_count):
            diagnostics.append(
                _diagnostic(
                    "invalid_retry_point",
                    f"row {row_index} point_id {point_id} is out of range",
                    f"rows.{row_index}.point_id",
                )
            )
            continue
        if not isinstance(attempt, int) or isinstance(attempt, bool):
            diagnostics.append(
                _diagnostic(
                    "invalid_retry_attempt",
                    f"row {row_index} has invalid attempt {attempt!r}",
                    f"rows.{row_index}.{attempt_column}",
                )
            )
            continue
        if attempt < 0 or attempt >= max_attempts:
            diagnostics.append(
                _diagnostic(
                    "invalid_retry_attempt",
                    f"row {row_index} attempt {attempt} is out of range",
                    f"rows.{row_index}.{attempt_column}",
                )
            )
            continue
        grouped.setdefault(point_id, []).append(row)

    output_rows: list[dict[str, Any]] = []
    summaries: list[PointRetrySummary] = []
    for point_id in range(point_count):
        attempts = sorted(
            grouped.get(point_id, ()),
            key=lambda row: cast(int, row[attempt_column]),
        )
        seen_attempts: set[int] = set()
        selected: Mapping[str, Any] | None = None
        for row in attempts:
            attempt = cast(int, row[attempt_column])
            if attempt in seen_attempts:
                diagnostics.append(
                    _diagnostic(
                        "duplicate_retry_attempt",
                        f"point {point_id} repeats attempt {attempt}",
                        f"points.{point_id}.attempts.{attempt}",
                    )
                )
                continue
            seen_attempts.add(attempt)
            if row.get(status_column) == "ok" and selected is None:
                selected = row

        if selected is None:
            diagnostics.append(
                _diagnostic(
                    "point_retry_exhausted",
                    f"point {point_id} has no successful attempt",
                    f"points.{point_id}",
                )
            )
            summaries.append(
                PointRetrySummary(
                    point_id=point_id,
                    attempts=len(seen_attempts),
                    selected_attempt=None,
                    status="failed",
                )
            )
            continue

        selected_attempt = cast(int, selected[attempt_column])
        output_rows.append(
            {
                key: value
                for key, value in selected.items()
                if key not in {attempt_column, status_column}
            }
        )
        summaries.append(
            PointRetrySummary(
                point_id=point_id,
                attempts=len(seen_attempts),
                selected_attempt=selected_attempt,
                status="ok",
            )
        )

    return RetryResultReport(
        rows=output_rows,
        points=summaries,
        diagnostics=diagnostics,
    )


def _diagnostic(code: str, message: str, path: str) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message, path=path)


__all__ = [
    "PointRetrySummary",
    "RetryPointStatus",
    "RetryResultReport",
    "RunPointStatus",
    "RunResumeManifest",
    "RunResumePlan",
    "build_run_resume_manifest",
    "plan_run_resume",
    "summarize_retry_rows",
]
