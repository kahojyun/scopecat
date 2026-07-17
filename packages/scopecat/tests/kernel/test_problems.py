from __future__ import annotations

from typing import cast

import pytest
from pydantic import ValidationError

from scopecat.kernel.errors import (
    CheckFailed,
    Conflict,
    MeasurementTransformExecutionError,
    OperationFailure,
    ProblemFailure,
    ProviderContractError,
)
from scopecat.kernel.problems import (
    ExternalLocation,
    ModelLocation,
    Problem,
    ProblemCategory,
    ProblemImpact,
    ProblemPhase,
    StorageLocation,
    blocking_problem,
    model_location,
)


def test_problem_v1_is_deeply_frozen_and_json_round_trips() -> None:
    problem = blocking_problem(
        "authoring.missing_input",
        "required input is missing",
        category=ProblemCategory.INVALID_INPUT,
        phase=ProblemPhase.AUTHORING,
        location=model_location("template", "inputs", "drive.frequency"),
        related_locations=(model_location("module", "inputs", "drive.frequency"),),
        details={"input_id": "drive.frequency", "accepted": ["float", "quantity"]},
        occurrence_id="problem-1",
    )

    assert problem.schema_version == "scopecat.problem.v1"
    assert problem.location == ModelLocation(
        root="template",
        path=("inputs", "drive.frequency"),
    )
    assert problem.details["accepted"] == ("float", "quantity")
    with pytest.raises(TypeError, match="immutable"):
        cast("dict[str, object]", problem.details)["input_id"] = "changed"
    with pytest.raises(ValidationError, match="frozen"):
        problem.message = "changed"

    restored = Problem.model_validate_json(problem.model_dump_json())
    updated = problem.model_dump(mode="python")
    updated["details"] = {"nested": [1, 2]}
    copied = Problem.model_validate(updated)

    assert restored == problem
    assert copied.details["nested"] == (1, 2)
    assert restored.model_dump(mode="json")["details"] == {
        "input_id": "drive.frequency",
        "accepted": ["float", "quantity"],
    }


def test_location_union_preserves_domain_specific_coordinates() -> None:
    problem = blocking_problem(
        "importing.invalid_cell",
        "cell is invalid",
        category=ProblemCategory.INVALID_INPUT,
        phase=ProblemPhase.IMPORTING,
        location=ExternalLocation(
            uri="config.xlsx",
            sheet="Parameters",
            row=2,
            column=3,
            path=("value",),
        ),
        related_locations=(StorageLocation(ref="imports/config.xlsx"),),
    )

    restored = Problem.model_validate(problem.model_dump(mode="json"))

    assert isinstance(restored.location, ExternalLocation)
    assert restored.location.row == 2
    assert isinstance(restored.related_locations[0], StorageLocation)
    with pytest.raises(ValidationError, match="positive"):
        ExternalLocation(uri="config.xlsx", row=0)


def test_model_location_rejects_delimiter_packed_roots() -> None:
    with pytest.raises(ValidationError, match="path delimiters"):
        ModelLocation(root="template.inputs")


def test_problem_failure_requires_nonempty_blocking_problems() -> None:
    advisory = Problem(
        code="authoring.deprecated_shape",
        impact=ProblemImpact.ADVISORY,
        category=ProblemCategory.INVALID_INPUT,
        phase=ProblemPhase.DEFINITION,
        message="shape is accepted but discouraged",
    )
    blocking = blocking_problem(
        "authoring.invalid_shape",
        "shape is invalid",
        category=ProblemCategory.INVALID_INPUT,
        phase=ProblemPhase.DEFINITION,
    )

    with pytest.raises(ValueError, match="at least one problem"):
        ProblemFailure(())
    with pytest.raises(ValueError, match="blocking problem"):
        CheckFailed((advisory,))

    error = Conflict((advisory, blocking))

    assert error.problems == (advisory, blocking)
    assert str(error) == (
        "authoring.deprecated_shape: shape is accepted but discouraged; "
        "authoring.invalid_shape: shape is invalid"
    )


def test_measurement_transform_execution_has_its_own_operation_failure_type() -> None:
    problem = blocking_problem(
        "measurement_transform_host_kernel_failed",
        "host measurement transform failed",
        category=ProblemCategory.EXTERNAL_FAILURE,
        phase=ProblemPhase.EXECUTION,
    )

    error = MeasurementTransformExecutionError((problem,))

    assert isinstance(error, OperationFailure)
    assert not isinstance(error, ProviderContractError)
    assert error.problems == (problem,)
