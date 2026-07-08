"""Compile and link authoring invocations into closed experiment specs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from scopecat._planning.parameter_patches import ParameterPatchSpec
from scopecat.authoring.context import (
    ExperimentAuthoringContext,
)
from scopecat.authoring.context import (
    diagnostic as _diagnostic,
)
from scopecat.authoring.templates import (
    ConfigProfileInput,
    ExperimentInvocation,
    materialize_request_inputs,
)
from scopecat.config_profiles import load_config_profile
from scopecat.config_registry import resolve_config_registry_config_source
from scopecat.diagnostics import Diagnostic
from scopecat.errors import ValidationFailed
from scopecat.experiments import (
    ExperimentSpec,
    RunParameterSweep,
    RunRequest,
    RunSweep,
    cartesian,
    iter_run_sweep_leaves,
)
from scopecat.models.config import ConfigProfileSnapshot, build_config_parameters
from scopecat.models.parameter import ParameterViewSnapshot
from scopecat.models.run import RunConfigSource
from scopecat.parameters import ParameterDerivationSet
from scopecat.planning.validation import has_blocking_diagnostics
from scopecat.relations import RelationExpr, ScalarExpr, as_scalar_expr, col

if TYPE_CHECKING:
    from scopecat.authoring.assembly import ExperimentAssembly, PointSourceIntent


@dataclass(frozen=True)
class ResolvedExperiment:
    experiment: ExperimentSpec
    template_id: str | None
    inputs: dict[str, object]
    config: ConfigProfileSnapshot
    parameter_view: ParameterViewSnapshot
    parameter_derivations: ParameterDerivationSet | None = None
    config_source: RunConfigSource | None = None
    diagnostics: tuple[Diagnostic, ...] = ()


def resolve_experiment(
    experiment: ExperimentInvocation,
    *,
    workspace: str | Path,
    config_entry: str | None = "active",
    config_profile: ConfigProfileInput | None = None,
) -> ResolvedExperiment:
    config, source = _resolve_config_source(
        workspace=workspace,
        config_entry=config_entry,
        config_profile=config_profile,
    )
    return resolve_experiment_with_config(
        experiment,
        config=config,
        workspace=workspace,
        config_source=source,
    )


def resolve_experiment_with_config(
    experiment: ExperimentInvocation,
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    config_source: RunConfigSource | None = None,
) -> ResolvedExperiment:
    return _resolve_invocation(
        experiment,
        config=config,
        workspace=workspace,
        config_source=config_source,
    )


def _resolve_invocation(
    invocation: ExperimentInvocation,
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    config_source: RunConfigSource | None,
) -> ResolvedExperiment:
    assembly = _compile_invocation(invocation)
    return _link_assembly(
        assembly,
        config=config,
        workspace=workspace,
        config_source=config_source,
    )


def _compile_invocation(invocation: ExperimentInvocation) -> ExperimentAssembly:
    inputs = _merged_inputs(invocation)
    request = _materialized_request(invocation, inputs=inputs)
    from scopecat.authoring.assembly import ExperimentAssembly

    try:
        compiled = invocation.compile(**inputs)
    except ValidationFailed:
        raise
    except Exception as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "experiment_authoring_compile_failed",
                    "experiment authoring compile failed: "
                    f"{type(error).__name__}: {error}",
                    "authoring",
                )
            ]
        ) from error
    if isinstance(compiled, ExperimentAssembly):
        assembly = compiled.with_invocation(
            request=request,
            inputs=inputs,
            parameter_derivations=invocation.parameter_derivations,
        )
        if invocation.runtime_sweeps:
            return _apply_runtime_sweeps(
                assembly,
                invocation.runtime_sweeps,
                inputs=inputs,
            )
        return assembly
    raise ValidationFailed(
        [
            _diagnostic(
                "error",
                "experiment_authoring_compile_result_invalid",
                "experiment authoring compile must produce an ExperimentAssembly",
                "authoring",
            )
        ]
    )


def compile_composed_source(source: object) -> ExperimentAssembly:
    from scopecat.authoring.assembly import (
        AroundPointSourceIntent,
        CompositePointSourceIntent,
        ExperimentAssembly,
        ExperimentModule,
        ModuleBuilder,
        ModuleInvocation,
        ProductSelectionIntent,
        ValuePointSourceIntent,
    )
    from scopecat.relations import RelationExpr

    if isinstance(source, ExperimentAssembly):
        return source
    if isinstance(
        source,
        (
            RelationExpr,
            AroundPointSourceIntent,
            ValuePointSourceIntent,
            CompositePointSourceIntent,
            ProductSelectionIntent,
        ),
    ):
        if isinstance(source, ProductSelectionIntent):
            return ExperimentAssembly(
                entity_inputs=(),
                record_selections=(source,),
            )
        return ExperimentAssembly(entity_inputs=(), point_source=source)
    if isinstance(source, ModuleBuilder):
        return source.as_module().assemble()
    if isinstance(source, ModuleInvocation):
        return source.assemble()
    if isinstance(source, ExperimentModule):
        return source().assemble()
    if isinstance(source, ExperimentInvocation):
        return _compile_invocation(source)
    raise TypeError(
        "compose sources must be ExperimentModule, ModuleInvocation, "
        "ExperimentInvocation, ExperimentAssembly, or point source"
    )


def _link_assembly(
    assembly: ExperimentAssembly,
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    config_source: RunConfigSource | None,
) -> ResolvedExperiment:
    from scopecat.authoring.assembly import link_experiment_assembly

    parameter_view = build_config_parameters(
        config,
        derivations=assembly.parameter_derivations,
    )
    context = ExperimentAuthoringContext(
        config=config,
        parameter_view=parameter_view,
        workspace=Path(workspace),
        config_source=config_source,
    )
    try:
        experiment = link_experiment_assembly(assembly, context)
    except ValidationFailed:
        raise
    except Exception as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "experiment_authoring_link_failed",
                    "experiment authoring link failed: "
                    f"{type(error).__name__}: {error}",
                    "authoring",
                )
            ]
        ) from error
    if assembly.request is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "experiment_authoring_request_missing",
                    "experiment assembly is missing its run request",
                    "authoring.request",
                )
            ]
        )
    return _resolved_spec(
        experiment,
        config=config,
        workspace=workspace,
        config_source=config_source,
        request=assembly.request,
        inputs=assembly.inputs,
        parameter_view=parameter_view,
        parameter_derivations=assembly.parameter_derivations,
        authoring_diagnostics=context.diagnostics,
    )


def _resolved_spec(
    experiment: ExperimentSpec,
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    config_source: RunConfigSource | None,
    request: RunRequest,
    inputs: Mapping[str, object],
    parameter_view: ParameterViewSnapshot,
    parameter_derivations: ParameterDerivationSet | None,
    authoring_diagnostics: list[Diagnostic] | None = None,
) -> ResolvedExperiment:
    del workspace
    diagnostics = list(authoring_diagnostics or [])
    if has_blocking_diagnostics(diagnostics):
        raise ValidationFailed(diagnostics)
    selected_request = experiment.request or request
    experiment = experiment.model_copy(
        update={
            "request": selected_request,
            "config_snapshot_id": config.id,
        }
    )
    return ResolvedExperiment(
        experiment=experiment,
        template_id=selected_request.template_id,
        inputs=dict(inputs),
        config=config,
        parameter_view=parameter_view,
        parameter_derivations=parameter_derivations,
        config_source=config_source,
        diagnostics=tuple(diagnostics),
    )


def _merged_inputs(invocation: ExperimentInvocation) -> dict[str, object]:
    merged = dict(invocation.defaults)
    merged.update(invocation.build_inputs)
    runtime_axes = {
        leaf.axis_id
        for sweep in invocation.runtime_sweeps
        for leaf in iter_run_sweep_leaves(sweep)
    }
    missing = [
        option.id
        for option in invocation.input_descriptions
        if option.id not in merged and option.id not in runtime_axes
    ]
    if missing:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "experiment_template_missing_input",
                    "experiment template missing required input: " + ", ".join(missing),
                    "template.inputs",
                )
            ]
        )
    return merged


def _materialized_request(
    invocation: ExperimentInvocation,
    *,
    inputs: Mapping[str, object],
) -> RunRequest:
    template_inputs = dict(invocation.request.template_inputs)
    template_inputs.update(materialize_request_inputs(inputs))
    point_axes = dict(invocation.request.point_axes)
    parameter_sweeps = list(invocation.request.parameter_sweeps)
    sweep_groups = list(invocation.request.sweep_groups)
    for sweep in invocation.runtime_sweeps:
        sweep_groups.append(sweep.request_record())
        for leaf in iter_run_sweep_leaves(sweep):
            record = leaf.request_record()
            point_axes[leaf.axis_id] = record
            if isinstance(leaf, RunParameterSweep):
                parameter_sweeps.append(record)
    return invocation.request.model_copy(
        update={
            "template_inputs": template_inputs,
            "point_axes": point_axes,
            "parameter_sweeps": parameter_sweeps,
            "sweep_groups": sweep_groups,
        }
    )


def _apply_runtime_sweeps(
    assembly: ExperimentAssembly,
    sweeps: Sequence[RunSweep],
    *,
    inputs: Mapping[str, object],
) -> ExperimentAssembly:
    _validate_runtime_sweeps(sweeps)
    input_sweeps, extra_sweeps = _split_runtime_sweeps(assembly, sweeps)
    point_source = _combine_ordered_point_sources(
        (
            *((_combined_runtime_sweep_points(input_sweeps),) if input_sweeps else ()),
            *(() if assembly.point_source is None else (assembly.point_source,)),
            *((_combined_runtime_sweep_points(extra_sweeps),) if extra_sweeps else ()),
        )
    )
    return replace(
        assembly,
        point_source=point_source,
        params=(
            *assembly.params,
            *tuple(
                _runtime_parameter_patch(sweep, inputs)
                for root in sweeps
                for sweep in iter_run_sweep_leaves(root)
                if isinstance(sweep, RunParameterSweep)
            ),
        ),
    )


def _split_runtime_sweeps(
    assembly: ExperimentAssembly,
    sweeps: Sequence[RunSweep],
) -> tuple[tuple[RunSweep, ...], tuple[RunSweep, ...]]:
    input_axis_ids = {port.id for port in assembly.input_ports} | set(
        assembly.entity_inputs
    )
    input_sweeps: list[RunSweep] = []
    extra_sweeps: list[RunSweep] = []
    for sweep in sweeps:
        target = (
            input_sweeps
            if any(
                leaf.axis_id in input_axis_ids for leaf in iter_run_sweep_leaves(sweep)
            )
            else extra_sweeps
        )
        target.append(sweep)
    return tuple(input_sweeps), tuple(extra_sweeps)


def _combine_ordered_point_sources(
    sources: Sequence[RelationExpr | PointSourceIntent],
) -> RelationExpr | PointSourceIntent | None:
    selected = tuple(sources)
    if not selected:
        return None
    if len(selected) == 1:
        return selected[0]
    from scopecat.authoring.assembly import CompositePointSourceIntent

    return CompositePointSourceIntent(sources=selected)


def _validate_runtime_sweeps(sweeps: Sequence[RunSweep]) -> None:
    axis_ids = [
        leaf.axis_id for sweep in sweeps for leaf in iter_run_sweep_leaves(sweep)
    ]
    duplicates = sorted(
        {axis_id for axis_id in axis_ids if axis_ids.count(axis_id) > 1}
    )
    if duplicates:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "runtime_sweep_axis_duplicate",
                    "duplicate run-time sweep axis: " + ", ".join(duplicates),
                    "run.sweeps",
                )
            ]
        )


def _combined_runtime_sweep_points(
    sweeps: Sequence[RunSweep],
) -> RelationExpr | PointSourceIntent:
    from scopecat.authoring.assembly import CompositePointSourceIntent

    selected = tuple(sweeps)
    if len(selected) > 1:
        selected = (cartesian(*selected),)
    point_sources = tuple(sweep.points for sweep in selected)
    if len(point_sources) == 1:
        return point_sources[0]
    return CompositePointSourceIntent(sources=point_sources)


def _runtime_parameter_patch(
    sweep: RunParameterSweep,
    inputs: Mapping[str, object],
) -> ParameterPatchSpec:
    return ParameterPatchSpec(
        kind="update_rows",
        table_id=sweep.table_id,
        key={
            name: _bind_runtime_input_refs(as_scalar_expr(value), inputs)
            for name, value in sweep.key.items()
        },
        values={sweep.column: col(sweep.axis_id)},
    )


def _bind_runtime_input_refs(
    expression: ScalarExpr,
    inputs: Mapping[str, object],
) -> ScalarExpr:
    if expression.kind == "input":
        input_name = expression.name
        if not input_name:
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "runtime_sweep_input_missing",
                        "run-time sweep key references an unnamed input",
                        "run.sweeps",
                    )
                ]
            )
        if input_name not in inputs:
            return col(input_name)
        return as_scalar_expr(inputs[input_name])
    if expression.kind == "param_lookup":
        return expression.model_copy(
            update={
                "key": {
                    name: _bind_runtime_input_refs(value, inputs)
                    for name, value in (expression.key or {}).items()
                }
            }
        )
    if expression.kind == "binary":
        return expression.model_copy(
            update={
                "left": _bind_runtime_input_refs(
                    _required_scalar(expression.left, "expression.left"),
                    inputs,
                ),
                "right": _bind_runtime_input_refs(
                    _required_scalar(expression.right, "expression.right"),
                    inputs,
                ),
            }
        )
    if expression.kind == "case":
        return expression.model_copy(
            update={
                "cases": [
                    branch.model_copy(
                        update={
                            "condition": _bind_runtime_input_refs(
                                branch.condition,
                                inputs,
                            ),
                            "value": _bind_runtime_input_refs(branch.value, inputs),
                        }
                    )
                    for branch in (expression.cases or [])
                ],
                "fallback": _bind_runtime_input_refs(
                    _required_scalar(expression.fallback, "expression.fallback"),
                    inputs,
                ),
            }
        )
    return expression


def _required_scalar(value: ScalarExpr | None, path: str) -> ScalarExpr:
    if value is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "runtime_sweep_expression_invalid",
                    f"run-time sweep expression missing {path}",
                    "run.sweeps",
                )
            ]
        )
    return value


def _resolve_config_source(
    *,
    workspace: str | Path,
    config_entry: str | None,
    config_profile: ConfigProfileInput | None,
) -> tuple[ConfigProfileSnapshot, RunConfigSource | None]:
    if config_profile is not None:
        if config_entry not in (None, "active"):
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "conflicting_experiment_authoring_config_source",
                        "provide either config_profile or config_entry, not both",
                        "config",
                    )
                ]
            )
        if isinstance(config_profile, ConfigProfileSnapshot):
            return config_profile, None
        return load_config_profile(config_profile), None
    if config_entry is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_experiment_authoring_config_source",
                    "provide config_profile or config_entry",
                    "config",
                )
            ]
        )
    return resolve_config_registry_config_source(
        selector=config_entry,
        workspace=workspace,
    )


__all__ = [
    "ResolvedExperiment",
    "resolve_experiment",
    "resolve_experiment_with_config",
]
