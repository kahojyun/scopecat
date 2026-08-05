"""Config-free verification for experiment definitions and invocations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.kernel.value_type_compatibility import is_assignable
from scopecat.kernel.value_types import ValueType
from scopecat.kernel.value_validation import ValueValidationError, validate_literal
from scopecat.program.operations import ModuleInputPort
from scopecat.program.scans import (
    AroundScanSource,
    AxisSpec,
    PointPlan,
    parameter_overlay_cell,
)
from scopecat.program.value_refs import (
    ValueRef,
    internal_value_ref_input_id,
)


class ExperimentInputDefinition(Protocol):
    """Normalized experiment input fields needed when binding an invocation."""

    @property
    def id(self) -> str: ...

    @property
    def value_type(self) -> ValueType | None: ...


def _definition_problem(
    code: str,
    message: str,
    root: str,
    *,
    path: Sequence[str | int] = (),
) -> Problem:
    return problem(
        code=code,
        phase=ProblemPhase.AUTHORING,
        message=message,
        location=model_location(root, *path),
    )


def validate_experiment_definition(
    *,
    input_ports: Sequence[ModuleInputPort],
    defaults: Mapping[str, object],
    default_point_plan: PointPlan,
) -> dict[str, ValueType]:
    """Validate one closed experiment definition without consulting config."""

    problems: list[Problem] = []
    input_types, input_type_problems = _definition_input_types(
        input_ports,
        default_point_plan,
    )
    problems.extend(input_type_problems)
    problems.extend(
        _literal_type_problems(
            defaults,
            input_types,
            location=model_location("definition", "inputs"),
            path_suffix=("default",),
        )
    )
    _raise_problems(problems, phase=ProblemPhase.DEFINITION)
    return input_types


def validate_experiment_inputs(
    *,
    definitions: Sequence[ExperimentInputDefinition],
    inputs: Mapping[str, object],
) -> None:
    """Reject known invocation input errors while leaving missing values open."""

    allowed = {definition.id for definition in definitions}
    input_types = {
        definition.id: definition.value_type
        for definition in definitions
        if definition.value_type is not None
    }
    unknown = sorted(set(inputs) - allowed)
    problems: list[Problem] = []
    if unknown:
        problems.append(
            _definition_problem(
                "experiment_unknown_input",
                "experiment received unknown input: " + ", ".join(unknown),
                "experiment",
                path=("inputs",),
            )
        )
    problems.extend(
        _literal_type_problems(
            inputs,
            input_types,
            location=model_location("inputs"),
        )
    )
    _raise_problems(problems)


def _definition_input_types(
    input_ports: Sequence[ModuleInputPort],
    default_point_plan: PointPlan,
) -> tuple[dict[str, ValueType], list[Problem]]:
    selected = {port.id: port.value_type for port in input_ports}
    problems: list[Problem] = []

    for axis in default_point_plan.domain.axes:
        for input_id, value_type in _direct_scan_input_types(axis):
            existing = selected.get(input_id)
            if existing is None or is_assignable(value_type, existing):
                selected[input_id] = value_type
            elif not is_assignable(existing, value_type):
                problems.append(
                    _definition_problem(
                        "module_input_type_conflict",
                        f"experiment input {input_id} has incompatible value types",
                        "inputs",
                        path=(input_id,),
                    )
                )
    return selected, problems


def _direct_scan_input_types(
    axis: AxisSpec,
) -> tuple[tuple[str, ValueType], ...]:
    selected: list[tuple[str, ValueType]] = []
    values: tuple[object, ...] = ()
    if isinstance(axis.source, AroundScanSource):
        values = (axis.source.center,)
    if axis.overlay is not None:
        _lookup, key = parameter_overlay_cell(axis)
        values = (*values, *(value for _name, value in key))
    for value in values:
        if not isinstance(value, ValueRef):
            continue
        input_id = internal_value_ref_input_id(value)
        if input_id is not None:
            selected.append((input_id, value.value_type))
    return tuple(selected)


def _literal_type_problems(
    values: Mapping[str, object],
    input_types: Mapping[str, ValueType],
    *,
    location: ModelLocation,
    path_suffix: tuple[str | int, ...] = (),
) -> list[Problem]:
    problems: list[Problem] = []
    for input_id in sorted(set(values) & set(input_types)):
        value_location = model_location(
            location.root,
            *location.path,
            input_id,
            *path_suffix,
        )
        try:
            validate_literal(
                input_types[input_id],
                values[input_id],
                path=(value_location.root, *value_location.path),
            )
        except ValueValidationError as error:
            problems.append(
                _definition_problem(
                    "module_input_type_mismatch",
                    str(error),
                    value_location.root,
                    path=value_location.path,
                )
            )
    return problems


def _raise_problems(
    problems: list[Problem],
    *,
    phase: ProblemPhase = ProblemPhase.AUTHORING,
) -> None:
    if problems:
        raise CheckFailed(
            [problem.model_copy(update={"phase": phase}) for problem in problems]
        )
