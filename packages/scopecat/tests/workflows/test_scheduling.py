from __future__ import annotations

from scopecat.workflows import (
    ResourceLeaseRequest,
    plan_resource_leases,
)
from tests.support.records import assert_model_round_trip


def test_plan_resource_leases_allows_shared_leases() -> None:
    plan = plan_resource_leases(
        [
            ResourceLeaseRequest(
                run_id="run-a",
                resource_id="source-0",
                mode="shared",
            ),
            ResourceLeaseRequest(
                run_id="run-b",
                resource_id="source-0",
                mode="shared",
            ),
        ]
    )

    assert_model_round_trip(
        plan,
        schema_version="scopecat.resource_schedule_plan.v1",
    )
    assert plan.accepted_run_ids == ["run-a", "run-b"]
    assert plan.blocked_run_ids == []
    assert [lease.run_id for lease in plan.leases] == ["run-a", "run-b"]
    assert plan.diagnostics == []


def test_plan_resource_leases_blocks_exclusive_conflicts() -> None:
    plan = plan_resource_leases(
        [
            ResourceLeaseRequest(
                run_id="run-a",
                resource_id="source-0",
                mode="shared",
            ),
            ResourceLeaseRequest(
                run_id="run-b",
                resource_id="source-0",
                mode="exclusive",
            ),
            ResourceLeaseRequest(
                run_id="run-c",
                resource_id="source-1",
                mode="exclusive",
            ),
        ]
    )

    assert plan.accepted_run_ids == ["run-a", "run-c"]
    assert plan.blocked_run_ids == ["run-b"]
    assert [diagnostic.code for diagnostic in plan.diagnostics] == [
        "resource_lease_conflict"
    ]
    assert plan.diagnostics[0].path == "requests.1.resource_id"


def test_plan_resource_leases_blocks_missing_dependencies() -> None:
    plan = plan_resource_leases(
        [
            ResourceLeaseRequest(
                run_id="run-b",
                resource_id="source-1",
                mode="exclusive",
                depends_on_run_ids=["run-a"],
            ),
            ResourceLeaseRequest(
                run_id="run-a",
                resource_id="source-0",
                mode="exclusive",
            ),
        ]
    )

    assert plan.accepted_run_ids == ["run-a"]
    assert plan.blocked_run_ids == ["run-b"]
    assert [diagnostic.code for diagnostic in plan.diagnostics] == [
        "resource_lease_dependency_blocked"
    ]
    assert plan.diagnostics[0].path == "requests.0.depends_on_run_ids"
