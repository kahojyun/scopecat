from __future__ import annotations

from typing import cast

import pytest
from pydantic import ValidationError

from scopecat.kernel.errors import (
    CheckFailed,
    Conflict,
    MeasurementPostprocessorExecutionError,
    OperationFailure,
    ProblemFailure,
    ProviderContractError,
)
from scopecat.kernel.problems import (
    ExternalLocation,
    ModelLocation,
    Problem,
    ProblemPhase,
    StorageLocation,
    model_location,
    problem,
)


def test_problem_is_deeply_frozen_and_json_round_trips() -> None:
    selected = problem(
        "authoring.missing_input",
        "required input is missing",
        phase=ProblemPhase.AUTHORING,
        location=model_location("template", "inputs", "test.drive_frequency/v1"),
        related_locations=(
            model_location("module", "inputs", "test.drive_frequency/v1"),
        ),
        details={
            "input_id": "test.drive_frequency/v1",
            "accepted": ["float", "quantity"],
        },
        occurrence_id="problem-1",
    )

    assert selected.location == ModelLocation(
        root="template",
        path=("inputs", "test.drive_frequency/v1"),
    )
    assert selected.details["accepted"] == ("float", "quantity")
    with pytest.raises(TypeError, match="immutable"):
        cast("dict[str, object]", selected.details)["input_id"] = "changed"
    with pytest.raises(ValidationError, match="frozen"):
        selected.message = "changed"

    restored = Problem.model_validate_json(selected.model_dump_json())
    updated = selected.model_dump(mode="python")
    updated["details"] = {"nested": [1, 2]}
    copied = Problem.model_validate(updated)

    assert restored == selected
    assert copied.details["nested"] == (1, 2)
    assert restored.model_dump(mode="json")["details"] == {
        "input_id": "test.drive_frequency/v1",
        "accepted": ["float", "quantity"],
    }


def test_location_union_preserves_domain_specific_coordinates() -> None:
    selected = problem(
        "importing.invalid_cell",
        "cell is invalid",
        phase=ProblemPhase.CONFIGURATION,
        location=ExternalLocation(
            uri="config.xlsx",
            sheet="Parameters",
            row=2,
            column=3,
            path=("value",),
        ),
        related_locations=(StorageLocation(ref="imports/config.xlsx"),),
    )

    restored = Problem.model_validate(selected.model_dump(mode="json"))

    assert isinstance(restored.location, ExternalLocation)
    assert restored.location.row == 2
    assert isinstance(restored.related_locations[0], StorageLocation)
    with pytest.raises(ValidationError, match="positive"):
        ExternalLocation(uri="config.xlsx", row=0)


def test_model_location_rejects_delimiter_packed_roots() -> None:
    with pytest.raises(ValidationError, match="path delimiters"):
        ModelLocation(root="template.inputs")


def test_problem_failure_requires_nonempty_problems() -> None:
    first = Problem(
        code="authoring.deprecated_shape",
        phase=ProblemPhase.DEFINITION,
        message="shape is accepted but discouraged",
    )
    second = problem(
        "authoring.invalid_shape",
        "shape is invalid",
        phase=ProblemPhase.DEFINITION,
    )

    with pytest.raises(ValueError, match="at least one problem"):
        ProblemFailure(())
    assert CheckFailed((first,)).problems == (first,)

    error = Conflict((first, second))

    assert error.problems == (first, second)
    assert str(error) == (
        "authoring.deprecated_shape: shape is accepted but discouraged; "
        "authoring.invalid_shape: shape is invalid"
    )


def test_postprocessor_execution_has_its_own_operation_failure_type() -> None:
    selected = problem(
        "measurement_postprocessor_kernel_failed",
        "measurement postprocessor failed",
        phase=ProblemPhase.EXECUTION,
    )

    error = MeasurementPostprocessorExecutionError((selected,))

    assert isinstance(error, OperationFailure)
    assert not isinstance(error, ProviderContractError)
    assert error.problems == (selected,)
