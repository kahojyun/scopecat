"""Internal helpers for boundary records."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from scopecat.experiments import PlanSnapshot


@dataclass(frozen=True)
class PlanBoundary:
    """Stable plan context copied into boundary records."""

    run_id: str
    plan_content_hash: str
    point_count: int


@dataclass(frozen=True)
class PlanBoundarySummary:
    """Stable plan summary copied into execution boundary records."""

    schema_version: str
    content_hash: str
    point_count: int
    desired_state_count: int
    state_patch_count: int
    acquisition_kind: str
    acquisition_record: str
    result_intent_count: int
    expected_dataset_schema_id: str | None


def plan_boundary(*, run_id: str, plan: PlanSnapshot) -> PlanBoundary:
    """Build common run/plan metadata copied into persisted boundary records."""
    if not run_id:
        msg = "run_id must not be blank"
        raise ValueError(msg)
    return PlanBoundary(
        run_id=run_id,
        plan_content_hash=plan.content_hash,
        point_count=len(plan.points),
    )


def plan_boundary_summary(plan: PlanSnapshot) -> PlanBoundarySummary:
    """Build the static plan summary used by execution boundary manifests."""
    return PlanBoundarySummary(
        schema_version=plan.schema_version,
        content_hash=plan.content_hash,
        point_count=len(plan.points),
        desired_state_count=len(plan.desired_state),
        state_patch_count=len(plan.state_patches),
        acquisition_kind=plan.acquisition.kind,
        acquisition_record=plan.acquisition.record,
        result_intent_count=len(plan.result_intents),
        expected_dataset_schema_id=(
            plan.expected_dataset_schema.dataset_id
            if plan.expected_dataset_schema is not None
            else None
        ),
    )


def plan_point_count(plan: PlanSnapshot) -> int:
    """Return the logical point count used by boundary records."""
    return len(plan.points)


def duplicate_values(values: Sequence[int]) -> list[int]:
    seen: set[int] = set()
    duplicates: list[int] = []
    for value in values:
        if value in seen:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def invalid_point_ids(point_ids: Sequence[int], *, point_count: int) -> list[int]:
    return [
        point_id for point_id in point_ids if point_id < 0 or point_id >= point_count
    ]
