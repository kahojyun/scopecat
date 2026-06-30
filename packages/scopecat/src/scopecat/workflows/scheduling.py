"""Resource scheduling boundary records."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scopecat._boundary import (
    duplicate_values,
    invalid_point_ids,
    plan_boundary,
)
from scopecat.diagnostics import Diagnostic
from scopecat.experiments import PlanSnapshot

ResourceLeaseMode = Literal["shared", "exclusive"]
BackendExecutionMode = Literal["host", "hardware"]


class BackendExecutionSegment(BaseModel):
    """Point segment assigned to a concrete execution backend."""

    model_config = ConfigDict(extra="forbid")

    backend_id: str
    mode: BackendExecutionMode
    point_ids: list[int]
    reason: str | None = None


class HardwareSweepBatch(BaseModel):
    """Hardware-internal sweep batch preserving logical plan point ids."""

    model_config = ConfigDict(extra="forbid")

    batch_id: str
    backend_id: str
    point_ids: list[int]
    program_ref: str | None = None


class HardwareSweepPlan(BaseModel):
    """Concrete hardware sweep grouping outside the experiment plan."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.hardware_sweep_plan.v1"] = (
        "scopecat.hardware_sweep_plan.v1"
    )
    run_id: str
    plan_content_hash: str
    point_count: int
    batches: list[HardwareSweepBatch] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class MixedBackendPlan(BaseModel):
    """Concrete backend split without mutating the experiment plan."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.mixed_backend_plan.v1"] = (
        "scopecat.mixed_backend_plan.v1"
    )
    run_id: str
    plan_content_hash: str
    point_count: int
    segments: list[BackendExecutionSegment] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class ResourceLeaseRequest(BaseModel):
    """Run-level resource lease request outside the experiment DSL."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    resource_id: str
    mode: ResourceLeaseMode
    depends_on_run_ids: list[str] = Field(default_factory=list)


class ResourceSchedulePlan(BaseModel):
    """Concrete scheduling decision for a batch of run resource leases."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.resource_schedule_plan.v1"] = (
        "scopecat.resource_schedule_plan.v1"
    )
    accepted_run_ids: list[str] = Field(default_factory=list)
    blocked_run_ids: list[str] = Field(default_factory=list)
    leases: list[ResourceLeaseRequest] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class TimingBarrierRequest(BaseModel):
    """Executor timing barrier request around an ordinary plan point."""

    model_config = ConfigDict(extra="forbid")

    barrier_id: str
    point_id: int
    resource_ids: list[str]
    settle_time_s: float = 0.0


class TimingBarrierPlan(BaseModel):
    """Concrete timing barrier plan derived without mutating the experiment plan."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.timing_barrier_plan.v1"] = (
        "scopecat.timing_barrier_plan.v1"
    )
    run_id: str
    plan_content_hash: str
    point_count: int
    barriers: list[TimingBarrierRequest] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class MonitorInterleaveRequest(BaseModel):
    """Workflow monitor insertion request outside the experiment DSL."""

    model_config = ConfigDict(extra="forbid")

    monitor_id: str
    every_n_points: int
    source_ref: str | None = None
    max_insertions: int | None = None


class MonitorInterleaveRow(BaseModel):
    """One monitor row selected after a logical experiment point."""

    model_config = ConfigDict(extra="forbid")

    monitor_id: str
    after_point_id: int
    sequence_index: int
    source_ref: str | None = None


class MonitorInterleavePlan(BaseModel):
    """Concrete monitor rows without inserting hidden points into the plan."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.monitor_interleave_plan.v1"] = (
        "scopecat.monitor_interleave_plan.v1"
    )
    run_id: str
    plan_content_hash: str
    point_count: int
    rows: list[MonitorInterleaveRow] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


def plan_hardware_sweeps(
    *,
    run_id: str,
    plan: PlanSnapshot,
    batches: Sequence[HardwareSweepBatch],
) -> HardwareSweepPlan:
    boundary = plan_boundary(run_id=run_id, plan=plan)
    accepted_batches: list[HardwareSweepBatch] = []
    diagnostics: list[Diagnostic] = []
    seen_point_ids: set[int] = set()

    for index, batch in enumerate(batches):
        if not batch.point_ids:
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="empty_hardware_sweep_batch",
                    message=f"hardware sweep batch {batch.batch_id} has no point ids",
                    path=f"batches.{index}.point_ids",
                )
            )
            continue

        duplicate_point_ids = duplicate_values(batch.point_ids)
        if duplicate_point_ids:
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="duplicate_hardware_batch_point",
                    message=(
                        f"hardware sweep batch {batch.batch_id} repeats point "
                        f"{duplicate_point_ids[0]}"
                    ),
                    path=f"batches.{index}.point_ids",
                )
            )
            continue

        invalid_points = invalid_point_ids(
            batch.point_ids,
            point_count=boundary.point_count,
        )
        if invalid_points:
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="invalid_hardware_batch_point",
                    message=(
                        f"hardware sweep batch {batch.batch_id} point "
                        f"{invalid_points[0]} is outside the plan"
                    ),
                    path=f"batches.{index}.point_ids",
                )
            )
            continue

        already_assigned = [
            point_id for point_id in batch.point_ids if point_id in seen_point_ids
        ]
        if already_assigned:
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="hardware_batch_point_conflict",
                    message=(
                        f"hardware sweep batch {batch.batch_id} point "
                        f"{already_assigned[0]} is already assigned"
                    ),
                    path=f"batches.{index}.point_ids",
                )
            )
            continue

        accepted_batches.append(batch)
        seen_point_ids.update(batch.point_ids)

    return HardwareSweepPlan(
        run_id=boundary.run_id,
        plan_content_hash=boundary.plan_content_hash,
        point_count=boundary.point_count,
        batches=accepted_batches,
        diagnostics=diagnostics,
    )


def plan_mixed_backend(
    *,
    run_id: str,
    plan: PlanSnapshot,
    segments: Sequence[BackendExecutionSegment],
) -> MixedBackendPlan:
    boundary = plan_boundary(run_id=run_id, plan=plan)
    accepted_segments: list[BackendExecutionSegment] = []
    diagnostics: list[Diagnostic] = []
    seen_point_ids: set[int] = set()

    for index, segment in enumerate(segments):
        if not segment.point_ids:
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="empty_backend_segment",
                    message=f"backend {segment.backend_id} has no point ids",
                    path=f"segments.{index}.point_ids",
                )
            )
            continue

        duplicate_point_ids = duplicate_values(segment.point_ids)
        if duplicate_point_ids:
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="duplicate_backend_segment_point",
                    message=(
                        f"backend {segment.backend_id} repeats point "
                        f"{duplicate_point_ids[0]}"
                    ),
                    path=f"segments.{index}.point_ids",
                )
            )
            continue

        invalid_points = invalid_point_ids(
            segment.point_ids,
            point_count=boundary.point_count,
        )
        if invalid_points:
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="invalid_backend_segment_point",
                    message=(
                        f"backend {segment.backend_id} point {invalid_points[0]} "
                        "is outside the plan"
                    ),
                    path=f"segments.{index}.point_ids",
                )
            )
            continue

        already_assigned = [
            point_id for point_id in segment.point_ids if point_id in seen_point_ids
        ]
        if already_assigned:
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="backend_segment_point_conflict",
                    message=(
                        f"backend {segment.backend_id} point {already_assigned[0]} "
                        "is already assigned"
                    ),
                    path=f"segments.{index}.point_ids",
                )
            )
            continue

        accepted_segments.append(segment)
        seen_point_ids.update(segment.point_ids)

    return MixedBackendPlan(
        run_id=boundary.run_id,
        plan_content_hash=boundary.plan_content_hash,
        point_count=boundary.point_count,
        segments=accepted_segments,
        diagnostics=diagnostics,
    )


def plan_resource_leases(
    requests: Sequence[ResourceLeaseRequest],
) -> ResourceSchedulePlan:
    accepted: list[ResourceLeaseRequest] = []
    accepted_run_ids: list[str] = []
    blocked_run_ids: list[str] = []
    diagnostics: list[Diagnostic] = []

    for index, request in enumerate(requests):
        missing_dependencies = [
            run_id
            for run_id in request.depends_on_run_ids
            if run_id not in accepted_run_ids
        ]
        if missing_dependencies:
            blocked_run_ids.append(request.run_id)
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="resource_lease_dependency_blocked",
                    message=(
                        f"run {request.run_id} waits for dependencies "
                        f"{', '.join(missing_dependencies)}"
                    ),
                    path=f"requests.{index}.depends_on_run_ids",
                )
            )
            continue

        conflicting = _conflicting_leases(accepted, request)
        if conflicting:
            blocked_run_ids.append(request.run_id)
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="resource_lease_conflict",
                    message=(
                        f"run {request.run_id} conflicts with accepted run "
                        f"{conflicting[0].run_id} on resource {request.resource_id}"
                    ),
                    path=f"requests.{index}.resource_id",
                )
            )
            continue

        accepted.append(request)
        accepted_run_ids.append(request.run_id)

    return ResourceSchedulePlan(
        accepted_run_ids=accepted_run_ids,
        blocked_run_ids=blocked_run_ids,
        leases=list(accepted),
        diagnostics=diagnostics,
    )


def plan_monitor_interleave(
    *,
    run_id: str,
    plan: PlanSnapshot,
    requests: Sequence[MonitorInterleaveRequest],
) -> MonitorInterleavePlan:
    boundary = plan_boundary(run_id=run_id, plan=plan)
    rows: list[MonitorInterleaveRow] = []
    diagnostics: list[Diagnostic] = []

    for index, request in enumerate(requests):
        if request.every_n_points <= 0:
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="invalid_monitor_interval",
                    message=(
                        f"monitor {request.monitor_id} has invalid interval "
                        f"{request.every_n_points}"
                    ),
                    path=f"requests.{index}.every_n_points",
                )
            )
            continue
        if request.max_insertions is not None and request.max_insertions <= 0:
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="invalid_monitor_max_insertions",
                    message=(
                        f"monitor {request.monitor_id} has invalid max insertions "
                        f"{request.max_insertions}"
                    ),
                    path=f"requests.{index}.max_insertions",
                )
            )
            continue

        after_point_ids = list(
            range(
                request.every_n_points - 1,
                boundary.point_count,
                request.every_n_points,
            )
        )
        if request.max_insertions is not None:
            after_point_ids = after_point_ids[: request.max_insertions]
        rows.extend(
            MonitorInterleaveRow(
                monitor_id=request.monitor_id,
                after_point_id=point_id,
                sequence_index=sequence_index,
                source_ref=request.source_ref,
            )
            for sequence_index, point_id in enumerate(after_point_ids)
        )

    return MonitorInterleavePlan(
        run_id=boundary.run_id,
        plan_content_hash=boundary.plan_content_hash,
        point_count=boundary.point_count,
        rows=rows,
        diagnostics=diagnostics,
    )


def plan_timing_barriers(
    *,
    run_id: str,
    plan: PlanSnapshot,
    requests: Sequence[TimingBarrierRequest],
) -> TimingBarrierPlan:
    boundary = plan_boundary(run_id=run_id, plan=plan)
    barriers: list[TimingBarrierRequest] = []
    diagnostics: list[Diagnostic] = []
    seen: set[tuple[str, int]] = set()

    for index, request in enumerate(requests):
        key = (request.barrier_id, request.point_id)
        if key in seen:
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="duplicate_timing_barrier",
                    message=(
                        f"barrier {request.barrier_id} repeats point {request.point_id}"
                    ),
                    path=f"requests.{index}.barrier_id",
                )
            )
            continue
        seen.add(key)

        if invalid_point_ids([request.point_id], point_count=boundary.point_count):
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="invalid_timing_barrier_point",
                    message=(
                        f"barrier {request.barrier_id} point {request.point_id} "
                        "is outside the plan"
                    ),
                    path=f"requests.{index}.point_id",
                )
            )
            continue
        if len(set(request.resource_ids)) < 2:
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="timing_barrier_requires_multiple_resources",
                    message=(
                        f"barrier {request.barrier_id} must include at least two "
                        "resources"
                    ),
                    path=f"requests.{index}.resource_ids",
                )
            )
            continue

        barriers.append(request)

    return TimingBarrierPlan(
        run_id=boundary.run_id,
        plan_content_hash=boundary.plan_content_hash,
        point_count=boundary.point_count,
        barriers=barriers,
        diagnostics=diagnostics,
    )


def _conflicting_leases(
    accepted: Sequence[ResourceLeaseRequest],
    request: ResourceLeaseRequest,
) -> list[ResourceLeaseRequest]:
    if request.mode == "shared":
        return [
            lease
            for lease in accepted
            if lease.resource_id == request.resource_id and lease.mode == "exclusive"
        ]
    return [lease for lease in accepted if lease.resource_id == request.resource_id]
