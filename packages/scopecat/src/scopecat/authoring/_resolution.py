"""Compile and link authoring invocations into transient linked programs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from scopecat._compiler.program import LinkedProgram
from scopecat._parameter_resolution import resolve_config_parameters
from scopecat._relations import ParameterRelationData
from scopecat.authoring._assembly_linking import link_experiment_assembly_internal
from scopecat.authoring._context import ExperimentAuthoringContext
from scopecat.authoring._context import (
    diagnostic as _diagnostic,
)
from scopecat.authoring._intents import ParameterScanOverlayIntent
from scopecat.authoring._invocation_plan import (
    InvocationRequestContext,
    PreparedInvocation,
    prepare_invocation,
)
from scopecat.authoring._module_composition import (
    ExperimentAssemblyInternal,
    assemble_invocation_internal,
)
from scopecat.authoring._module_handles import module_exposed_input_types_internal
from scopecat.authoring._parameter_contracts import merge_parameter_contracts
from scopecat.authoring._request_values import (
    project_run_request_inputs,
)
from scopecat.authoring._scan_intents import (
    ParameterScanIntent,
    PointScanIntent,
    ScanGroupIntent,
    ScanLeafIntent,
    inherit_default_scan_fields,
    iter_scan_leaves,
    replace_scan_group,
    scan_parameter_contracts,
    scan_point_id,
)
from scopecat.authoring._scan_lowering import (
    lower_scan_points,
    project_scan_record,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    describe_value_type,
    is_assignable,
    require_assignable,
)
from scopecat.authoring.scans import (
    Scan,
    cartesian,
)
from scopecat.authoring.templates import (
    ConfigProfileInput,
    ExperimentInvocation,
)
from scopecat.authoring.values import ModuleInput, module_input_is_valid
from scopecat.config_profiles import load_config_profile
from scopecat.config_registry import resolve_config_registry_config_source
from scopecat.diagnostics import Diagnostic
from scopecat.errors import ValidationFailed
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.run import RunConfigSource
from scopecat.models.run_request import RunRequest
from scopecat.planning.validation import has_blocking_diagnostics


@dataclass(frozen=True)
class ResolvedExperiment:
    experiment: LinkedProgram
    request: RunRequest
    template_id: str | None
    inputs: dict[str, object]
    config: ConfigProfileSnapshot
    parameters: ParameterRelationData
    config_source: RunConfigSource | None = None
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class _CompiledInvocation:
    assembly: ExperimentAssemblyInternal
    request: RunRequest
    inputs: dict[str, object]


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
    merged_inputs = {**compiled.inputs, **inputs}
    assembly = replace(
        compiled,
        inputs=merged_inputs,
    )
    _validate_point_dependencies(assembly, scans)
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
    )


def _compile_invocation_template(
    invocation: ExperimentInvocation,
    inputs: Mapping[str, object],
) -> ExperimentAssemblyInternal:
    template = invocation.template
    if template.module is None:
        msg = "experiment template requires a module"
        raise ValueError(msg)
    exposed_inputs = module_exposed_input_types_internal(template.module)
    module_inputs: dict[str, ModuleInput] = {}
    for input_id, value in inputs.items():
        if input_id not in exposed_inputs:
            continue
        if not module_input_is_valid(value):
            msg = f"module input {input_id!r} is not typed or closed literal data"
            raise TypeError(msg)
        module_inputs[input_id] = cast("ModuleInput", value)
    assemblies = [assemble_invocation_internal(template.module(**module_inputs))]
    if template.record_selections:
        assemblies.append(
            ExperimentAssemblyInternal(
                entity_inputs=(),
                record_selections=template.record_selections,
            )
        )
    return ExperimentAssemblyInternal.combine(
        experiment_id=template.experiment_id or template.id,
        kind=template.kind or template.id,
        assemblies=assemblies,
        metadata=template.metadata,
    )


def _validate_invocation_inputs(
    invocation: ExperimentInvocation,
    assembly: ExperimentAssemblyInternal,
    inputs: Mapping[str, object],
    *,
    scans: Sequence[Scan],
) -> None:
    allowed = {description.id for description in invocation.template.inputs} | {
        port.id for port in assembly.input_ports
    }
    unknown = sorted(set(inputs) - allowed)
    scan_inputs = {
        scan_point_id(leaf) for scan in scans for leaf in iter_scan_leaves(scan)
    }
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


def _link_assembly(
    assembly: ExperimentAssemblyInternal,
    *,
    request: RunRequest,
    inputs: Mapping[str, object],
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    config_source: RunConfigSource | None,
) -> ResolvedExperiment:
    resolved_parameters = resolve_config_parameters(config)
    if has_blocking_diagnostics(resolved_parameters.diagnostics):
        raise ValidationFailed(list(resolved_parameters.diagnostics))
    context = ExperimentAuthoringContext(
        config=config,
        parameters=resolved_parameters.data,
        workspace=Path(workspace),
        config_source=config_source,
    )
    try:
        experiment = link_experiment_assembly_internal(assembly, context)
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
    return _resolved_invocation(
        experiment,
        config=config,
        workspace=workspace,
        config_source=config_source,
        request=request,
        inputs=inputs,
        parameters=resolved_parameters.data,
        authoring_diagnostics=[
            *resolved_parameters.diagnostics,
            *context.diagnostics,
        ],
    )


def _resolved_invocation(
    experiment: LinkedProgram,
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    config_source: RunConfigSource | None,
    request: RunRequest,
    inputs: Mapping[str, object],
    parameters: ParameterRelationData,
    authoring_diagnostics: list[Diagnostic] | None = None,
) -> ResolvedExperiment:
    del workspace
    diagnostics = list(authoring_diagnostics or [])
    if has_blocking_diagnostics(diagnostics):
        raise ValidationFailed(diagnostics)
    resolved_request = request.model_copy(
        update={
            "config_source": (
                config_source.selector
                if config_source is not None
                else request.config_source
            )
        }
    )
    return ResolvedExperiment(
        experiment=experiment,
        request=resolved_request,
        template_id=resolved_request.template_id,
        inputs=dict(inputs),
        config=config,
        parameters=parameters,
        config_source=config_source,
        diagnostics=tuple(diagnostics),
    )


def _effective_scans(invocation: ExperimentInvocation) -> tuple[Scan, ...]:
    defaults = invocation.template.default_scans
    overrides = tuple(invocation.scans)
    if not defaults:
        _validate_group_override_shape((), overrides)
        return overrides
    default_axis_ids = {
        scan_point_id(leaf) for scan in defaults for leaf in iter_scan_leaves(scan)
    }
    _validate_group_override_shape(default_axis_ids, overrides)
    override_leaves = {
        scan_point_id(leaf): leaf
        for scan in overrides
        for leaf in iter_scan_leaves(scan)
        if scan_point_id(leaf) in default_axis_ids
    }
    replaced = tuple(_replace_scan_leaves(scan, override_leaves) for scan in defaults)
    covered = set(override_leaves)
    additions = tuple(
        scan
        for scan in overrides
        if not any(scan_point_id(leaf) in covered for leaf in iter_scan_leaves(scan))
    )
    return (*replaced, *additions)


def _replace_scan_leaves(
    scan: Scan,
    replacements: Mapping[str, ScanLeafIntent],
) -> Scan:
    if isinstance(scan, ScanGroupIntent):
        return replace_scan_group(
            scan,
            tuple(_replace_scan_leaves(child, replacements) for child in scan.scans),
        )
    if not isinstance(scan, PointScanIntent | ParameterScanIntent):
        msg = "invalid scan handle"
        raise TypeError(msg)
    replacement = replacements.get(scan_point_id(scan))
    if replacement is None:
        return scan
    return inherit_default_scan_fields(scan, replacement)


def _validate_group_override_shape(
    default_axis_ids: set[str] | tuple[()],
    overrides: Sequence[Scan],
) -> None:
    known = set(default_axis_ids)
    for scan in overrides:
        if not isinstance(scan, ScanGroupIntent):
            continue
        axis_ids = {scan_point_id(leaf) for leaf in iter_scan_leaves(scan)}
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
    merged: dict[str, object] = {
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
    scans: Sequence[Scan],
) -> RunRequest:
    template_inputs = project_run_request_inputs(context.template_inputs)
    template_inputs.update(project_run_request_inputs(inputs))
    request_scans = list(context.scans)
    for scan in scans:
        request_scans.append(project_scan_record(scan, inputs=inputs))
    return RunRequest.model_validate(
        {
            "id": context.id,
            "template_id": context.template_id,
            "template_inputs": template_inputs,
            "scans": request_scans,
            "operator": context.operator,
            "metadata": dict(context.metadata),
        }
    )


def _apply_scans(
    assembly: ExperimentAssemblyInternal,
    scans: Sequence[Scan],
    *,
    inputs: Mapping[str, object],
) -> ExperimentAssemblyInternal:
    _validate_scans(scans)
    _validate_scan_target_types(assembly, scans)
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
        parameter_contracts=merge_parameter_contracts(
            assembly.parameter_contracts,
            *(scan_parameter_contracts(scan) for scan in scans),
        ),
        parameter_overlays=(
            *assembly.parameter_overlays,
            *tuple(
                _runtime_parameter_overlay_intent(scan)
                for root in scans
                for scan in iter_scan_leaves(root)
                if isinstance(scan, ParameterScanIntent)
            ),
        ),
    )


def _split_scans(
    assembly: ExperimentAssemblyInternal,
    scans: Sequence[Scan],
) -> tuple[tuple[Scan, ...], tuple[Scan, ...]]:
    input_axis_ids = {port.id for port in assembly.input_ports} | set(
        assembly.entity_inputs
    )
    input_scans: list[Scan] = []
    extra_scans: list[Scan] = []
    for scan in scans:
        target = (
            input_scans
            if any(
                scan_point_id(leaf) in input_axis_ids for leaf in iter_scan_leaves(scan)
            )
            else extra_scans
        )
        target.append(scan)
    return tuple(input_scans), tuple(extra_scans)


def _scan_depends_on_point_row(scan: Scan) -> bool:
    return any(
        isinstance(leaf, PointScanIntent) and leaf.center is not None
        for leaf in iter_scan_leaves(scan)
    )


def _combine_ordered_point_sources(
    sources: Sequence[ValueRef],
) -> ValueRef | None:
    selected = tuple(sources)
    if not selected:
        return None
    if len(selected) == 1:
        return selected[0]
    point_source = selected[0]
    for next_source in selected[1:]:
        point_source = point_source.cross(next_source)
    return point_source


def _validate_scans(scans: Sequence[Scan]) -> None:
    axis_ids = [
        scan_point_id(leaf) for scan in scans for leaf in iter_scan_leaves(scan)
    ]
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


def _validate_scan_target_types(
    assembly: ExperimentAssemblyInternal,
    scans: Sequence[Scan],
) -> None:
    input_types = {port.id: port.value_type for port in assembly.input_ports}
    for root in scans:
        for scan in iter_scan_leaves(root):
            expected = input_types.get(scan_point_id(scan))
            if expected is None:
                continue
            require_assignable(
                scan.target.value_type,
                expected,
                path=f"scans.{scan_point_id(scan)}",
            )


def _validate_point_dependencies(
    assembly: ExperimentAssemblyInternal,
    scans: Sequence[Scan],
) -> None:
    scan_types = {
        scan_point_id(scan): scan.target.value_type
        for root in scans
        for scan in iter_scan_leaves(root)
    }
    diagnostics: list[Diagnostic] = []
    for dependency in assembly.point_dependencies:
        actual = scan_types.get(dependency.id)
        if actual is None:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "experiment_point_dependency_missing",
                    f"module requires point {dependency.id!r}, but no scan provides it",
                    f"scans.{dependency.id}",
                )
            )
            continue
        if is_assignable(actual, dependency.value_type):
            continue
        diagnostics.append(
            _diagnostic(
                "error",
                "experiment_point_dependency_type_mismatch",
                f"scan for point {dependency.id!r} provides "
                f"{describe_value_type(actual)}, but the module requires "
                f"{describe_value_type(dependency.value_type)}",
                f"scans.{dependency.id}",
            )
        )
    if diagnostics:
        raise ValidationFailed(diagnostics)


def _combined_scan_points(
    scans: Sequence[Scan],
    *,
    inputs: Mapping[str, object],
) -> ValueRef:
    selected = tuple(scans)
    if len(selected) > 1:
        selected = (cartesian(*selected),)
    point_sources = tuple(lower_scan_points(scan, inputs=inputs) for scan in selected)
    if len(point_sources) == 1:
        return point_sources[0]
    point_source = point_sources[0]
    for next_source in point_sources[1:]:
        point_source = point_source.cross(next_source)
    return point_source


def _runtime_parameter_overlay_intent(
    scan: ParameterScanIntent,
) -> ParameterScanOverlayIntent:
    return ParameterScanOverlayIntent(
        table_id=scan.table_id,
        key=scan.key,
        column_id=scan.column,
        point_id=scan.point_id,
    )


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
