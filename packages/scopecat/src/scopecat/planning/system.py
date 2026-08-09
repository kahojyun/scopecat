"""Compile bound experiment semantics for one physical experiment system.

This boundary coordinates local target selection, domain lowering, and bounded
coverage so placement decisions share one view of effect order and resource
ownership. Its output is the closed ``RunProgram`` accepted by execution.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import cast

from scopecat.compiler.bind import BoundDomainTarget, BoundPlan
from scopecat.execution.local.program import (
    ApplyStateOperation,
    InvokeOperation,
    LocalOperation,
)
from scopecat.execution.program import (
    RunCoverageCheckpoint,
    RunCoverageEffect,
    RunCoveredOperation,
    RunDomainJob,
    RunHostBinding,
    RunProgram,
)
from scopecat.kernel.errors import CheckFailed, ProviderContractError
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.kernel.resource_identity import (
    DomainTargetRequirement,
    ResourceRequirement,
)
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.kernel.value_identity import scalar_values_equal
from scopecat.measurements.projection import select_measurement_projection
from scopecat.planning.catalog import InstrumentContractCatalog
from scopecat.planning.domain_bridge import (
    make_domain_batch_request,
    make_domain_call_view,
    make_domain_compile_request,
)
from scopecat.planning.domain_results import (
    domain_result_product_use_ids,
)
from scopecat.planning.local_effects import (
    MaterializedLocalEffects,
    local_operation_resource_requirements,
)
from scopecat.planning.local_materialization import (
    materialize_local_execution,
    materialize_local_success_state,
    prepare_local_target,
)
from scopecat.planning.measurement_projection import (
    project_measurement_catalog,
    project_run_point_catalog,
    project_static_value_record_candidates,
)
from scopecat.planning.point_materialization import (
    MaterializedBoundPoints,
    materialize_bound_points,
)
from scopecat.planning.point_order import point_execution_ordinals
from scopecat.planning.provider_binding import (
    validate_run_host_binding,
)
from scopecat.program.logical import LogicalDomainExecution, LogicalEffect
from scopecat.records.config import (
    ConfigProfileSnapshot,
    config_content_hash,
)
from scopecat.sdk.domain.compiler import (
    DomainCompiler,
)
from scopecat.sdk.domain.execution import DomainStateAddress, PreparedDomainExecution
from scopecat.sdk.domain.view import DomainCallView
from scopecat.sdk.instruments.contracts import (
    resolve_implementation_component,
    resolve_implementation_state_reference,
)
from scopecat.sdk.payloads import PayloadCodecRegistry


@dataclass(frozen=True, slots=True)
class ExperimentSystem:
    """The physical interfaces used to lower one experiment definition.

    The daemon-resolved instrument catalog is immutable planning input. Domain
    compilers and payload codecs remain local code because they lower and encode
    author-authored values without opening instrument connections.
    """

    instrument_catalog: InstrumentContractCatalog = field(repr=False)
    domain_compiler: DomainCompiler | None = field(default=None, repr=False)
    payload_codecs: PayloadCodecRegistry = field(
        default_factory=PayloadCodecRegistry,
        repr=False,
        compare=False,
    )

    def compile(
        self,
        bound: BoundPlan,
    ) -> RunProgram:
        return _compile_system_program(
            system=self,
            bound=bound,
        )


type ExperimentSystemBuilder = Callable[
    [ConfigProfileSnapshot, InstrumentContractCatalog],
    ExperimentSystem,
]


def build_experiment_system(
    builder: ExperimentSystemBuilder | None,
    config: ConfigProfileSnapshot,
    instrument_catalog: InstrumentContractCatalog,
) -> ExperimentSystem:
    """Build a config-bound experiment system at the planning boundary."""

    if builder is None:
        return ExperimentSystem(instrument_catalog=instrument_catalog)
    system = builder(config, instrument_catalog)
    if system.instrument_catalog != instrument_catalog:
        raise ValueError(
            "experiment system builder must retain the daemon instrument catalog"
        )
    return system


def _compile_system_program(
    *,
    system: ExperimentSystem,
    bound: BoundPlan,
) -> RunProgram:
    config = bound.environment.config
    catalog = system.instrument_catalog
    expected_config_hash = config_content_hash(config)
    if catalog.config_content_hash != expected_config_hash:
        raise ProviderContractError(
            (
                problem(
                    "instrument_catalog_config_mismatch",
                    "instrument contracts do not match the planning configuration",
                    phase=ProblemPhase.PROVIDER_PREFLIGHT,
                    location=model_location(
                        "instrument_catalog",
                        "config_content_hash",
                    ),
                    details={
                        "expected": expected_config_hash,
                        "actual": catalog.config_content_hash,
                    },
                ),
            )
        )
    domain_use_ids_by_execution = {
        execution.id: domain_result_product_use_ids(bound.bindings, execution)
        for execution in bound.program.program.domain_executions
    }
    domain_calls = {
        execution_id: make_domain_call_view(
            bound,
            execution_id,
            product_use_ids,
        )
        for execution_id, product_use_ids in domain_use_ids_by_execution.items()
    }
    _validate_domain_compiler(
        system.domain_compiler,
        target=bound.domain_target,
    )
    domain_owned_product_use_ids = frozenset(
        use_id
        for product_use_ids in domain_use_ids_by_execution.values()
        for use_id in product_use_ids
    )
    postprocessor_output_use_ids = frozenset(
        use_id
        for postprocessor in bound.bindings.measurement_postprocessors
        for output in postprocessor.outputs
        for use_id in output.product_use_ids
    )
    local_product_use_ids = tuple(
        use.id
        for use in bound.bindings.product_uses
        if use.id not in domain_owned_product_use_ids
        and use.id not in postprocessor_output_use_ids
    )
    local_instrument_required = bool(
        local_product_use_ids
        or bound.program.program.bindings
        or bound.program.program.invocations
    )
    local_execution_required = bool(
        local_instrument_required or bound.bindings.live_compute_ids
    )
    implementation_problems = list(
        _implementation_problems(
            has_domain_call=bool(bound.program.program.domain_executions),
            has_domain_compiler=system.domain_compiler is not None,
            local_instrument_required=local_instrument_required,
            domain_instrument_required=False,
            has_local_instrument_catalog=catalog.provider_id is not None,
        )
    )
    if implementation_problems:
        raise CheckFailed(implementation_problems)
    if local_instrument_required and catalog.problems:
        raise ProviderContractError(catalog.problems)
    bound_points = materialize_bound_points(bound)
    point_domain = bound_points.point_domain
    logical = bound.program.program
    execution_ordinals = point_execution_ordinals(
        point_domain,
        repeat=logical.point_repeat,
        repeat_mode=logical.point_repeat_mode,
        traversal=logical.point_traversal,
    )
    measurement_catalog = project_measurement_catalog(bound_points)
    point_catalog = project_run_point_catalog(bound_points)
    measurements = select_measurement_projection(
        measurement_catalog,
        bound.bindings.record_uses,
        static_value_candidates=project_static_value_record_candidates(bound_points),
    )
    local_target = (
        prepare_local_target(
            bound,
            product_use_ids=frozenset(local_product_use_ids),
            instrument_order=tuple(item.instrument_id for item in catalog.instruments),
        )
        if local_execution_required
        else None
    )
    local_effects = (
        materialize_local_execution(
            bound_points,
            target=local_target,
            point_ordinals=execution_ordinals,
        )
        if local_target is not None
        else None
    )
    local_success_state = (
        materialize_local_success_state(
            bound,
            target=local_target,
        )
        if local_target is not None
        else ()
    )
    local_requirements = _local_resource_requirements(
        local_effects,
        success_state=local_success_state,
    )
    coverage = _compile_coverage(
        system=system,
        bound=bound,
        bound_points=bound_points,
        point_ordinals=execution_ordinals,
        domain_calls=domain_calls,
        local_effects=local_effects,
    )
    domain_instrument_ids = _domain_execution_instrument_ids(coverage)
    domain_target_requirement = _domain_target_requirement(
        bound.domain_target,
        instrument_ids=domain_instrument_ids,
    )
    domain_footprint = _domain_target_footprint(domain_target_requirement)
    domain_instrument_required = bool(domain_instrument_ids)
    domain_implementation_problems = _implementation_problems(
        has_domain_call=False,
        has_domain_compiler=True,
        local_instrument_required=False,
        domain_instrument_required=domain_instrument_required,
        has_local_instrument_catalog=catalog.provider_id is not None,
    )
    if domain_implementation_problems:
        raise CheckFailed(domain_implementation_problems)
    if domain_instrument_required and catalog.problems:
        raise ProviderContractError(catalog.problems)
    resource_requirements = _sorted_requirements(
        (*local_requirements, *domain_footprint)
    )
    local_instrument_ids = frozenset(
        requirement.id for requirement in local_requirements
    )
    host = _host_binding(
        catalog,
        instrument_ids=local_instrument_ids | frozenset(domain_instrument_ids),
        payload_codecs=system.payload_codecs,
    )
    if host is not None:
        validate_run_host_binding(
            host=host,
            effect_blocks=(
                ()
                if local_effects is None
                else (
                    tuple(
                        effect.operation for effect in local_effects.compute_operations
                    ),
                    *(
                        tuple(effect.operation for effect in effects)
                        for effects in local_effects.effect_operations
                    ),
                    local_success_state,
                )
            ),
            problems=(),
        )
    _reject_host_domain_state_write_conflicts(local_effects, coverage)
    _validate_domain_state_requirements(coverage, catalog=catalog)

    return RunProgram(
        config_content_hash=config_content_hash(config),
        host=host,
        coverage=coverage,
        success_state=local_success_state,
        points=point_catalog,
        measurements=measurements,
        measurement_postprocessors=bound.bindings.measurement_postprocessors,
        resource_requirements=resource_requirements,
        domain_target_requirement=domain_target_requirement,
    )


def _host_binding(
    catalog: InstrumentContractCatalog,
    *,
    instrument_ids: frozenset[str],
    payload_codecs: PayloadCodecRegistry,
) -> RunHostBinding | None:
    provider_id = catalog.provider_id
    if provider_id is None or not instrument_ids:
        return None
    instrument_order = tuple(
        description.instrument_id
        for description in catalog.instruments
        if description.instrument_id in instrument_ids
    )
    return RunHostBinding(
        resource_order=instrument_order,
        provider_id=provider_id,
        advertised_descriptions={
            description.instrument_id: description
            for description in catalog.instruments
        },
        payload_codecs=payload_codecs,
    )


def _validate_domain_compiler(
    compiler: DomainCompiler | None,
    *,
    target: BoundDomainTarget | None,
) -> None:
    if target is None or compiler is None:
        return
    if compiler.target_id != target.id:
        raise CheckFailed(
            [
                _planning_problem(
                    "domain_target_mismatch",
                    "the domain compiler target does not match the bound target",
                    details={
                        "compiler_target_id": compiler.target_id,
                        "configured_target_id": target.id,
                    },
                )
            ]
        )
    if compiler.target_kind != target.kind:
        raise CheckFailed(
            [
                _planning_problem(
                    "domain_target_kind_mismatch",
                    "the domain compiler adapter does not match the bound target",
                    details={
                        "compiler_target_kind": compiler.target_kind,
                        "configured_target_kind": target.kind,
                    },
                )
            ]
        )


def _domain_target_requirement(
    target: BoundDomainTarget | None,
    *,
    instrument_ids: tuple[str, ...],
) -> DomainTargetRequirement | None:
    if target is None:
        return None
    unauthorized = sorted(set(instrument_ids) - set(target.instrument_ids))
    if unauthorized:
        raise CheckFailed(
            [
                _planning_problem(
                    "domain_target_instrument_unauthorized",
                    "the compiled domain execution requires instruments outside "
                    "the configured target authority",
                    details={"instrument_ids": unauthorized},
                )
            ]
        )
    return DomainTargetRequirement(
        id=target.id,
        kind=target.kind,
        instrument_ids=instrument_ids,
    )


def _domain_execution_instrument_ids(
    coverage: tuple[RunCoveredOperation, ...],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                instrument_id
                for operation in coverage
                if isinstance(operation, RunDomainJob)
                for instrument_id in operation.execution.instrument_ids
            }
        )
    )


def _domain_target_footprint(
    target: DomainTargetRequirement | None,
) -> tuple[ResourceRequirement, ...]:
    if target is None:
        return ()
    return _sorted_requirements(
        tuple(
            ResourceRequirement(instrument_id, "instrument")
            for instrument_id in target.instrument_ids
        )
    )


def _sorted_requirements(
    requirements: tuple[ResourceRequirement, ...],
) -> tuple[ResourceRequirement, ...]:
    return tuple(
        sorted(
            set(requirements),
            key=lambda requirement: (requirement.kind, requirement.id),
        )
    )


def _local_resource_requirements(
    local_effects: MaterializedLocalEffects | None,
    *,
    success_state: Sequence[LocalOperation] = (),
) -> tuple[ResourceRequirement, ...]:
    if local_effects is None and not success_state:
        return ()
    effect_operations = (
        ()
        if local_effects is None
        else (
            *(effect.operation for effect in local_effects.compute_operations),
            *(
                effect.operation
                for group in local_effects.effect_operations
                for effect in group
            ),
        )
    )
    return _sorted_requirements(
        tuple(
            requirement
            for operation in (*effect_operations, *success_state)
            for requirement in local_operation_resource_requirements(operation)
        )
    )


def _reject_host_domain_state_write_conflicts(
    local_effects: MaterializedLocalEffects | None,
    coverage: tuple[RunCoveredOperation, ...],
) -> None:
    """Keep one writer for each physical property within point coverage."""

    host_write_points: dict[DomainStateAddress, set[int]] = {}
    if local_effects is not None:
        for group in local_effects.effect_operations:
            for covered in group:
                operation = covered.operation
                if not isinstance(operation, ApplyStateOperation):
                    continue
                for target in operation.targets:
                    address = DomainStateAddress(
                        instrument_id=operation.instrument_id,
                        interface_id=target.interface_id,
                        component_path=target.component_path,
                        property_id=target.property_id,
                    )
                    host_write_points.setdefault(address, set()).add(
                        covered.point_index
                    )
    domain_write_points: dict[DomainStateAddress, set[int]] = {}
    for operation in coverage:
        if not isinstance(operation, RunDomainJob):
            continue
        for write in (
            *operation.execution.setup_write_footprint,
            *operation.execution.realtime_write_footprint,
        ):
            domain_write_points.setdefault(write, set()).update(
                operation.point_ordinals
            )
    conflicts = tuple(
        sorted(
            address
            for address in host_write_points.keys() & domain_write_points.keys()
            if host_write_points[address] & domain_write_points[address]
        )
    )
    if conflicts:
        raise CheckFailed(
            [
                _planning_problem(
                    "host_domain_state_write_conflict",
                    "host and domain effects cannot both own the same physical "
                    "state property",
                    details={
                        "state_addresses": tuple(
                            _state_address_description(address) for address in conflicts
                        )
                    },
                )
            ]
        )


def _state_address_description(address: DomainStateAddress) -> str:
    component = "/".join(address.component_path)
    mounted_interface = (
        f"{address.interface_id}/{component}" if component else address.interface_id
    )
    return f"{address.instrument_id}:{mounted_interface}.{address.property_id}"


@dataclass(frozen=True, slots=True)
class _ScheduledStateGuarantee:
    value: StateValue
    provenance: dict[str, object]


def _validate_domain_state_requirements(
    coverage: tuple[RunCoveredOperation, ...],
    *,
    catalog: InstrumentContractCatalog,
) -> None:
    """Verify requirements against guarantees scheduled by preceding stages."""

    guarantees: dict[DomainStateAddress, _ScheduledStateGuarantee] = {}
    invalidated_by: dict[DomainStateAddress, dict[str, object]] = {}
    problems: list[Problem] = []
    for covered in coverage:
        if isinstance(covered, RunCoverageEffect) and isinstance(
            operation := covered.operation,
            ApplyStateOperation,
        ):
            for target in operation.targets:
                address = DomainStateAddress(
                    instrument_id=operation.instrument_id,
                    interface_id=target.interface_id,
                    component_path=target.component_path,
                    property_id=target.property_id,
                )
                guarantees[address] = _ScheduledStateGuarantee(
                    value=target.value,
                    provenance={
                        "kind": "host_state",
                        "point_index": covered.point_index,
                    },
                )
                invalidated_by.pop(address, None)
            continue
        if isinstance(covered, RunCoverageEffect) and isinstance(
            operation := covered.operation,
            InvokeOperation,
        ):
            provenance: dict[str, object] = {
                "kind": "host_operation",
                "instrument_id": operation.instrument_id,
                "interface_id": operation.interface_id,
                "component_path": operation.component_path,
                "operation_id": operation.operation_id,
                "point_index": covered.point_index,
            }
            for invalidated in _invoke_state_invalidations(operation, catalog):
                guarantees.pop(invalidated, None)
                invalidated_by[invalidated] = provenance
            continue
        if not isinstance(covered, RunDomainJob):
            continue
        for requirement in covered.execution.state_requirements:
            actual = guarantees.get(requirement.address)
            if actual is None:
                details: dict[str, object] = {
                    "domain_job_id": covered.id,
                    "state_address": _state_address_description(requirement.address),
                    "point_ordinals": covered.point_ordinals,
                }
                if invalidation_provenance := invalidated_by.get(requirement.address):
                    details["invalidated_by"] = invalidation_provenance
                problems.append(
                    _planning_problem(
                        "domain_state_requirement_missing",
                        "domain execution requires physical state that no "
                        "preceding host stage guarantees",
                        details=details,
                    )
                )
            elif not _state_values_equal(actual.value, requirement.value):
                problems.append(
                    _planning_problem(
                        "domain_state_requirement_mismatch",
                        "domain execution requires a different physical state "
                        "value than the preceding host guarantee",
                        details={
                            "domain_job_id": covered.id,
                            "state_address": _state_address_description(
                                requirement.address
                            ),
                            "point_ordinals": covered.point_ordinals,
                            "guaranteed_by": actual.provenance,
                        },
                    )
                )
        for invalidated in covered.execution.setup_write_footprint:
            guarantees.pop(invalidated, None)
            invalidated_by[invalidated] = {
                "kind": "domain_setup_write_footprint",
                "domain_job_id": covered.id,
                "point_ordinals": covered.point_ordinals,
            }
        for invalidated in covered.execution.setup_state_invalidations:
            guarantees.pop(invalidated, None)
            invalidated_by[invalidated] = {
                "kind": "domain_setup_invalidation",
                "domain_job_id": covered.id,
                "point_ordinals": covered.point_ordinals,
            }
        for requirement in covered.execution.state_requirements:
            guarantees[requirement.address] = _ScheduledStateGuarantee(
                value=requirement.value,
                provenance={
                    "kind": "domain_requirement_reconciliation",
                    "domain_job_id": covered.id,
                    "point_ordinals": covered.point_ordinals,
                },
            )
            invalidated_by.pop(requirement.address, None)
        for invalidated in covered.execution.realtime_write_footprint:
            guarantees.pop(invalidated, None)
            invalidated_by[invalidated] = {
                "kind": "domain_realtime_write_footprint",
                "domain_job_id": covered.id,
                "point_ordinals": covered.point_ordinals,
            }
        for invalidated in covered.execution.realtime_state_invalidations:
            guarantees.pop(invalidated, None)
            invalidated_by[invalidated] = {
                "kind": "domain_realtime_invalidation",
                "domain_job_id": covered.id,
                "point_ordinals": covered.point_ordinals,
            }
    if problems:
        raise CheckFailed(problems)


def _invoke_state_invalidations(
    operation: InvokeOperation,
    catalog: InstrumentContractCatalog,
) -> tuple[DomainStateAddress, ...]:
    description = next(
        item
        for item in catalog.instruments
        if item.instrument_id == operation.instrument_id
    )
    interface_spec = next(
        item for item in description.interfaces if item.id == operation.interface_id
    )
    component_spec = resolve_implementation_component(
        description,
        interface_spec,
        operation.component_path,
    )
    assert component_spec is not None
    operation_spec = next(
        item for item in component_spec.operations if item.id == operation.operation_id
    )
    resolved = tuple(
        resolve_implementation_state_reference(
            description,
            reference,
            context_interface_id=operation.interface_id,
            context_component_path=operation.component_path,
        )
        for reference in operation_spec.invalidates
    )
    if any(reference is None for reference in resolved):
        raise ValueError(
            f"operation {operation.operation_id!r} has an invalid state "
            "invalidation mount"
        )
    return tuple(
        DomainStateAddress(
            instrument_id=operation.instrument_id,
            interface_id=reference.interface_id,
            component_path=tuple(reference.component_path),
            property_id=reference.property_id,
        )
        for reference in resolved
        if reference is not None
    )


def _state_values_equal(left: StateValue, right: StateValue) -> bool:
    left_value = left.root
    right_value = right.root
    if isinstance(left_value, PayloadRef) or isinstance(right_value, PayloadRef):
        return left_value == right_value
    return scalar_values_equal(left_value, right_value)


def _compile_coverage(
    *,
    system: ExperimentSystem,
    bound: BoundPlan,
    bound_points: MaterializedBoundPoints,
    point_ordinals: tuple[int, ...],
    domain_calls: dict[str, DomainCallView],
    local_effects: MaterializedLocalEffects | None,
) -> tuple[RunCoveredOperation, ...]:
    region = point_ordinals
    if not region:
        return ()
    compiler = cast("DomainCompiler", system.domain_compiler)
    compile_regions = _stable_host_regions(region, local_effects)
    scheduled_local_effects = _coalesce_host_state(local_effects, compile_regions)
    jobs_by_execution: dict[str, list[RunDomainJob]] = {}
    for execution in bound.program.program.effects:
        if not isinstance(execution, LogicalDomainExecution):
            continue
        jobs: list[RunDomainJob] = []
        for compile_region in compile_regions:
            jobs.extend(
                _compile_domain_batches(
                    compiler,
                    domain_calls[execution.id],
                    bound_points,
                    compile_region,
                    first_batch_ordinal=len(jobs),
                )
            )
        jobs_by_execution[execution.id] = jobs
    return _coverage_operations(
        effects=bound.program.program.effects,
        local_effects=scheduled_local_effects,
        regions=compile_regions,
        jobs_by_execution=jobs_by_execution,
    )


def _coverage_operations(
    *,
    effects: tuple[LogicalEffect, ...],
    local_effects: MaterializedLocalEffects | None,
    regions: tuple[tuple[int, ...], ...],
    jobs_by_execution: dict[str, list[RunDomainJob]],
) -> tuple[RunCoveredOperation, ...]:
    selected_compute = () if local_effects is None else local_effects.compute_operations
    selected_effects = () if local_effects is None else local_effects.effect_operations
    operations: list[RunCoveredOperation] = []
    for region in regions:
        operations.extend(
            effect for effect in selected_compute if effect.point_index in region
        )
        for effect_index, effect in enumerate(effects):
            if local_effects is not None:
                operations.extend(
                    item
                    for item in selected_effects[effect_index]
                    if item.point_index in region
                )
            if isinstance(effect, LogicalDomainExecution):
                operations.extend(
                    job
                    for job in jobs_by_execution.get(effect.id, ())
                    if job.point_ordinals[0] in region
                )
        for ordinal in region:
            operations.append(RunCoverageCheckpoint(ordinal))
    return tuple(operations)


def _stable_host_regions(
    region: tuple[int, ...],
    local_effects: MaterializedLocalEffects | None,
) -> tuple[tuple[int, ...], ...]:
    """Group adjacent points that require the same static host state frame.

    Pure host computation does not delimit a real-time batch. Static state is
    idempotent and can be reconciled once at the start of a stable region.
    Invocations, acquisitions, and state backed by point-local payloads remain
    hard point boundaries because repeating or reordering them changes meaning.
    """

    selected: list[tuple[int, ...]] = []
    start = 0
    previous_frame: tuple[tuple[ApplyStateOperation, ...], ...] | None = None
    for offset, ordinal in enumerate(region):
        frame = _static_state_frame(local_effects, ordinal)
        changed = frame is None or previous_frame is None or frame != previous_frame
        if offset and changed:
            selected.append(region[start:offset])
            start = offset
        previous_frame = frame
    selected.append(region[start:])
    return tuple(selected)


def _static_state_frame(
    local_effects: MaterializedLocalEffects | None,
    point_index: int,
) -> tuple[tuple[ApplyStateOperation, ...], ...] | None:
    """Return the comparable state frame for one point, or a hard boundary."""

    if local_effects is None:
        return ()
    frame: list[tuple[ApplyStateOperation, ...]] = []
    for group in local_effects.effect_operations:
        operations: list[ApplyStateOperation] = []
        for covered in group:
            if covered.point_index != point_index:
                continue
            operation = covered.operation
            if not isinstance(operation, ApplyStateOperation):
                return None
            if any(
                isinstance(target.value.root, PayloadRef)
                for target in operation.targets
            ):
                return None
            operations.append(replace(operation, operation_id=""))
        frame.append(tuple(operations))
    return tuple(frame)


def _coalesce_host_state(
    local_effects: MaterializedLocalEffects | None,
    regions: tuple[tuple[int, ...], ...],
) -> MaterializedLocalEffects | None:
    """Keep one materialized static-state frame at each stable region anchor."""

    if local_effects is None:
        return None
    anchors = {region[0] for region in regions}
    return MaterializedLocalEffects(
        compute_operations=local_effects.compute_operations,
        effect_operations=tuple(
            tuple(effect for effect in group if effect.point_index in anchors)
            for group in local_effects.effect_operations
        ),
    )


def _compile_domain_batches(
    compiler: DomainCompiler,
    call: DomainCallView,
    bound_points: MaterializedBoundPoints,
    point_ordinals: tuple[int, ...],
    *,
    first_batch_ordinal: int = 0,
) -> tuple[RunDomainJob, ...]:
    complete_request = make_domain_compile_request(
        call,
        bound_points,
        point_ordinals,
    )
    partition = compiler.partition(complete_request)
    if sum(partition.batch_sizes) != len(point_ordinals):
        raise ValueError(
            "domain compiler partition must cover every bounded point exactly once"
        )
    jobs: list[RunDomainJob] = []
    offset = 0
    for local_batch_ordinal, batch_size in enumerate(partition.batch_sizes):
        batch_ordinal = first_batch_ordinal + local_batch_ordinal
        batch_points = point_ordinals[offset : offset + batch_size]
        offset += batch_size
        request = make_domain_batch_request(
            call,
            bound_points,
            batch_points,
            batch_ordinal=batch_ordinal,
        )
        execution_candidate = cast(
            "object",
            compiler.compile_batch(request),
        )
        if not isinstance(execution_candidate, PreparedDomainExecution):
            raise TypeError(
                "domain compiler compile_batch must return PreparedDomainExecution"
            )

        jobs.append(
            RunDomainJob(
                id=f"{call.id}:batch-{batch_ordinal}",
                point_ordinals=batch_points,
                execution=execution_candidate,
            )
        )
    return tuple(jobs)


def _implementation_problems(
    *,
    has_domain_call: bool,
    has_domain_compiler: bool,
    local_instrument_required: bool,
    domain_instrument_required: bool,
    has_local_instrument_catalog: bool,
) -> tuple[Problem, ...]:
    """Report missing effect/dataflow implementations directly from typed edges."""

    problems: list[Problem] = []
    if has_domain_call and not has_domain_compiler:
        problems.append(
            _planning_problem(
                "domain_compiler_missing",
                "the typed domain call has no configured compiler",
            )
        )
    if local_instrument_required and not has_local_instrument_catalog:
        problems.append(
            _planning_problem(
                "local_instrument_catalog_missing",
                "local effects or products require an instrument contract catalog",
            )
        )
    if domain_instrument_required and not has_local_instrument_catalog:
        problems.append(
            _planning_problem(
                "domain_instrument_catalog_missing",
                "domain execution instruments require an instrument contract catalog",
            )
        )
    return tuple(problems)


def _planning_problem(
    code: str,
    message: str,
    *,
    details: dict[str, object] | None = None,
) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.PLANNING,
        location=model_location("experiment_system"),
        details=details or {},
    )
