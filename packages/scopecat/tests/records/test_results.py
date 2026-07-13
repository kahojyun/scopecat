from __future__ import annotations

import pytest

from scopecat.measurements.results import summarize_point_attempts
from tests.testkit.records import assert_model_round_trip


def test_summarize_point_attempts_selects_first_target_attempt() -> None:
    summary = summarize_point_attempts(
        [
            {"attempt": 0, "state": "pending"},
            {"attempt": 1, "state": "ready"},
            {"attempt": 2, "state": "ready"},
        ],
        point_index=7,
        max_attempts=4,
        target_value="ready",
        value_column="state",
        value_label="state",
    )

    restored = assert_model_round_trip(
        summary,
        schema_version="scopecat.point_attempt_summary.v3",
    )

    assert restored == summary
    assert summary.point_index == 7
    assert summary.success is True
    assert summary.attempts == 2
    assert summary.selected_attempt == 1
    assert summary.final_value == "ready"
    assert summary.value_label == "state"
    assert summary.problems == ()


def test_summarize_point_attempts_reports_failed_target() -> None:
    summary = summarize_point_attempts(
        [
            {"attempt": 0, "state": "pending"},
            {"attempt": 1, "state": "failed"},
        ],
        point_index=2,
        max_attempts=2,
        target_value="ready",
        value_column="state",
    )

    assert summary.success is False
    assert summary.attempts == 2
    assert summary.selected_attempt is None
    assert summary.final_value == "failed"
    assert summary.problems == ()


def test_summarize_point_attempts_reports_invalid_attempt_rows() -> None:
    summary = summarize_point_attempts(
        [
            {"attempt": "0", "state": "ready"},
            {"attempt": -1, "state": "ready"},
            {"attempt": 0, "state": "pending"},
            {"attempt": 0, "state": "ready"},
            {"attempt": 1, "state": {"not": "scalar"}},
        ],
        point_index=3,
        max_attempts=2,
        target_value="ready",
        value_column="state",
    )

    assert summary.success is False
    assert summary.attempts == 2
    assert summary.final_value == "pending"
    assert [problem.code for problem in summary.problems] == [
        "invalid_point_attempt",
        "invalid_point_attempt",
        "duplicate_point_attempt",
        "invalid_attempt_value",
    ]


def test_summarize_point_attempts_rejects_invalid_policy() -> None:
    with pytest.raises(ValueError, match="point_index must be nonnegative"):
        summarize_point_attempts([], point_index=-1, max_attempts=1, target_value=True)

    with pytest.raises(ValueError, match="max_attempts must be positive"):
        summarize_point_attempts([], point_index=0, max_attempts=0, target_value=True)
