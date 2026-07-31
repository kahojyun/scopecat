"""Materialize the bound symbolic point space for physical planning."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast

from scopecat.compiler.bind import BoundPlan
from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.entity_resolution import (
    EntityResolutionError,
    resolve_entity,
)
from scopecat.compiler.environment import ConfigEnvironment
from scopecat.compiler.relations.context import EvalContext, ParameterRelationData
from scopecat.compiler.relations.evaluation import (
    evaluate_scalar,
    evaluate_table_value,
)
from scopecat.compiler.semantic.value_expressions import (
    CompilerValue,
    ScalarValueExpr,
)
from scopecat.compiler.typed.parameter_overlays import resolve_point_parameters
from scopecat.compiler.typed.point_domain import (
    MaterializedPoint,
    MaterializedPointDomain,
    PointDomainEvaluationError,
    materialize_point_domain,
)
from scopecat.compiler.typed.program import (
    TypedDomainExecution,
    bound_domain_executions,
)
from scopecat.graph.relations.model import Row
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    model_location,
)
from scopecat.kernel.value_validation import ValueValidationError, coerce_literal


@dataclass(frozen=True, slots=True)
class MaterializedBoundPoints:
    """One bound plan with eagerly materialized points and parameter bindings."""

    bound_plan: BoundPlan
    point_domain: MaterializedPointDomain
    point_parameters: tuple[ParameterRelationData, ...]

    def __post_init__(self) -> None:
        if len(self.point_parameters) != len(self.point_domain.points):
            msg = "materialized points and parameter bindings must have equal length"
            raise ValueError(msg)

    def bind_domain_inputs(
        self,
        execution_id: str,
        input_kind: Literal["program", "compiler"],
        input_ids: Sequence[str],
        ordinals: Sequence[int],
    ) -> tuple[tuple[str, tuple[object, ...]], ...]:
        """Evaluate selected domain inputs for selected logical ordinals."""

        selected_input_ids = tuple(input_ids)
        selected = tuple(ordinals)
        entries = {
            point.logical_ordinal: (point, parameters)
            for point, parameters in zip(
                self.point_domain.points,
                self.point_parameters,
                strict=True,
            )
        }
        if any(ordinal not in entries for ordinal in selected):
            raise ValueError("point selection contains an unknown ordinal")
        execution = next(
            item
            for item in bound_domain_executions(self.bound_plan.bindings)
            if item.id == execution_id
        )
        available_inputs = (
            execution.inputs if input_kind == "program" else execution.compiler_inputs
        )
        known_input_ids = tuple(available_inputs)
        selected_input_set = set(selected_input_ids)
        if not selected_input_ids:
            return ()
        if selected_input_ids != tuple(
            input_id for input_id in known_input_ids if input_id in selected_input_set
        ):
            raise ValueError(
                "domain input binding must select known inputs in typed order"
            )
        problems: list[Problem] = []
        columns: dict[str, list[object]] = {
            input_id: [] for input_id in selected_input_ids
        }
        for ordinal in selected:
            point, parameters = entries[ordinal]
            input_values = _domain_inputs(
                execution,
                input_kind,
                point,
                selected_input_ids,
                parameters=parameters,
                problems=problems,
            )
            if input_values is not None:
                for input_id, value in input_values:
                    columns[input_id].append(value)
        if bool(problems):
            raise CheckFailed(problems)
        return tuple(
            (input_id, tuple(columns[input_id])) for input_id in selected_input_ids
        )


def materialize_bound_points(bound: BoundPlan) -> MaterializedBoundPoints:
    """Eagerly close the bound point space before target compilation."""

    point_domain = _materialize_bound_point_domain(bound)
    point_parameters = tuple(
        resolve_point_parameters(
            bound.environment.parameters,
            bound.bindings.parameter_overlays,
            point_row=point.row,
        )
        for point in point_domain.points
    )
    return MaterializedBoundPoints(
        bound_plan=bound,
        point_domain=point_domain,
        point_parameters=point_parameters,
    )


def _materialize_bound_point_domain(
    bound: BoundPlan,
) -> MaterializedPointDomain:
    problems: list[Problem] = []
    entity_columns = bound.point_domain.entity_columns
    try:
        point_domain = materialize_point_domain(
            bound.point_domain,
            bound.environment.parameters,
            row_normalizer=lambda row: _normalize_point_domain_row(
                row,
                entity_columns=entity_columns,
                environment=bound.environment,
                problems=problems,
            ),
        )
    except PointDomainEvaluationError as error:
        problems.append(
            compiler_problem(
                "experiment_points_evaluation_failed",
                f"experiment point domain failed: {error.error}",
                model_location("point_domain", *error.path),
                phase=ProblemPhase.PLANNING,
            )
        )
        raise CheckFailed(problems) from error
    except ValueValidationError as error:
        problems.append(
            compiler_problem(
                "module_point_value_type_mismatch",
                str(error),
                model_location("points"),
                phase=ProblemPhase.PLANNING,
            )
        )
        raise CheckFailed(problems) from error
    if bool(problems):
        raise CheckFailed(problems)
    return point_domain


def _domain_inputs(
    execution: TypedDomainExecution,
    input_kind: Literal["program", "compiler"],
    point: MaterializedPoint,
    input_ids: tuple[str, ...],
    *,
    parameters: ParameterRelationData,
    problems: list[Problem],
) -> tuple[tuple[str, object], ...] | None:
    input_values: list[tuple[str, object]] = []
    failed = False
    for input_name in input_ids:
        success, value = _materialize_domain_execution_input(
            execution,
            input_kind=input_kind,
            input_name=input_name,
            point=point,
            parameters=parameters,
            problems=problems,
        )
        if not success:
            failed = True
            continue
        input_values.append((input_name, value))
    if failed:
        return None
    return tuple(input_values)


def _materialize_domain_execution_input(
    execution: TypedDomainExecution,
    *,
    input_kind: Literal["program", "compiler"],
    input_name: str,
    point: MaterializedPoint,
    parameters: ParameterRelationData,
    problems: list[Problem],
) -> tuple[bool, object]:
    """Evaluate one selected domain input at one logical point."""

    context = EvalContext(params=parameters, point_row=point.row)
    input_spec = (
        execution.inputs[input_name]
        if input_kind == "program"
        else execution.compiler_inputs[input_name]
    )
    try:
        evaluated = _evaluate_domain_input(
            input_spec,
            context=context,
        )
        value = coerce_literal(
            input_spec.value_type,
            evaluated,
            path=(
                "domain_executions",
                execution.id,
                "points",
                point.logical_ordinal,
                f"{input_kind}_inputs",
                input_name,
            ),
        )
        return True, _unwrap_domain_input(value)
    except (ArithmeticError, KeyError, TypeError, ValueError) as error:
        problems.append(
            compiler_problem(
                "domain_execution_input_evaluation_failed",
                f"domain execution input {input_name!r} failed for point "
                f"{point.logical_ordinal}: {error}",
                model_location(
                    "domain_executions",
                    execution.id,
                    "points",
                    point.logical_ordinal,
                    "inputs",
                    input_name,
                ),
                phase=ProblemPhase.PLANNING,
            )
        )
        return False, None


def _evaluate_domain_input(
    input_spec: CompilerValue,
    *,
    context: EvalContext,
) -> object:
    if isinstance(input_spec, ScalarValueExpr):
        return evaluate_scalar(input_spec.plan, context)
    return evaluate_table_value(input_spec.source, input_spec.value_type, context)


def _unwrap_domain_input(value: object) -> object:
    if isinstance(value, PayloadValue):
        return value.payload
    if isinstance(value, list):
        return [_unwrap_domain_input(item) for item in cast("list[object]", value)]
    if isinstance(value, tuple):
        selected = cast("tuple[object, ...]", value)
        return tuple(_unwrap_domain_input(item) for item in selected)
    if isinstance(value, Mapping):
        return {
            name: _unwrap_domain_input(item)
            for name, item in cast("Mapping[object, object]", value).items()
        }
    return value


def _normalize_point_domain_row(
    row: Row,
    *,
    entity_columns: Sequence[str],
    environment: ConfigEnvironment,
    problems: list[Problem],
) -> Row:
    selected = dict(row)
    for column_id in entity_columns:
        value = selected.get(column_id)
        if value is None:
            continue
        entity = _resolve_entity(value, environment, problems)
        if entity is not None:
            selected[column_id] = entity
    return selected


def _resolve_entity(
    value: object,
    environment: ConfigEnvironment,
    problems: list[Problem],
) -> EntityRef | None:
    selected = value if isinstance(value, EntityRef) else str(value)
    try:
        return resolve_entity(environment.config.topology, selected)
    except EntityResolutionError as error:
        issue = error.issue
    if issue.code == "unknown_entity":
        problems.append(
            compiler_problem(
                "unknown_authoring_entity",
                f"experiment references unknown entity {issue.entity_id}",
                model_location("entity", issue.entity_id),
                phase=ProblemPhase.PLANNING,
            )
        )
        return None
    problems.append(
        compiler_problem(
            "authoring_entity_kind_mismatch",
            f"entity {issue.entity_id} has kind {issue.actual_kind}, "
            f"not {issue.requested_kind}",
            model_location("entity", issue.entity_id),
            phase=ProblemPhase.PLANNING,
        )
    )
    return None
