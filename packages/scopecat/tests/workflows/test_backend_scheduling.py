from __future__ import annotations

import pytest

from scopecat.workflows import (
    BackendExecutionSegment,
    HardwareSweepBatch,
    plan_hardware_sweeps,
    plan_mixed_backend,
)
from tests.support.records import assert_model_round_trip
from tests.support.workflow_scheduling import plan


def test_plan_hardware_sweeps_preserves_logical_point_ids() -> None:
    base_plan = plan()
    content_hash = base_plan.content_hash

    sweep_plan = plan_hardware_sweeps(
        run_id="run-000008",
        plan=base_plan,
        batches=[
            HardwareSweepBatch(
                batch_id="batch-0",
                backend_id="qpu-0",
                point_ids=[0, 1, 2],
                program_ref="programs/qpu-0/batch-0.json",
            )
        ],
    )

    assert_model_round_trip(
        sweep_plan,
        schema_version="scopecat.hardware_sweep_plan.v1",
    )
    assert sweep_plan.run_id == "run-000008"
    assert sweep_plan.plan_content_hash == content_hash
    assert sweep_plan.point_count == 3
    assert [
        (batch.batch_id, batch.backend_id, batch.point_ids, batch.program_ref)
        for batch in sweep_plan.batches
    ] == [("batch-0", "qpu-0", [0, 1, 2], "programs/qpu-0/batch-0.json")]
    assert sweep_plan.diagnostics == []
    assert base_plan.content_hash == content_hash


def test_plan_hardware_sweeps_reports_invalid_batches() -> None:
    sweep_plan = plan_hardware_sweeps(
        run_id="run-000009",
        plan=plan(),
        batches=[
            HardwareSweepBatch(
                batch_id="empty",
                backend_id="qpu-0",
                point_ids=[],
            ),
            HardwareSweepBatch(
                batch_id="repeated",
                backend_id="qpu-0",
                point_ids=[0, 0],
            ),
            HardwareSweepBatch(
                batch_id="outside-plan",
                backend_id="qpu-0",
                point_ids=[10],
            ),
            HardwareSweepBatch(
                batch_id="accepted",
                backend_id="qpu-0",
                point_ids=[1],
            ),
            HardwareSweepBatch(
                batch_id="conflict",
                backend_id="qpu-1",
                point_ids=[1, 2],
            ),
        ],
    )

    assert sweep_plan.batches == [
        HardwareSweepBatch(
            batch_id="accepted",
            backend_id="qpu-0",
            point_ids=[1],
        )
    ]
    assert [diagnostic.code for diagnostic in sweep_plan.diagnostics] == [
        "empty_hardware_sweep_batch",
        "duplicate_hardware_batch_point",
        "invalid_hardware_batch_point",
        "hardware_batch_point_conflict",
    ]


def test_plan_hardware_sweeps_requires_run_id() -> None:
    with pytest.raises(ValueError, match="run_id must not be blank"):
        plan_hardware_sweeps(run_id="", plan=plan(), batches=[])


def test_plan_mixed_backend_records_segments_without_mutating_plan() -> None:
    base_plan = plan()
    content_hash = base_plan.content_hash

    backend_plan = plan_mixed_backend(
        run_id="run-000006",
        plan=base_plan,
        segments=[
            BackendExecutionSegment(
                backend_id="cpu-local",
                mode="host",
                point_ids=[0],
                reason="low-latency setup",
            ),
            BackendExecutionSegment(
                backend_id="hardware-batch-0",
                mode="hardware",
                point_ids=[1, 2],
                reason="contiguous hardware program",
            ),
        ],
    )

    assert_model_round_trip(
        backend_plan,
        schema_version="scopecat.mixed_backend_plan.v1",
    )
    assert backend_plan.run_id == "run-000006"
    assert backend_plan.plan_content_hash == content_hash
    assert backend_plan.point_count == 3
    assert [
        (segment.backend_id, segment.mode, segment.point_ids, segment.reason)
        for segment in backend_plan.segments
    ] == [
        ("cpu-local", "host", [0], "low-latency setup"),
        ("hardware-batch-0", "hardware", [1, 2], "contiguous hardware program"),
    ]
    assert backend_plan.diagnostics == []
    assert base_plan.content_hash == content_hash


def test_plan_mixed_backend_reports_invalid_segments() -> None:
    backend_plan = plan_mixed_backend(
        run_id="run-000007",
        plan=plan(),
        segments=[
            BackendExecutionSegment(
                backend_id="empty",
                mode="host",
                point_ids=[],
            ),
            BackendExecutionSegment(
                backend_id="repeated",
                mode="hardware",
                point_ids=[0, 0],
            ),
            BackendExecutionSegment(
                backend_id="outside-plan",
                mode="hardware",
                point_ids=[10],
            ),
            BackendExecutionSegment(
                backend_id="host-a",
                mode="host",
                point_ids=[1],
            ),
            BackendExecutionSegment(
                backend_id="hardware-conflict",
                mode="hardware",
                point_ids=[1, 2],
            ),
        ],
    )

    assert backend_plan.segments == [
        BackendExecutionSegment(
            backend_id="host-a",
            mode="host",
            point_ids=[1],
        )
    ]
    assert [diagnostic.code for diagnostic in backend_plan.diagnostics] == [
        "empty_backend_segment",
        "duplicate_backend_segment_point",
        "invalid_backend_segment_point",
        "backend_segment_point_conflict",
    ]


def test_plan_mixed_backend_requires_run_id() -> None:
    with pytest.raises(ValueError, match="run_id must not be blank"):
        plan_mixed_backend(run_id="", plan=plan(), segments=[])
