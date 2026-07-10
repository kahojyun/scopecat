"""Compile and link authoring invocations into closed experiment specs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from scopecat._planning.parameter_patches import ParameterPatchSpec
from scopecat.authoring._invocation_plan import (
    InvocationRequestContext,
    PreparedInvocation,
    prepare_invocation,
)
from scopecat.authoring.context import ExperimentAuthoringContext
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
    ParameterScanAxis,
    RunRequest,
    ScanAxis,
    ScanGroup,
    ScanItem,
    ScanLeaf,
    cartesian,
    iter_scan_leaves,
)
from scopecat.models.config import ConfigProfileSnapshot, build_config_parameters
from scopecat.models.parameter import ParameterViewSnapshot
from scopecat.models.run import RunConfigSource
from scopecat.parameters import ParameterDerivationSet, combine_parameter_derivations
from scopecat.planning.validation import has_blocking_diagnostics
from scopecat.relations import RelationExpr, ScalarExpr, as_scalar_expr, col

if TYPE_CHECKING:
    from scopecat.authoring.assembly import ExperimentAssembly


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


@dataclass(frozen=True)
class _CompiledInvocation:
    assembly: ExperimentAssembly
    request: RunRequest
    inputs: dict[str, object]
    parameter_derivations: ParameterDerivationSet | None


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
    return resolve_prepared_invocation(
        prepare_invocation(experiment),
        config=config,
        workspace=workspace,
        config_source=config_source,
    )


def resolve_prepared_invocation(
    prepared: PreparedInvocation,
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    config_source: RunConfigSource | None = None,
) -> ResolvedExperiment:
    compiled = compile_prepared_invocation(prepared)
    return _link_assembly(
        compiled.assembly,
        request=compiled.request,
        inputs=compiled.inputs,
        parameter_derivations=compiled.parameter_derivations,
        config=config,
        workspace=workspace,
        config_source=config_source,
    )


def compile_prepared_invocation(
    prepared: PreparedInvocation,
) -> _CompiledInvocation:
    invocation = prepared.invocation
    request_context = prepared.request_context
    scans = _effective_scans(invocation)
    inputs = _merged_inputs(invocation)

    try:
        compiled = _compile_invocation_template(invocation, inputs)
        _validate_invocation_inputs(
            invocation,
            compiled,
            inputs,
            scans=scans,
        )
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
    request = _materialized_request(request_context, inputs=inputs, scans=scans)
    invocation_derivations = invocation.template.parameter_derivations
    merged_inputs = {**compiled.inputs, **inputs}
    parameter_derivations = _combined_parameter_derivations(
        id=f"{_compiled_derivation_id(compiled, request)}.parameter_derivations",
        derivations=(
            compiled.parameter_derivations,
            invocation_derivations,
        ),
    )
    assembly = replace(
        compiled,
        inputs=merged_inputs,
        parameter_derivations=parameter_derivations,
    )
    if scans:
        assembly = _apply_scans(
            assembly,
            scans,
            inputs=inputs,
        )
    return _CompiledInvocation(
        assembly=assembly,
        request=request,
        inputs=merged_inputs,
        parameter_derivations=parameter_derivations,
    )


def _compile_invocation_template(
    invocation: ExperimentInvocation,
    inputs: Mapping[str, object],
) -> ExperimentAssembly:
    from scopecat.authoring.assembly import ExperimentAssembly

    template = invocation.template
    if template.module is None:
        msg = "experiment template requires a module"
        raise ValueError(msg)
    assemblies = [template.module(**inputs).assemble()]
    if template.record_selections:
        assemblies.append(
            ExperimentAssembly(
                entity_inputs=(),
                record_selections=template.record_selections,
            )
        )
    return ExperimentAssembly.combine(
        experiment_id=template.experiment_id or template.id,
        kind=template.kind or template.id,
        assemblies=assemblies,
        metadata=template.metadata,
    )


def _validate_invocation_inputs(
    invocation: ExperimentInvocation,
    assembly: ExperimentAssembly,
    inputs: Mapping[str, object],
    *,
    scans: Sequence[ScanItem],
) -> None:
    allowed = {description.id for description in invocation.template.inputs} | {
        port.id for port in assembly.input_ports
    }
    unknown = sorted(set(inputs) - allowed)
    scan_inputs = {leaf.axis_id for scan in scans for leaf in iter_scan_leaves(scan)}
    missing = [
        description.id
        for description in invocation.template.inputs
        if description.id not in inputs and description.id not in scan_inputs
    ]
    diagnostics: list[Diagnostic] = []
    if unknown:
        diagnostics.append(
            _diagnostic(
                "error",
                "experiment_template_unknown_input",
                "experiment template received unknown input: " + ", ".join(unknown),
                "template.inputs",
            )
        )
    if missing:
        diagnostics.append(
            _diagnostic(
                "error",
                "experiment_template_missing_input",
                "experiment template missing required input: " + ", ".join(missing),
                "template.inputs",
            )
        )
    if diagnostics:
        raise ValidationFailed(diagnostics)


def _compiled_derivation_id(assembly: ExperimentAssembly, request: RunRequest) -> str:
    return assembly.experiment_id or request.template_id or request.id


def _combined_parameter_derivations(
    *,
    id: str,  # noqa: A002
    derivations: Sequence[ParameterDerivationSet | None],
) -> ParameterDerivationSet | None:
    selected: list[ParameterDerivationSet] = []
    seen_ids: set[str] = set()
    for derivation in derivations:
        if derivation is None or derivation.id in seen_ids:
            continue
        selected.append(derivation)
        seen_ids.add(derivation.id)
    return combine_parameter_derivations(id=id, derivations=selected)


def _link_assembly(
    assembly: ExperimentAssembly,
    *,
    request: RunRequest,
    inputs: Mapping[str, object],
    parameter_derivations: ParameterDerivationSet | None,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    config_source: RunConfigSource | None,
) -> ResolvedExperiment:
    from scopecat.authoring.assembly import link_experiment_assembly

    parameter_view = build_config_parameters(
        config,
        derivations=parameter_derivations,
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
    return _resolved_spec(
        experiment,
        config=config,
        workspace=workspace,
        config_source=config_source,
        request=request,
        inputs=inputs,
        parameter_view=parameter_view,
        parameter_derivations=parameter_derivations,
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


def _effective_scans(invocation: ExperimentInvocation) -> tuple[ScanItem, ...]:
    defaults = invocation.template.default_scans
    overrides = tuple(invocation.scans)
    if not defaults:
        _validate_group_override_shape((), overrides)
        return overrides
    default_axis_ids = {
        leaf.axis_id for scan in defaults for leaf in iter_scan_leaves(scan)
    }
    _validate_group_override_shape(default_axis_ids, overrides)
    override_leaves = {
        leaf.axis_id: leaf
        for scan in overrides
        for leaf in iter_scan_leaves(scan)
        if leaf.axis_id in default_axis_ids
    }
    replaced = tuple(_replace_scan_leaves(scan, override_leaves) for scan in defaults)
    covered = set(override_leaves)
    additions = tuple(
        scan
        for scan in overrides
        if not any(leaf.axis_id in covered for leaf in iter_scan_leaves(scan))
    )
    return (*replaced, *additions)


def _replace_scan_leaves(
    scan: ScanItem,
    replacements: Mapping[str, ScanLeaf],
) -> ScanItem:
    if isinstance(scan, ScanGroup):
        return scan.__class__(
            kind=scan.kind,
            scans=tuple(
                _replace_scan_leaves(child, replacements) for child in scan.scans
            ),
        )
    replacement = replacements.get(scan.axis_id)
    if replacement is None:
        return scan
    return _inherit_default_scan_fields(scan, replacement)


def _inherit_default_scan_fields(
    default: ScanLeaf,
    replacement: ScanLeaf,
) -> ScanLeaf:
    if not isinstance(default, ScanAxis) or not isinstance(replacement, ScanAxis):
        return replacement
    if replacement.point_values or not replacement.implicit_center:
        return replacement
    return replace(
        replacement,
        target_id=default.target_id,
        center=default.center,
    )


def _validate_group_override_shape(
    default_axis_ids: set[str] | tuple[()],
    overrides: Sequence[ScanItem],
) -> None:
    known = set(default_axis_ids)
    for scan in overrides:
        if not isinstance(scan, ScanGroup):
            continue
        axis_ids = {leaf.axis_id for leaf in iter_scan_leaves(scan)}
        existing = axis_ids & known
        if existing and existing != axis_ids:
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "scan_group_mixed_override",
                        (
                            "scan group cannot mix overridden default axes with "
                            "new axes: " + ", ".join(sorted(axis_ids))
                        ),
                        "scans",
                    )
                ]
            )


def _merged_inputs(
    invocation: ExperimentInvocation,
) -> dict[str, object]:
    merged = {
        input_description.id: input_description.default
        for input_description in invocation.template.inputs
        if input_description.has_default
    }
    merged.update(invocation.inputs)
    return merged


def _materialized_request(
    context: InvocationRequestContext,
    *,
    inputs: Mapping[str, object],
    scans: Sequence[ScanItem],
) -> RunRequest:
    template_inputs = dict(context.template_inputs)
    template_inputs.update(materialize_request_inputs(inputs))
    request_scans = list(context.scans)
    for scan in scans:
        selected_scan = _bind_scan_inputs(scan, inputs)
        request_scans.append(selected_scan.request_record())
    return RunRequest(
        id=context.id,
        template_id=context.template_id,
        template_inputs=template_inputs,
        scans=request_scans,
        operator=context.operator,
        metadata=dict(context.metadata),
    )


def _apply_scans(
    assembly: ExperimentAssembly,
    scans: Sequence[ScanItem],
    *,
    inputs: Mapping[str, object],
) -> ExperimentAssembly:
    _validate_scans(scans)
    input_scans, extra_scans = _split_scans(assembly, scans)
    input_scans = tuple(sorted(input_scans, key=_scan_depends_on_point_row))
    point_source = _combine_ordered_point_sources(
        (
            *(
                (_combined_scan_points(input_scans, inputs=inputs),)
                if input_scans
                else ()
            ),
            *(() if assembly.point_source is None else (assembly.point_source,)),
            *(
                (_combined_scan_points(extra_scans, inputs=inputs),)
                if extra_scans
                else ()
            ),
        )
    )
    return replace(
        assembly,
        point_source=point_source,
        params=(
            *assembly.params,
            *tuple(
                _runtime_parameter_patch(scan, inputs)
                for root in scans
                for scan in iter_scan_leaves(root)
                if isinstance(scan, ParameterScanAxis)
            ),
        ),
    )


def _split_scans(
    assembly: ExperimentAssembly,
    scans: Sequence[ScanItem],
) -> tuple[tuple[ScanItem, ...], tuple[ScanItem, ...]]:
    input_axis_ids = {port.id for port in assembly.input_ports} | set(
        assembly.entity_inputs
    )
    input_scans: list[ScanItem] = []
    extra_scans: list[ScanItem] = []
    for scan in scans:
        target = (
            input_scans
            if any(leaf.axis_id in input_axis_ids for leaf in iter_scan_leaves(scan))
            else extra_scans
        )
        target.append(scan)
    return tuple(input_scans), tuple(extra_scans)


def _scan_depends_on_point_row(scan: ScanItem) -> bool:
    return any(
        isinstance(leaf, ScanAxis) and leaf.center is not None
        for leaf in iter_scan_leaves(scan)
    )


def _combine_ordered_point_sources(
    sources: Sequence[RelationExpr],
) -> RelationExpr | None:
    selected = tuple(sources)
    if not selected:
        return None
    if len(selected) == 1:
        return selected[0]
    relation = selected[0]
    for next_relation in selected[1:]:
        relation = relation.cross(next_relation)
    return relation


def _validate_scans(scans: Sequence[ScanItem]) -> None:
    axis_ids = [leaf.axis_id for scan in scans for leaf in iter_scan_leaves(scan)]
    duplicates = sorted(
        {axis_id for axis_id in axis_ids if axis_ids.count(axis_id) > 1}
    )
    if duplicates:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "scan_axis_duplicate",
                    "duplicate scan axis: " + ", ".join(duplicates),
                    "scans",
                )
            ]
        )


def _combined_scan_points(
    scans: Sequence[ScanItem],
    *,
    inputs: Mapping[str, object],
) -> RelationExpr:
    selected = tuple(_bind_scan_inputs(scan, inputs) for scan in scans)
    if len(selected) > 1:
        selected = (cartesian(*selected),)
    point_sources = tuple(scan.points for scan in selected)
    if len(point_sources) == 1:
        return point_sources[0]
    relation = point_sources[0]
    for next_relation in point_sources[1:]:
        relation = relation.cross(next_relation)
    return relation


def _bind_scan_inputs(scan: ScanItem, inputs: Mapping[str, object]) -> ScanItem:
    from scopecat.authoring.assembly import bind_input_refs

    if isinstance(scan, ScanAxis):
        if scan.center is not None:
            return replace(scan, center=bind_input_refs(scan.center, inputs))
        return scan
    if isinstance(scan, ScanGroup):
        return replace(
            scan,
            scans=tuple(_bind_scan_inputs(child, inputs) for child in scan.scans),
        )
    return scan


def _runtime_parameter_patch(
    scan: ParameterScanAxis,
    inputs: Mapping[str, object],
) -> ParameterPatchSpec:
    return ParameterPatchSpec(
        kind="update_rows",
        table_id=scan.table_id,
        key={
            name: _bind_runtime_input_refs(as_scalar_expr(value), inputs)
            for name, value in scan.key.items()
        },
        values={scan.column: col(scan.axis_id)},
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
                        "runtime_scan_input_missing",
                        "run-time scan key references an unnamed input",
                        "run.scans",
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
                    "runtime_scan_expression_invalid",
                    f"run-time scan expression missing {path}",
                    "run.scans",
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
