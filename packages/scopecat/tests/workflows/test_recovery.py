from __future__ import annotations

import pytest

from scopecat.experiments import PlanSnapshot, acquire, experiment, plan_experiment
from scopecat.relations import ParameterRelationData, grid
from scopecat.workflows import (
    RunResumePlan,
    build_run_resume_manifest,
    plan_run_resume,
    summarize_retry_rows,
)
from tests.support.records import assert_model_round_trip


def test_plan_run_resume_selects_pending_and_retry_points() -> None:
    plan = _plan()
    original_content_hash = plan.content_hash

    resume = plan_run_resume(
        plan,
        [
            {"point_id": 0, "status": "ok"},
            {"point_id": 1, "status": "failed"},
            {"point_id": 3, "status": "skipped"},
        ],
    )

    assert_model_round_trip(
        resume,
        schema_version="scopecat.run_resume_plan.v1",
    )
    assert resume.completed_point_ids == [0]
    assert resume.retry_point_ids == [1]
    assert resume.pending_point_ids == [1, 2]
    assert resume.terminal_failed_point_ids == []
    assert resume.diagnostics == []
    assert plan.content_hash == original_content_hash


def test_plan_run_resume_can_leave_failed_points_terminal() -> None:
    resume = plan_run_resume(
        _plan(),
        [
            {"point_id": 0, "status": "ok"},
            {"point_id": 1, "status": "failed"},
        ],
        retry_failed=False,
    )

    assert resume.completed_point_ids == [0]
    assert resume.retry_point_ids == []
    assert resume.pending_point_ids == [2, 3]
    assert resume.terminal_failed_point_ids == [1]


def test_plan_run_resume_reports_invalid_status_rows() -> None:
    resume = plan_run_resume(
        _plan(),
        [
            {"point_id": "0", "status": "ok"},
            {"point_id": 0, "status": "ok"},
            {"point_id": 0, "status": "ok"},
            {"point_id": 10, "status": "ok"},
            {"point_id": 2, "status": "unknown"},
            {"point_id": 3, "status": 3},
        ],
    )

    assert [diagnostic.code for diagnostic in resume.diagnostics] == [
        "invalid_resume_point",
        "duplicate_resume_point",
        "invalid_resume_point",
        "invalid_resume_status",
        "invalid_resume_status",
    ]
    assert resume.completed_point_ids == [0]
    assert resume.pending_point_ids == [1, 2, 3]


def test_build_run_resume_manifest_records_plan_hash_and_point_selection() -> None:
    plan = _plan()
    resume = plan_run_resume(
        plan,
        [
            {"point_id": 0, "status": "ok"},
            {"point_id": 1, "status": "failed"},
            {"point_id": 3, "status": "skipped"},
        ],
    )

    manifest = build_run_resume_manifest(
        run_id="run-000001",
        plan=plan,
        resume=resume,
        status_ref="artifacts/point-status.jsonl",
    )
    restored = assert_model_round_trip(
        manifest,
        schema_version="scopecat.run_resume_manifest.v1",
    )

    assert restored == manifest
    assert manifest.run_id == "run-000001"
    assert manifest.plan_content_hash == plan.content_hash
    assert manifest.point_count == 4
    assert manifest.status_ref == "artifacts/point-status.jsonl"
    assert manifest.completed_point_ids == [0]
    assert manifest.retry_point_ids == [1]
    assert manifest.pending_point_ids == [1, 2]
    assert manifest.terminal_failed_point_ids == []
    assert manifest.diagnostics == []

    resume.retry_point_ids.append(2)
    assert manifest.retry_point_ids == [1]


def test_build_run_resume_manifest_copies_resume_diagnostics() -> None:
    resume = plan_run_resume(
        _plan(),
        [
            {"point_id": "0", "status": "ok"},
            {"point_id": 0, "status": "unknown"},
        ],
    )

    manifest = build_run_resume_manifest(
        run_id="run-000002",
        plan=_plan(),
        resume=resume,
    )

    assert [diagnostic.code for diagnostic in manifest.diagnostics] == [
        "invalid_resume_point",
        "invalid_resume_status",
    ]


def test_build_run_resume_manifest_requires_run_id() -> None:
    with pytest.raises(ValueError, match="run_id must not be blank"):
        build_run_resume_manifest(run_id="", plan=_plan(), resume=RunResumePlan())


def test_summarize_retry_rows_selects_successful_attempts() -> None:
    report = summarize_retry_rows(
        [
            {"point_id": 0, "attempt": 0, "status": "failed", "signal": 0.1},
            {"point_id": 0, "attempt": 1, "status": "ok", "signal": 0.9},
            {"point_id": 1, "attempt": 0, "status": "failed", "signal": 0.2},
            {"point_id": 1, "attempt": 1, "status": "failed", "signal": 0.3},
            {"point_id": 2, "attempt": 0, "status": "ok", "signal": 0.8},
        ],
        point_count=3,
        max_attempts=2,
    )

    assert_model_round_trip(
        report,
        schema_version="scopecat.retry_result_report.v1",
    )
    assert report.rows == [
        {"point_id": 0, "signal": 0.9},
        {"point_id": 2, "signal": 0.8},
    ]
    assert [
        (point.point_id, point.attempts, point.selected_attempt, point.status)
        for point in report.points
    ] == [
        (0, 2, 1, "ok"),
        (1, 2, None, "failed"),
        (2, 1, 0, "ok"),
    ]
    assert [diagnostic.code for diagnostic in report.diagnostics] == [
        "point_retry_exhausted",
    ]


def test_summarize_retry_rows_reports_invalid_attempt_rows() -> None:
    report = summarize_retry_rows(
        [
            {"point_id": "0", "attempt": 0, "status": "ok"},
            {"point_id": 0, "attempt": -1, "status": "ok"},
            {"point_id": 0, "attempt": 0, "status": "failed"},
            {"point_id": 0, "attempt": 0, "status": "ok"},
            {"point_id": 10, "attempt": 0, "status": "ok"},
        ],
        point_count=1,
        max_attempts=2,
    )

    assert [diagnostic.code for diagnostic in report.diagnostics] == [
        "invalid_retry_point",
        "invalid_retry_attempt",
        "invalid_retry_point",
        "duplicate_retry_attempt",
        "point_retry_exhausted",
    ]
    assert_model_round_trip(report)
    assert report.rows == []
    assert [
        (point.point_id, point.attempts, point.selected_attempt, point.status)
        for point in report.points
    ] == [(0, 1, None, "failed")]


def test_summarize_retry_rows_requires_positive_max_attempts() -> None:
    with pytest.raises(ValueError, match="max_attempts must be positive"):
        summarize_retry_rows([], point_count=1, max_attempts=0)


def _plan() -> PlanSnapshot:
    spec = experiment(
        id="resume-boundary",
        kind="workflow.resume",
        points=grid(point=[0, 1, 2, 3]),
        acquire=acquire("measurement"),
    )
    return plan_experiment(spec, params=ParameterRelationData())
