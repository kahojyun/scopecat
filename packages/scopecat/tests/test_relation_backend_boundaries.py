from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import scopecat as sc
import scopecat.authoring as authoring
from scopecat._compiler.binding import bind_program
from scopecat._compiler.environment import validate_config_environment
from scopecat._relation_analysis import RelationOperation
from scopecat._relation_backend import (
    PreparedRelationEvaluation,
    ReferenceRelationBackend,
    RelationBackendCapabilityIssue,
    RelationPlanRequirements,
)
from scopecat._relations import RelationExpr, Row
from scopecat.authoring._invocation_plan import prepare_invocation
from scopecat.authoring._resolution import (
    compile_prepared_invocation,
    resolve_compiled_invocation,
)
from scopecat.problems import ModelLocation, ProblemCategory, ProblemPhase
from tests.support.workflow_fixtures import load_config, load_experiment


class _TrackingBackend(ReferenceRelationBackend):
    assessed_operations: list[tuple[RelationOperation, ...]]
    materialized_relations: list[tuple[RelationOperation, ...]]

    def __init__(
        self,
        *,
        backend_id: str,
        unsupported_operations: frozenset[RelationOperation],
    ) -> None:
        super().__init__(
            backend_id=backend_id,
            supported_operations=(
                frozenset(RelationOperation) - unsupported_operations
            ),
        )
        object.__setattr__(self, "assessed_operations", [])
        object.__setattr__(self, "materialized_relations", [])

    def assess_relation_requirements(
        self,
        requirements: RelationPlanRequirements,
    ) -> Sequence[RelationBackendCapabilityIssue]:
        self.assessed_operations.append(requirements.required_operations)
        return super().assess_relation_requirements(requirements)

    def materialize_relation(
        self,
        evaluation: PreparedRelationEvaluation[RelationExpr],
    ) -> list[Row]:
        self.materialized_relations.append(evaluation.selected_plan.required_operations)
        return super().materialize_relation(evaluation)


def _static_record_axis_invocation() -> authoring.ExperimentInvocation:
    axis_size = sc.input("axis_size", sc.ScalarType(sc.IntType()))
    module = (
        authoring.module("test.static-record-axis-backend-boundary")
        .inputs(axis_size)
        .resource("source")
        .record(
            "signal",
            resource="source",
            axes=(sc.record_axis("sample", size=axis_size + 1),),
        )
        .build()
    )
    template = (
        module.template(
            "test.static-record-axis-backend-boundary",
            kind="backend-boundary",
        )
        .experiment_id("static-record-axis-backend-boundary")
        .build()
    )
    return template.bind(axis_size=2)


def test_record_axis_static_evaluation_is_isolated_from_target_backend(
    tmp_path: Path,
) -> None:
    environment = validate_config_environment(load_config())
    target_backend = _TrackingBackend(
        backend_id="tests.target-without-static-binary",
        unsupported_operations=frozenset({RelationOperation.SCALAR_BINARY}),
    )
    compiled = compile_prepared_invocation(
        prepare_invocation(_static_record_axis_invocation())
    )

    resolved = resolve_compiled_invocation(
        compiled,
        environment=environment,
        workspace=tmp_path,
    )

    assert target_backend.assessed_operations == []
    assert target_backend.materialized_relations == []
    assert resolved.experiment.product_defs[0].axes[0].size == 3

    plan = bind_program(
        resolved.experiment,
        environment,
        relation_backend=target_backend,
    )

    assert plan.valid, plan.problems
    assert plan.point_count == 1
    assert target_backend.assessed_operations == []
    assert target_backend.materialized_relations == []


def test_target_backend_rejection_precedes_point_materialization() -> None:
    environment = validate_config_environment(load_config())
    target_backend = _TrackingBackend(
        backend_id="tests.target-without-point-column",
        unsupported_operations=frozenset({RelationOperation.SCALAR_POINT_COLUMN}),
    )

    plan = bind_program(
        load_experiment(),
        environment,
        relation_backend=target_backend,
    )

    assert not plan.valid
    assert plan.points == ()
    assert target_backend.materialized_relations == []
    assert any(
        RelationOperation.RELATION_GRID in operations
        for operations in target_backend.assessed_operations
    )
    assert any(
        RelationOperation.SCALAR_POINT_COLUMN in operations
        for operations in target_backend.assessed_operations
    )

    assert len(plan.problems) == 1
    problem = plan.problems[0]
    assert problem.code == "relation_backend_capability_unsupported"
    assert problem.category is ProblemCategory.UNAVAILABLE
    assert problem.phase is ProblemPhase.PLANNING
    assert isinstance(problem.location, ModelLocation)
    assert problem.location.root == "state"
    assert problem.location.path == (0, "value")
    assert problem.details == {
        "backend_id": "tests.target-without-point-column",
        "consumer_kind": "state_value",
        "consumer_location": {"root": "state", "path": (0, "value")},
        "capability_dimension": "operation",
        "capability_code": "scalar.point_column",
        "plan_path": (),
    }
