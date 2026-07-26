"""Compile authoring invocations into canonical core programs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import cast

from scopecat.authoring._intents import ParameterScanOverlayIntent
from scopecat.authoring._parameter_contracts import merge_parameter_contracts
from scopecat.authoring._point_domain_intents import point_domain_intent_output_types
from scopecat.authoring._scan_intents import (
    CenteredParameterScanIntent,
    ExplicitParameterScanIntent,
    ParameterScanIntent,
    ScanLeafIntent,
    inherit_default_scan_fields,
    iter_scan_leaves,
    parameter_scan_lookup,
    scan_parameter_contracts,
    scan_point_id,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_point_value_ref,
)
from scopecat.authoring.scans import Scan
from scopecat.authoring.templates import ExperimentInvocation
from scopecat.authoring.values import ModuleInput
from scopecat.compiler.frontend.assembly_linking import (
    bind_verified_assembly,
)
from scopecat.compiler.frontend.assembly_verification import verify_assembly
from scopecat.compiler.frontend.elaboration import (
    SemanticExperimentIR,
    elaborate_module,
)
from scopecat.compiler.frontend.environment import ConfigEnvironment
from scopecat.compiler.frontend.graph_validation import VerifiedAssembly
from scopecat.compiler.frontend.problems import frontend_problem as _problem
from scopecat.compiler.frontend.request_values import (
    project_run_request_inputs,
)
from scopecat.compiler.frontend.scan_lowering import (
    lower_scans_point_domain,
    project_scan_record,
)
from scopecat.compiler.frontend.scan_validation import (
    ScanValidationError,
    VerifiedScans,
    verify_scans,
)
from scopecat.compiler.linking.linked import LinkedPlan, link_program
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import Problem
from scopecat.kernel.value_type_compatibility import (
    describe_value_type,
    is_assignable,
)
from scopecat.records.run_request import RunRequest


@dataclass(frozen=True, slots=True)
class CompiledInvocation:
    """Config-free result of compiling one DSL invocation."""

    assembly: VerifiedAssembly
    request: RunRequest


def resolve_compiled_invocation(
    compiled: CompiledInvocation,
    *,
    environment: ConfigEnvironment,
) -> LinkedPlan:
    return link_program(
        bind_verified_assembly(compiled.assembly, environment),
        environment=environment,
    )


def compile_invocation(
    invocation: ExperimentInvocation,
    *,
    metadata: Mapping[str, object] | None = None,
    operator: str | None = None,
) -> CompiledInvocation:
    scans = _effective_scans(invocation)
    inputs = _merged_inputs(invocation)
    compiled = _compile_invocation_definition(invocation, inputs)
    verified_scans = _verified_scans(
        compiled,
        scans,
        inputs=inputs,
    )
    _validate_required_invocation_inputs(
        invocation,
        inputs,
        verified_scans=verified_scans,
    )
    request = _materialized_request(
        invocation,
        inputs=inputs,
        verified_scans=verified_scans,
        metadata=metadata,
        operator=operator,
    )
    merged_inputs = {**compiled.inputs, **inputs}
    assembly = replace(
        compiled,
        inputs=merged_inputs,
    )
    _validate_point_dependencies(assembly, verified_scans)
    assembly = _apply_scans(
        assembly,
        verified_scans,
        inputs=inputs,
    )
    return CompiledInvocation(
        assembly=verify_assembly(assembly),
        request=request,
    )


def _compile_invocation_definition(
    invocation: ExperimentInvocation,
    inputs: Mapping[str, object],
) -> SemanticExperimentIR:
    definition = invocation.definition
    module_input_ids = {port.id for port in definition.module.interface.imports}
    module_inputs: dict[str, ModuleInput] = {}
    for input_id, value in inputs.items():
        if input_id not in module_input_ids:
            continue
        module_inputs[input_id] = cast("ModuleInput", value)
    assembly = elaborate_module(
        definition.module,
        **module_inputs,
    )
    return replace(
        assembly,
        experiment_id=definition.id,
        kind=definition.kind,
        record_selections=(
            *assembly.record_selections,
            *definition.record_selections,
        ),
    )


def _validate_required_invocation_inputs(
    invocation: ExperimentInvocation,
    inputs: Mapping[str, object],
    *,
    verified_scans: VerifiedScans,
) -> None:
    scan_axis_ids = {axis.id for axis in verified_scans.axes}
    missing = [
        definition.id
        for definition in invocation.definition.inputs
        if definition.required
        and definition.id not in inputs
        and definition.id not in scan_axis_ids
    ]
    if missing:
        raise CheckFailed(
            [
                _problem(
                    "experiment_missing_input",
                    "experiment missing required input: " + ", ".join(missing),
                    "experiment",
                    path=("inputs",),
                )
            ]
        )


def _effective_scans(invocation: ExperimentInvocation) -> tuple[ScanLeafIntent, ...]:
    defaults = tuple(
        leaf
        for scan in invocation.definition.default_scans
        for leaf in iter_scan_leaves(scan)
    )
    overrides = tuple(
        leaf for scan in invocation.scans for leaf in iter_scan_leaves(scan)
    )
    override_axis_ids = [scan_point_id(scan) for scan in overrides]
    # Validate before indexing so repeated overrides cannot silently collapse.
    duplicate_overrides = sorted(
        axis_id for axis_id, count in Counter(override_axis_ids).items() if count > 1
    )
    if duplicate_overrides:
        raise CheckFailed(
            [
                _problem(
                    "scan_axis_duplicate",
                    "duplicate scan axis: " + ", ".join(duplicate_overrides),
                    "scans",
                )
            ]
        )
    default_axis_ids = {scan_point_id(scan) for scan in defaults}
    override_by_id = {scan_point_id(scan): scan for scan in overrides}
    replaced = tuple(
        inherit_default_scan_fields(default, override_by_id[scan_point_id(default)])
        if scan_point_id(default) in override_by_id
        else default
        for default in defaults
    )
    additions = tuple(
        scan for scan in overrides if scan_point_id(scan) not in default_axis_ids
    )
    return (*replaced, *additions)


def _merged_inputs(
    invocation: ExperimentInvocation,
) -> dict[str, object]:
    merged: dict[str, object] = {
        input_definition.id: input_definition.default
        for input_definition in invocation.definition.inputs
        if input_definition.has_default
    }
    merged.update(invocation.inputs)
    return merged


def _materialized_request(
    invocation: ExperimentInvocation,
    *,
    inputs: Mapping[str, object],
    verified_scans: VerifiedScans,
    metadata: Mapping[str, object] | None,
    operator: str | None,
) -> RunRequest:
    request_inputs = project_run_request_inputs(inputs)
    request_scans = [
        project_scan_record(axis.leaf, inputs=inputs) for axis in verified_scans.axes
    ]
    return RunRequest.model_validate(
        {
            "experiment_id": invocation.definition.id,
            "inputs": request_inputs,
            "scans": request_scans,
            "operator": operator,
            "metadata": dict(metadata or {}),
        }
    )


def _verified_scans(
    assembly: SemanticExperimentIR,
    scans: Sequence[Scan],
    *,
    inputs: Mapping[str, object],
) -> VerifiedScans:
    try:
        return verify_scans(
            scans,
            inputs=inputs,
            input_types={port.id: port.value_type for port in assembly.input_ports},
        )
    except ScanValidationError as error:
        raise CheckFailed(
            [
                _problem(
                    issue.code,
                    issue.message,
                    "scans",
                    path=issue.path,
                )
                for issue in error.issues
            ]
        ) from error


def _apply_scans(
    assembly: SemanticExperimentIR,
    verified_scans: VerifiedScans,
    *,
    inputs: Mapping[str, object],
) -> SemanticExperimentIR:
    scan_leaves = tuple(axis.leaf for axis in verified_scans.axes)
    point_domain = lower_scans_point_domain(
        scan_leaves,
        inputs=inputs,
    )
    consumed_point_input_ids = {port.id for port in assembly.input_ports}
    point_inputs = {
        input_id: target
        for input_id, target in _point_provider_inputs(verified_scans).items()
        if input_id in consumed_point_input_ids and input_id not in assembly.inputs
    }
    return replace(
        assembly,
        inputs={**assembly.inputs, **point_inputs},
        point_domain=point_domain,
        parameter_contracts=merge_parameter_contracts(
            assembly.parameter_contracts,
            *(scan_parameter_contracts(axis.leaf) for axis in verified_scans.axes),
        ),
        parameter_overlays=(
            *assembly.parameter_overlays,
            *tuple(
                _runtime_parameter_overlay_intent(axis.leaf)
                for axis in verified_scans.axes
                if isinstance(
                    axis.leaf,
                    ExplicitParameterScanIntent | CenteredParameterScanIntent,
                )
            ),
        ),
    )


def _point_provider_inputs(
    verified_scans: VerifiedScans,
) -> dict[str, ValueRef]:
    """Map every scan coordinate to one explicit point-value handle."""

    return {
        axis.id: internal_point_value_ref(axis.id, axis.value_type)
        for axis in verified_scans.axes
    }


def _validate_point_dependencies(
    assembly: SemanticExperimentIR,
    verified_scans: VerifiedScans,
) -> None:
    point_types = {
        **point_domain_intent_output_types(assembly.point_domain),
        **{axis.id: axis.value_type for axis in verified_scans.axes},
    }
    problems: list[Problem] = []
    for dependency in assembly.point_dependencies:
        actual = point_types.get(dependency.id)
        if actual is None:
            problems.append(
                _problem(
                    "experiment_point_dependency_missing",
                    f"module requires point {dependency.id!r}, but no point "
                    "domain provides it",
                    "scans",
                    path=(dependency.id,),
                )
            )
            continue
        if is_assignable(actual, dependency.value_type):
            continue
        problems.append(
            _problem(
                "experiment_point_dependency_type_mismatch",
                f"scan for point {dependency.id!r} provides "
                f"{describe_value_type(actual)}, but the module requires "
                f"{describe_value_type(dependency.value_type)}",
                "scans",
                path=(dependency.id,),
            )
        )
    if problems:
        raise CheckFailed(problems)


def _runtime_parameter_overlay_intent(
    scan: ParameterScanIntent,
) -> ParameterScanOverlayIntent:
    lookup, key = parameter_scan_lookup(scan)
    return ParameterScanOverlayIntent(
        table_id=lookup.table_id,
        key=key,
        column_id=lookup.column_id,
        point_id=scan_point_id(scan),
    )
