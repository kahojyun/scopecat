from __future__ import annotations

from dataclasses import replace

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from scopecat.automation import (
    CalibrationDependencyEvidence,
    CalibrationObservation,
    CalibrationRegistry,
    CalibrationTargetRef,
    procedure,
)
from scopecat.automation.calibration_definition import CalibrationDefinition


class _Inputs(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: int


class _Intent(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: int


@procedure(id="tests.calibration-definition.procedure", version="1", intent=_Intent)
def _procedure_one(_context: object, _intent: _Intent) -> None:
    pass


@procedure(id="tests.calibration-definition.procedure", version="2", intent=_Intent)
def _procedure_two(_context: object, _intent: _Intent) -> None:
    pass


def _select(_context: object) -> tuple[CalibrationTargetRef, ...]:
    return (CalibrationTargetRef(kind="qubit", id="q0"),)


def _observe(
    _context: object,
    _target: CalibrationTargetRef,
) -> CalibrationObservation[_Inputs]:
    return CalibrationObservation(inputs=_Inputs(value=1))


def _build(
    _context: object,
    _target: CalibrationTargetRef,
    inputs: _Inputs,
    _dependencies: tuple[CalibrationDependencyEvidence, ...],
) -> _Intent:
    return _Intent(value=inputs.value)


_DEFINITION = CalibrationDefinition(
    id="tests.calibration-definition",
    version="1",
    input_type=_Inputs,
    procedure=_procedure_one,
    fanout_scope="device-a",
    max_in_flight=2,
    _select_targets=_select,
    _observe=_observe,
    _build_intent=_build,
)


def test_definition_fingerprint_covers_procedure_scope_and_capacity() -> None:
    changed_procedure = replace(_DEFINITION, procedure=_procedure_two)
    changed_scope = replace(_DEFINITION, fanout_scope="device-b")
    changed_capacity = replace(_DEFINITION, max_in_flight=3)
    changed_success_policy = replace(
        _DEFINITION,
        success_policy="published_result",
    )

    assert (
        len(
            {
                _DEFINITION.fingerprint,
                changed_procedure.fingerprint,
                changed_scope.fingerprint,
                changed_capacity.fingerprint,
                changed_success_policy.fingerprint,
            }
        )
        == 5
    )
    assert _DEFINITION.ref.success_policy == "procedure_success"
    assert changed_success_policy.ref.success_policy == "published_result"


def test_registry_allows_only_one_active_version_per_logical_id() -> None:
    changed_version = replace(_DEFINITION, version="2")

    with pytest.raises(ValueError, match="more than one active version"):
        CalibrationRegistry((_DEFINITION, changed_version))


def test_selector_is_canonical_and_bounded() -> None:
    selected = _DEFINITION.select_targets(object())

    assert selected == (CalibrationTargetRef(kind="qubit", id="q0"),)


def test_project_observation_rejects_unstable_forced_retries() -> None:
    with pytest.raises(ValidationError, match="forced_reason"):
        CalibrationObservation[_Inputs].model_validate(
            {
                "inputs": _Inputs(value=1),
                "forced_reason": "retry every cycle",
            }
        )
