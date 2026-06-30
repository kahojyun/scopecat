"""Recipe-based experiment assembly from structured authoring inputs."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from scopecat.authoring._bindings import (
    AssetBindingIntent,
    BindingIntent,
    ExperimentBindingIntent,
    ResourceRole,
    ResourceSelector,
    asset_binding,
    bind,
    requires,
    resolve_resource_roles,
    resource_role,
)
from scopecat.authoring._datasets import (
    DatasetColumn,
    DatasetIntent,
    PointDatasetIntent,
    ShotDatasetIntent,
    coordinate,
    observable,
    point_dataset,
    shot_dataset,
)
from scopecat.authoring._templates import (
    AroundSweep,
    ExperimentAuthoringContext,
    ExperimentDraft,
    ExperimentTemplate,
)
from scopecat.authoring._templates import (
    template as authoring_template,
)
from scopecat.authoring.expressions import (
    BindingSpec,
    ExperimentAsset,
    ExperimentVariable,
    Expression,
)
from scopecat.authoring.expressions import (
    asset_ref as asset_ref_expr,
)
from scopecat.authoring.expressions import (
    param as param_expr,
)
from scopecat.authoring.expressions import (
    var as var_expr,
)
from scopecat.experiments import (
    AcquisitionSpec,
    ExperimentSpec,
    ObservationSpec,
    StateSpec,
    set_state,
)
from scopecat.experiments import (
    acquire as build_acquisition_spec,
)
from scopecat.models.artifact import ArtifactRef
from scopecat.models.parameter import Quantity
from scopecat.models.provider import ProviderOptionDescription
from scopecat.relations import (
    CellValue,
    EvalContext,
    ParameterRelationData,
    RelationExpr,
    ScalarExpr,
    col,
    grid,
    literal_rows,
    param,
    range_values,
    values,
)
from scopecat.relations import (
    linspace as relation_linspace,
)

type VariableValue = ExperimentVariable | Expression
type VariableFactory = Callable[
    [ExperimentAuthoringContext, Mapping[str, object]], VariableValue
]


@dataclass(frozen=True)
class SweepAroundIntent:
    variable_id: str
    parameter_id: str
    default_span: Quantity | Expression
    default_points: int
    input_id: str | None = None

    def build(
        self,
        ctx: ExperimentAuthoringContext,
        inputs: Mapping[str, object],
    ) -> ExperimentVariable:
        sweep_input = inputs.get(self.input_id or self.variable_id)
        if sweep_input is not None and not isinstance(sweep_input, AroundSweep):
            ctx.raise_diagnostic(
                "recipe_sweep_input_invalid",
                f"{self.variable_id} sweep input must be AroundSweep",
                self.input_id or self.variable_id,
            )
        return ctx.around_sweep(
            sweep_input,
            parameter_id=self.parameter_id,
            default_span=_quantity_from_value(self.default_span),
            default_points=self.default_points,
        )


@dataclass(frozen=True)
class DerivedVariableIntent:
    variable_id: str
    expression: Expression

    def build(
        self,
        ctx: ExperimentAuthoringContext,
        inputs: Mapping[str, object],
    ) -> ExperimentVariable:
        del ctx, inputs
        return ExperimentVariable(kind="derived", expression=self.expression)


@dataclass(frozen=True)
class ExplicitVariableIntent:
    variable_id: str
    value: VariableValue | VariableFactory

    def build(
        self,
        ctx: ExperimentAuthoringContext,
        inputs: Mapping[str, object],
    ) -> ExperimentVariable:
        value = self.value(ctx, inputs) if callable(self.value) else self.value
        if isinstance(value, ExperimentVariable):
            return value
        return ExperimentVariable(kind="derived", expression=value)


VariableIntent = SweepAroundIntent | DerivedVariableIntent | ExplicitVariableIntent


@dataclass(frozen=True)
class AcquisitionIntent:
    kind: str = "measurement"
    shots: Expression | Quantity | float | None = None
    repetitions: Expression | Quantity | float | None = None
    record: Literal["point", "shot"] = "point"
    channels: tuple[str, ...] = ()

    def build(self, ctx: ExperimentAuthoringContext) -> AcquisitionSpec:
        shots = _static_positive_int(
            ctx, self.shots, default=1, path="acquisition.shots"
        )
        repetitions = _static_positive_int(
            ctx,
            self.repetitions,
            default=1,
            path="acquisition.repetitions",
        )
        return build_acquisition_spec(
            self.kind,
            shots=shots,
            repetitions=repetitions,
            record=self.record,
            channels=list(self.channels),
        )


AcquisitionSpecIntent = AcquisitionIntent | AcquisitionSpec


@dataclass(frozen=True)
class ExperimentRecipe:
    id: str
    experiment_id: str
    kind: str
    subject_inputs: tuple[str, ...] = ("subject",)
    resource_roles: tuple[ResourceRole, ...] = ()
    variables: tuple[VariableIntent, ...] = ()
    bindings: tuple[ExperimentBindingIntent, ...] = ()
    acquisition: AcquisitionSpecIntent = field(default_factory=AcquisitionIntent)
    dataset: DatasetIntent | None = None
    assets: tuple[ExperimentAsset, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __call__(self, **inputs: object) -> ExperimentDraft:
        return ExperimentDraft(build=self.build, inputs=dict(inputs))

    def template(
        self,
        *,
        id: str | None = None,  # noqa: A002
        inputs: tuple[ProviderOptionDescription, ...] = (),
        defaults: Mapping[str, object] | None = None,
        label: str | None = None,
        description: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> ExperimentTemplate:
        return authoring_template(
            id=id or self.id,
            build=self.build,
            inputs=inputs,
            defaults=defaults,
            label=label,
            description=description,
            metadata=metadata,
        )

    def build(
        self,
        ctx: ExperimentAuthoringContext,
        **inputs: object,
    ) -> ExperimentSpec:
        _resolve_subject_inputs(ctx, self.subject_inputs, inputs)
        resource_ids = resolve_resource_roles(ctx, self.resource_roles)
        variables = {
            intent.variable_id: intent.build(ctx, inputs) for intent in self.variables
        }
        bindings = [binding.build(ctx, resource_ids) for binding in self.bindings]
        acquisition = _build_acquisition(ctx, self.acquisition)
        acquisition = _with_dataset_observations(
            acquisition,
            self.dataset,
            ctx=ctx,
            variables=variables,
        )
        return ExperimentSpec(
            id=self.experiment_id,
            kind=self.kind,
            points=_points_relation(variables),
            state=_state_specs(bindings),
            acquire=acquisition,
            assets=[_artifact_ref(asset) for asset in self.assets],
            metadata=dict(self.metadata),
        )


def recipe(
    *,
    id: str,  # noqa: A002
    experiment_id: str,
    kind: str,
    subject_inputs: Sequence[str] = ("subject",),
    resources: Sequence[ResourceRole] = (),
    variables: Sequence[VariableIntent] = (),
    bindings: Sequence[ExperimentBindingIntent] = (),
    acquisition: AcquisitionSpecIntent | None = None,
    dataset: DatasetIntent | None = None,
    assets: Sequence[ExperimentAsset] = (),
    metadata: Mapping[str, Any] | None = None,
) -> ExperimentRecipe:
    return ExperimentRecipe(
        id=id,
        experiment_id=experiment_id,
        kind=kind,
        subject_inputs=tuple(subject_inputs),
        resource_roles=tuple(resources),
        variables=tuple(variables),
        bindings=tuple(bindings),
        acquisition=acquisition or AcquisitionIntent(),
        dataset=dataset,
        assets=tuple(assets),
        metadata=dict(metadata or {}),
    )


def sweep(
    parameter_id: str,
    *,
    default_span: Quantity | Expression,
    points: int,
    variable_id: str | None = None,
    input_id: str | None = "sweep",
) -> SweepAroundIntent:
    return SweepAroundIntent(
        variable_id=variable_id or parameter_id,
        parameter_id=parameter_id,
        default_span=default_span,
        default_points=points,
        input_id=input_id,
    )


def derive(variable_id: str, expression: Expression) -> DerivedVariableIntent:
    return DerivedVariableIntent(variable_id=variable_id, expression=expression)


def variable(
    variable_id: str,
    value: VariableValue | VariableFactory,
) -> ExplicitVariableIntent:
    return ExplicitVariableIntent(variable_id=variable_id, value=value)


def var_ref(variable_id: str) -> Expression:
    return var_expr(variable_id)


def param_ref(parameter_id: str) -> Expression:
    return param_expr(parameter_id)


def asset_ref(asset: ExperimentAsset | str) -> Expression:
    return asset_ref_expr(asset)


def acquisition(
    kind: str = "measurement",
    *,
    shots: Expression | Quantity | float | None = None,
    repetitions: Expression | Quantity | float | None = None,
    record: Literal["point", "shot"] = "point",
    channels: Sequence[str] = (),
) -> AcquisitionIntent:
    return AcquisitionIntent(
        kind=kind,
        shots=shots,
        repetitions=repetitions,
        record=record,
        channels=tuple(channels),
    )


def _resolve_subject_inputs(
    ctx: ExperimentAuthoringContext,
    subject_inputs: tuple[str, ...],
    inputs: Mapping[str, object],
) -> list[str]:
    if not subject_inputs:
        ctx.raise_diagnostic(
            "recipe_subject_inputs_empty",
            "recipe must define at least one subject input",
            "subject_inputs",
        )
    subjects: list[str] = []
    for input_id in subject_inputs:
        value = inputs.get(input_id)
        if not isinstance(value, str) or not value:
            ctx.raise_diagnostic(
                "recipe_subject_input_invalid",
                f"recipe subject input {input_id} must be a non-empty string",
                input_id,
            )
        subjects.append(ctx.require_subject(value))
    return subjects


def _build_acquisition(
    ctx: ExperimentAuthoringContext,
    acquisition: AcquisitionSpecIntent,
) -> AcquisitionSpec:
    if isinstance(acquisition, AcquisitionIntent):
        return acquisition.build(ctx)
    return acquisition


def _with_dataset_observations(
    acquisition: AcquisitionSpec,
    dataset: DatasetIntent | None,
    *,
    ctx: ExperimentAuthoringContext,
    variables: Mapping[str, ExperimentVariable],
) -> AcquisitionSpec:
    if dataset is None:
        return acquisition
    schema = dataset.build(ctx, variables)
    observations = [
        ObservationSpec(
            id=variable.id,
            kind="observable",
            unit=variable.unit,
            metadata=variable.metadata,
        )
        for variable in schema.variables
        if variable.role == "observable"
    ]
    return acquisition.model_copy(
        update={"observations": [*acquisition.observations, *observations]}
    )


def _points_relation(variables: Mapping[str, ExperimentVariable]) -> RelationExpr:
    columns: dict[str, object] = {}
    derived: dict[str, ScalarExpr] = {}
    for variable_id, variable in variables.items():
        if variable.kind == "linspace":
            start = _required_quantity(variable.start, variable_id)
            stop = _required_quantity(variable.stop, variable_id)
            columns[variable_id] = relation_linspace(
                start.value,
                stop.value,
                _required_int(variable.count, variable_id),
                unit=start.unit,
            )
        elif variable.kind == "points":
            columns[variable_id] = values(
                _required_quantities(variable.points, variable_id)
            )
        elif variable.kind == "range":
            start = _required_quantity(variable.start, variable_id)
            stop = _required_quantity(variable.stop, variable_id)
            step = _required_quantity(variable.step, variable_id)
            columns[variable_id] = range_values(
                start.value,
                stop.value,
                step.value,
                unit=start.unit,
                include_stop=True,
            )
        elif variable.kind == "derived":
            derived[variable_id] = _expr_to_scalar(
                _required_expression(variable.expression, variable_id)
            )
    relation = grid(**columns) if columns else literal_rows([{}])
    if derived:
        relation = relation.with_columns(**derived)
    return relation


def _state_specs(bindings: Sequence[BindingSpec]) -> list[StateSpec]:
    return [
        set_state(
            binding.resource_id,
            f"{binding.capability_id}.{binding.field_path}",
            _expr_to_scalar(binding.value),
        )
        for binding in bindings
    ]


def _expr_to_scalar(expression: Expression) -> ScalarExpr:
    if expression.kind == "quantity":
        return _literal(_required_quantity(expression.quantity, "expression.quantity"))
    if expression.kind == "number":
        return _literal(_required_float(expression.value, "expression.value"))
    if expression.kind == "variable":
        return col(_required_name(expression.name, "expression.name"))
    if expression.kind == "parameter":
        return param(_required_name(expression.name, "expression.name"))
    if expression.kind == "asset":
        return _literal(
            {
                "kind": "asset",
                "asset_id": _required_name(expression.asset_id, "expression.asset_id"),
            }
        )
    if expression.kind == "binary":
        return ScalarExpr(
            kind="binary",
            op=expression.op,
            left=_expr_to_scalar(
                _required_expression(expression.left, "expression.left")
            ),
            right=_expr_to_scalar(
                _required_expression(expression.right, "expression.right")
            ),
        )
    msg = f"unsupported expression kind: {expression.kind}"
    raise ValueError(msg)


def _static_positive_int(
    ctx: ExperimentAuthoringContext,
    value: Expression | Quantity | float | None,
    *,
    default: int,
    path: str,
) -> int:
    if value is None:
        return default
    expression = (
        value if isinstance(value, Expression) else Expression.from_value(value)
    )
    try:
        evaluated = _expr_to_scalar(expression).eval(
            EvalContext(params=_relation_params(ctx))
        )
    except Exception as error:
        ctx.raise_diagnostic(
            "recipe_acquisition_value_invalid",
            f"acquisition value must resolve from config at authoring time: {error}",
            path,
        )
    if isinstance(evaluated, Quantity):
        number = evaluated.value
    elif isinstance(evaluated, int | float) and not isinstance(evaluated, bool):
        number = float(evaluated)
    else:
        ctx.raise_diagnostic(
            "recipe_acquisition_value_invalid",
            "acquisition value must resolve to a numeric count",
            path,
        )
    if number <= 0 or int(number) != number:
        ctx.raise_diagnostic(
            "recipe_acquisition_value_invalid",
            "acquisition value must be a positive integer",
            path,
        )
    return int(number)


def _relation_params(ctx: ExperimentAuthoringContext) -> ParameterRelationData:
    if ctx.config.parameter_build is None:
        ctx.raise_diagnostic(
            "missing_parameter_build",
            "experiment authoring requires a parameter build snapshot",
            "parameter_build",
        )
    return ParameterRelationData.from_build_snapshot(ctx.config.parameter_build)


def _artifact_ref(asset: ExperimentAsset) -> ArtifactRef:
    uri = None if asset.path or asset.content_hash else f"scopecat-asset:{asset.id}"
    return ArtifactRef(
        id=asset.id,
        kind=asset.kind,
        uri=uri,
        path=asset.path,
        content_hash=asset.content_hash,
        media_type=asset.media_type,
        metadata=asset.metadata,
    )


def _quantity_from_value(value: Quantity | Expression) -> Quantity:
    if isinstance(value, Quantity):
        return value
    if value.kind == "quantity" and value.quantity is not None:
        return value.quantity
    msg = "recipe quantity value must be a Quantity or quantity expression"
    raise TypeError(msg)


def _literal(value: CellValue) -> ScalarExpr:
    return ScalarExpr(kind="literal", value=value)


def _required_quantity(value: Quantity | None, path: str) -> Quantity:
    if value is None:
        msg = f"{path} is required"
        raise ValueError(msg)
    return value


def _required_quantities(value: list[Quantity] | None, path: str) -> list[Quantity]:
    if value is None:
        msg = f"{path} is required"
        raise ValueError(msg)
    return value


def _required_expression(value: Expression | None, path: str) -> Expression:
    if value is None:
        msg = f"{path} is required"
        raise ValueError(msg)
    return value


def _required_int(value: int | None, path: str) -> int:
    if value is None:
        msg = f"{path} is required"
        raise ValueError(msg)
    return value


def _required_float(value: float | None, path: str) -> float:
    if value is None:
        msg = f"{path} is required"
        raise ValueError(msg)
    return value


def _required_name(value: str | None, path: str) -> str:
    if not value:
        msg = f"{path} is required"
        raise ValueError(msg)
    return value


__all__ = [
    "AcquisitionIntent",
    "AssetBindingIntent",
    "BindingIntent",
    "DatasetColumn",
    "DatasetIntent",
    "DerivedVariableIntent",
    "ExperimentBindingIntent",
    "ExperimentRecipe",
    "ExplicitVariableIntent",
    "PointDatasetIntent",
    "ResourceRole",
    "ResourceSelector",
    "ShotDatasetIntent",
    "SweepAroundIntent",
    "VariableIntent",
    "acquisition",
    "asset_binding",
    "asset_ref",
    "bind",
    "coordinate",
    "derive",
    "observable",
    "param_ref",
    "point_dataset",
    "recipe",
    "requires",
    "resource_role",
    "shot_dataset",
    "sweep",
    "var_ref",
    "variable",
]
