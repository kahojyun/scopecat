from __future__ import annotations

import pytest

from scopecat.workflows import (
    MonitorInterleaveRequest,
    TimingBarrierRequest,
    plan_monitor_interleave,
    plan_timing_barriers,
)
from tests.support.records import assert_model_round_trip
from tests.support.workflow_scheduling import plan


def test_plan_timing_barriers_records_plan_hash_without_mutating_plan() -> None:
    base_plan = plan()
    content_hash = base_plan.content_hash

    timing_plan = plan_timing_barriers(
        run_id="run-000001",
        plan=base_plan,
        requests=[
            TimingBarrierRequest(
                barrier_id="arm-together",
                point_id=1,
                resource_ids=["source-0", "detector-0"],
                settle_time_s=0.002,
            )
        ],
    )

    assert_model_round_trip(
        timing_plan,
        schema_version="scopecat.timing_barrier_plan.v1",
    )
    assert timing_plan.run_id == "run-000001"
    assert timing_plan.plan_content_hash == content_hash
    assert timing_plan.point_count == 3
    assert [barrier.barrier_id for barrier in timing_plan.barriers] == ["arm-together"]
    assert timing_plan.diagnostics == []
    assert base_plan.content_hash == content_hash


def test_plan_timing_barriers_reports_invalid_requests() -> None:
    timing_plan = plan_timing_barriers(
        run_id="run-000002",
        plan=plan(),
        requests=[
            TimingBarrierRequest(
                barrier_id="single-resource",
                point_id=0,
                resource_ids=["source-0"],
            ),
            TimingBarrierRequest(
                barrier_id="outside-plan",
                point_id=10,
                resource_ids=["source-0", "detector-0"],
            ),
            TimingBarrierRequest(
                barrier_id="duplicate",
                point_id=1,
                resource_ids=["source-0", "detector-0"],
            ),
            TimingBarrierRequest(
                barrier_id="duplicate",
                point_id=1,
                resource_ids=["source-1", "detector-1"],
            ),
        ],
    )

    assert timing_plan.barriers == [
        TimingBarrierRequest(
            barrier_id="duplicate",
            point_id=1,
            resource_ids=["source-0", "detector-0"],
        )
    ]
    assert [diagnostic.code for diagnostic in timing_plan.diagnostics] == [
        "timing_barrier_requires_multiple_resources",
        "invalid_timing_barrier_point",
        "duplicate_timing_barrier",
    ]


def test_plan_timing_barriers_requires_run_id() -> None:
    with pytest.raises(ValueError, match="run_id must not be blank"):
        plan_timing_barriers(run_id="", plan=plan(), requests=[])


def test_plan_monitor_interleave_records_rows_without_mutating_plan() -> None:
    base_plan = plan()
    content_hash = base_plan.content_hash

    monitor_plan = plan_monitor_interleave(
        run_id="run-000003",
        plan=base_plan,
        requests=[
            MonitorInterleaveRequest(
                monitor_id="health-check",
                every_n_points=2,
                source_ref="monitors/health-check.json",
            )
        ],
    )

    assert_model_round_trip(
        monitor_plan,
        schema_version="scopecat.monitor_interleave_plan.v1",
    )
    assert monitor_plan.run_id == "run-000003"
    assert monitor_plan.plan_content_hash == content_hash
    assert monitor_plan.point_count == 3
    assert [
        (row.monitor_id, row.after_point_id, row.sequence_index, row.source_ref)
        for row in monitor_plan.rows
    ] == [("health-check", 1, 0, "monitors/health-check.json")]
    assert monitor_plan.diagnostics == []
    assert base_plan.content_hash == content_hash


def test_plan_monitor_interleave_caps_insertions() -> None:
    monitor_plan = plan_monitor_interleave(
        run_id="run-000004",
        plan=plan(),
        requests=[
            MonitorInterleaveRequest(
                monitor_id="quick-health-check",
                every_n_points=1,
                max_insertions=2,
            )
        ],
    )

    assert [row.after_point_id for row in monitor_plan.rows] == [0, 1]
    assert [row.sequence_index for row in monitor_plan.rows] == [0, 1]


def test_plan_monitor_interleave_reports_invalid_requests() -> None:
    monitor_plan = plan_monitor_interleave(
        run_id="run-000005",
        plan=plan(),
        requests=[
            MonitorInterleaveRequest(
                monitor_id="bad-interval",
                every_n_points=0,
            ),
            MonitorInterleaveRequest(
                monitor_id="bad-cap",
                every_n_points=1,
                max_insertions=0,
            ),
        ],
    )

    assert monitor_plan.rows == []
    assert [diagnostic.code for diagnostic in monitor_plan.diagnostics] == [
        "invalid_monitor_interval",
        "invalid_monitor_max_insertions",
    ]


def test_plan_monitor_interleave_requires_run_id() -> None:
    with pytest.raises(ValueError, match="run_id must not be blank"):
        plan_monitor_interleave(run_id="", plan=plan(), requests=[])
