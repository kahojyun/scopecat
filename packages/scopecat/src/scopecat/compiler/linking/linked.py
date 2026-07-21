"""Config-linked symbolic programs before any target materialization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

from scopecat.compiler.diagnostics import CompilerProblemError, compiler_problem
from scopecat.compiler.entity_resolution import (
    EntityResolutionError,
    resolve_entity,
)
from scopecat.compiler.frontend.environment import ValidatedConfigEnvironment
from scopecat.compiler.relations.evaluation import (
    EvalContext,
    ParameterRelationData,
    evaluate_relation,
    evaluate_scalar,
    evaluate_series,
    normalize_relation_parameter_import,
)
from scopecat.compiler.relations.model import (
    RelationExpr,
    Row,
    ScalarExpr,
    SeriesExpr,
)
from scopecat.compiler.relations.verification import (
    PlanImportNamespace,
    VerifiedRelationPlan,
)
from scopecat.compiler.semantic.value_expressions import (
    ScalarValueExpr,
    SeriesValueExpr,
)
from scopecat.compiler.typed.parameter_overlays import resolve_point_parameters
from scopecat.compiler.typed.point_domain import (
    MaterializedPoint,
    MaterializedPointDomain,
    PointDomainEvaluationError,
    VerifiedPointDomain,
    materialize_point_domain,
    materialize_point_domain_ordinals,
)
from scopecat.compiler.typed.program import (
    CoreProgram,
    TypedDomainExecution,
    ValueInput,
    core_domain_executions,
)
from scopecat.compiler.typed.specialization import specialize_core_program
from scopecat.compiler.typed.verification import (
    ProgramRelationConsumer,
    VerifiedCoreProgram,
    seal_typed_program,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    has_blocking_problems,
    model_location,
)
from scopecat.kernel.value_validation import ValueValidationError, coerce_literal
from scopecat.records.entity import EntityRef


@dataclass(frozen=True, slots=True)
class LinkedPlan:
    """A successful config link retaining the complete symbolic point domain.

    The plan binds a backend-neutral, sealed compiler program to one accepted
    configuration environment. Both are trusted transient compiler artifacts;
    the plan owns no materialized points or target artifact.
    """

    verified_program: VerifiedCoreProgram
    environment: ValidatedConfigEnvironment

    @property
    def program(self) -> CoreProgram:
        """Return the sealed compiler program bound to this plan."""

        return self.verified_program.program

    @property
    def point_domain(self) -> VerifiedPointDomain:
        return self.verified_program.point_domain


@dataclass(frozen=True, slots=True)
class MaterializedLinkedPoints:
    """One linked plan with canonical points and parameter bindings.

    Domain inputs are deliberately absent. Selected compilers decide which
    residual columns must be evaluated for each compiled job.
    """

    linked_plan: LinkedPlan
    point_domain: MaterializedPointDomain
    point_parameters: tuple[ParameterRelationData, ...]

    def __post_init__(self) -> None:
        if len(self.point_parameters) != len(self.point_domain.points):
            msg = "materialized points and parameter bindings must have equal length"
            raise ValueError(msg)


@dataclass(slots=True)
class LinkedPointMaterializer:
    """Shared closure of a symbolic point space in bounded ordinal blocks."""

    linked: LinkedPlan
    block_size: int = 100_000
    _point_domain: MaterializedPointDomain | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _selected_points: dict[int, MaterializedPoint] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if type(self.block_size) is not int or self.block_size <= 0:
            raise ValueError("point materialization block size must be positive")

    def materialize_point_domain(self) -> MaterializedPointDomain:
        """Materialize canonical point rows without retaining point parameters."""

        return self._materialize_point_domain()

    def bind_domain_inputs(
        self,
        execution_id: str,
        input_ids: Sequence[str],
        ordinals: Sequence[int],
        *,
        max_points: int,
        coverage: MaterializedLinkedPoints | None = None,
    ) -> tuple[tuple[str, tuple[object, ...]], ...]:
        """Evaluate selected domain inputs for selected logical ordinals."""

        selected_input_ids = tuple(input_ids)
        selected = tuple(ordinals)
        if type(max_points) is not int or max_points <= 0:
            raise ValueError("domain input binding budget must be positive")
        if len(selected) > max_points:
            raise ValueError("domain input binding exceeds the requested budget")
        point_count = self.linked.point_domain.cardinality
        if any(ordinal < 0 or ordinal >= point_count for ordinal in selected):
            raise ValueError("domain input binding selects an unknown ordinal")
        execution = next(
            item
            for item in core_domain_executions(self.linked.program)
            if item.id == execution_id
        )
        known_input_ids = tuple(execution.inputs)
        selected_input_set = set(selected_input_ids)
        if not selected_input_ids:
            raise ValueError("domain input binding requires at least one input")
        if selected_input_ids != tuple(
            input_id for input_id in known_input_ids if input_id in selected_input_set
        ):
            raise ValueError(
                "domain input binding must select known inputs in typed order"
            )
        selected_points = self._materialize_selected_points(
            selected,
            max_points=max_points,
        )
        coverage_parameters = (
            {}
            if coverage is None
            else {
                point.logical_ordinal: parameters
                for point, parameters in zip(
                    coverage.point_domain.points,
                    coverage.point_parameters,
                    strict=True,
                )
            }
        )
        if coverage is not None and coverage.linked_plan is not self.linked:
            raise ValueError("domain input coverage belongs to a different plan")
        if coverage is not None and any(
            point.logical_ordinal not in coverage_parameters
            for point in selected_points
        ):
            raise ValueError("domain input ordinals fall outside the bound coverage")
        problems: list[Problem] = []
        columns: dict[str, list[object]] = {
            input_id: [] for input_id in selected_input_ids
        }
        for point in selected_points:
            input_values = self._domain_inputs(
                execution,
                point,
                selected_input_ids,
                parameters=coverage_parameters.get(point.logical_ordinal),
                problems=problems,
            )
            if input_values is not None:
                for input_id, value in input_values:
                    columns[input_id].append(value)
        if has_blocking_problems(problems):
            raise CheckFailed(problems)
        return tuple(
            (input_id, tuple(columns[input_id])) for input_id in selected_input_ids
        )

    def materialize(self) -> MaterializedLinkedPoints:
        """Close canonical points by bounded blocks, without domain inputs."""

        cardinality = self.linked.point_domain.cardinality
        if cardinality > self.block_size:
            points = tuple(
                point
                for start in range(0, cardinality, self.block_size)
                for point in self._materialize_selected_points(
                    tuple(range(start, min(start + self.block_size, cardinality))),
                    max_points=self.block_size,
                )
            )
            point_domain = MaterializedPointDomain(
                self.linked.point_domain.id,
                points,
            )
            self._point_domain = point_domain
        else:
            point_domain = self._materialize_point_domain()
        problems: list[Problem] = []
        point_parameters = tuple(
            self._point_parameter(point, problems=problems)
            for point in point_domain.points
        )
        if has_blocking_problems(problems):
            raise CheckFailed(problems)
        return MaterializedLinkedPoints(
            self.linked,
            point_domain,
            point_parameters,
        )

    def materialize_ordinals(
        self,
        ordinals: Sequence[int],
        *,
        max_points: int,
    ) -> MaterializedLinkedPoints:
        """Materialize one bounded logical coverage without closing other points."""

        selected_ordinals = tuple(ordinals)
        if len(selected_ordinals) > max_points:
            raise ValueError("point materialization exceeds the requested budget")
        points = self._materialize_selected_points(
            selected_ordinals,
            max_points=max_points,
        )
        problems: list[Problem] = []
        variation_support = self.linked.verified_program.variation_analysis.parameters
        point_by_ordinal = {point.logical_ordinal: point for point in points}
        parameter_by_ordinal: dict[int, ParameterRelationData] = {}
        for coverage in self.linked.verified_program.iteration_layout.partition(
            variation_support.point_columns,
            selected_ordinals,
            rows={ordinal: point.row for ordinal, point in point_by_ordinal.items()},
        ):
            parameters = self._point_parameter(
                point_by_ordinal[coverage[0]],
                problems=problems,
            )
            for ordinal in coverage:
                parameter_by_ordinal[ordinal] = parameters
        if has_blocking_problems(problems):
            raise CheckFailed(problems)
        return MaterializedLinkedPoints(
            self.linked,
            MaterializedPointDomain(
                self.linked.point_domain.id,
                points,
            ),
            tuple(parameter_by_ordinal[point.logical_ordinal] for point in points),
        )

    def _materialize_point_domain(self) -> MaterializedPointDomain:
        if self._point_domain is not None:
            return self._point_domain
        problems: list[Problem] = []
        entity_columns = self.linked.point_domain.entity_columns
        try:
            point_domain = materialize_point_domain(
                self.linked.point_domain,
                self.linked.environment.parameters,
                row_normalizer=lambda row: _normalize_point_domain_row(
                    row,
                    entity_columns=entity_columns,
                    environment=self.linked.environment,
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
        if has_blocking_problems(problems):
            raise CheckFailed(problems)
        if self._selected_points:
            points = list(point_domain.points)
            for ordinal, selected in self._selected_points.items():
                if selected.row != points[ordinal].row:
                    raise AssertionError(
                        "selective and complete point materialization must agree"
                    )
                points[ordinal] = selected
            point_domain = MaterializedPointDomain(
                point_domain.id,
                tuple(points),
            )
        self._point_domain = point_domain
        return point_domain

    def _materialize_selected_points(
        self,
        ordinals: tuple[int, ...],
        *,
        max_points: int,
    ) -> tuple[MaterializedPoint, ...]:
        if self._point_domain is not None:
            return tuple(self._point_domain.points[ordinal] for ordinal in ordinals)
        missing = tuple(
            ordinal
            for ordinal in dict.fromkeys(ordinals)
            if ordinal not in self._selected_points
        )
        if missing:
            problems: list[Problem] = []
            entity_columns = self.linked.point_domain.entity_columns
            try:
                points = materialize_point_domain_ordinals(
                    self.linked.point_domain,
                    self.linked.environment.parameters,
                    missing,
                    max_points=max_points,
                    row_normalizer=lambda row: _normalize_point_domain_row(
                        row,
                        entity_columns=entity_columns,
                        environment=self.linked.environment,
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
            if has_blocking_problems(problems):
                raise CheckFailed(problems)
            self._selected_points.update(
                (point.logical_ordinal, point) for point in points
            )
        return tuple(self._selected_points[ordinal] for ordinal in ordinals)

    def _point_parameter(
        self,
        point: MaterializedPoint,
        *,
        problems: list[Problem],
    ) -> ParameterRelationData:
        try:
            return resolve_point_parameters(
                self.linked.environment.parameters,
                self.linked.program.parameter_overlays,
                point_row=point.row,
                relation_plan=self.linked.verified_program.relation_plan,
            )
        except CompilerProblemError as error:
            problems.append(error.problem)
            return ParameterRelationData()

    def _domain_inputs(
        self,
        execution: TypedDomainExecution,
        point: MaterializedPoint,
        input_ids: tuple[str, ...],
        *,
        parameters: ParameterRelationData | None = None,
        problems: list[Problem],
    ) -> tuple[tuple[str, object], ...] | None:
        if parameters is None:
            parameters = self._point_parameter(point, problems=problems)
        if has_blocking_problems(problems):
            return None
        input_values: list[tuple[str, object]] = []
        failed = False
        for input_name in input_ids:
            success, value = _materialize_domain_execution_input(
                execution,
                input_name=input_name,
                point=point,
                verified_program=self.linked.verified_program,
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
    input_name: str,
    point: MaterializedPoint,
    verified_program: VerifiedCoreProgram,
    parameters: ParameterRelationData,
    problems: list[Problem],
) -> tuple[bool, object]:
    """Evaluate one selected domain input at one logical point."""

    context = EvalContext(params=parameters, point_row=point.row)
    input_spec = execution.inputs[input_name]
    try:
        evaluated = _evaluate_domain_input(
            input_spec,
            verified_program=verified_program,
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
                "inputs",
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
    input_spec: ValueInput,
    *,
    verified_program: VerifiedCoreProgram,
    context: EvalContext,
) -> object:
    value = input_spec.value
    verified_plan = verified_program.relation_plan(input_spec.relation_use_id)
    if isinstance(value, ScalarValueExpr):
        return evaluate_scalar(
            cast("VerifiedRelationPlan[ScalarExpr]", verified_plan),
            context,
        )
    if isinstance(value, SeriesValueExpr):
        return evaluate_series(
            cast("VerifiedRelationPlan[SeriesExpr]", verified_plan),
            context,
        )
    return evaluate_relation(
        cast("VerifiedRelationPlan[RelationExpr]", verified_plan),
        context,
    )


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


def link_verified_program(
    verified_program: VerifiedCoreProgram,
    environment: ValidatedConfigEnvironment,
) -> LinkedPlan:
    """Bind config contracts to an already verified transient program."""

    problems = list(environment.problems)
    if environment.valid:
        problems.extend(
            _relation_import_problems(
                verified_program,
                environment.parameters,
            )
        )
    if has_blocking_problems(problems):
        raise CheckFailed(problems)
    return LinkedPlan(
        verified_program,
        environment,
    )


def specialize_linked_program(linked: LinkedPlan) -> LinkedPlan:
    """Partially evaluate one accepted config link before system lowering."""

    return LinkedPlan(
        seal_typed_program(
            specialize_core_program(
                linked.program,
                parameters=linked.environment.parameters,
            ),
            phase=ProblemPhase.PLANNING,
        ),
        linked.environment,
    )


def _relation_import_problems(
    verified_program: VerifiedCoreProgram,
    parameters: ParameterRelationData,
) -> tuple[Problem, ...]:
    problems: list[Problem] = []
    for consumer in verified_program.relation_consumers:
        plan = consumer.plan
        for imported in plan.imports:
            if imported.namespace is PlanImportNamespace.INPUT:
                problems.append(_unresolved_input_problem(consumer, imported.id))
                continue
            try:
                normalize_relation_parameter_import(
                    plan,
                    imported,
                    parameters,
                )
            except ValueValidationError as error:
                problems.append(_parameter_import_problem(consumer, error))
    return tuple(problems)


def _unresolved_input_problem(
    consumer: ProgramRelationConsumer,
    input_id: str,
) -> Problem:
    return compiler_problem(
        "linked_input_unresolved",
        f"linked relation still depends on unresolved input {input_id!r}",
        model_location(
            consumer.location.root,
            *consumer.location.path,
            "inputs",
            input_id,
        ),
        phase=ProblemPhase.PLANNING,
        category=ProblemCategory.NOT_FOUND,
        details={
            "consumer_kind": consumer.kind.value,
            "input_id": input_id,
        },
    )


def _parameter_import_problem(
    consumer: ProgramRelationConsumer,
    error: ValueValidationError,
) -> Problem:
    missing = error.code == "unknown_parameter"
    parameter_id = (
        error.path[1]
        if len(error.path) > 1 and isinstance(error.path[1], str)
        else None
    )
    return compiler_problem(
        "linked_parameter_missing" if missing else "linked_parameter_contract_mismatch",
        (
            "accepted configuration cannot satisfy relation "
            f"parameter import: {error.reason}"
        ),
        model_location(
            consumer.location.root,
            *consumer.location.path,
            *error.path,
        ),
        phase=ProblemPhase.PLANNING,
        category=(
            ProblemCategory.NOT_FOUND if missing else ProblemCategory.INVALID_INPUT
        ),
        details={
            "consumer_kind": consumer.kind.value,
            **({"parameter_id": parameter_id} if parameter_id is not None else {}),
            "value_path": list(error.path),
        },
    )


def _normalize_point_domain_row(
    row: Row,
    *,
    entity_columns: Sequence[str],
    environment: ValidatedConfigEnvironment,
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
    environment: ValidatedConfigEnvironment,
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
                category=ProblemCategory.NOT_FOUND,
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
