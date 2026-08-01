"""Low-level logical programs and bound facts used only by tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from scopecat.compiler.bind import (
    BoundPlan,
    _make_bound_plan,
)
from scopecat.compiler.bound_facts import (
    BoundMeasurementPostprocessor,
    BoundProgramFacts,
    LogicalResourceRequirement,
)
from scopecat.compiler.bound_verification import verify_bound_facts
from scopecat.compiler.environment import ConfigEnvironment
from scopecat.compiler.frontend.logical_verification import (
    VerifiedLogicalProgram,
)
from scopecat.compiler.parameter_overlays import PointParameterOverlay
from scopecat.compiler.point_domain import PointDomain
from scopecat.compiler.value_resolution import ProgramValue
from scopecat.domain.program import DomainProgramDef
from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.problems import ProblemPhase
from scopecat.kernel.product_identity import (
    ProductId,
    ProductUse,
    ProductUseId,
    product_id,
)
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    logical_resource_port_id,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_data import CellValue
from scopecat.kernel.value_types import Scalar, Table, ValueType
from scopecat.measurements.products import (
    ProductAxisDef,
    ProductDef,
)
from scopecat.measurements.records import RecordUse
from scopecat.measurements.results import MeasurementDType
from scopecat.program.expressions import (
    ComputeResultScalarExpr,
    ScalarExpr,
)
from scopecat.program.logical import (
    AcquireEffect,
    AcquireId,
    AcquireResult,
    LocalPythonImplementation,
    LogicalComputeNode,
    LogicalDomainExecution,
    LogicalInvocation,
    LogicalInvocationArgument,
    LogicalProgram,
    LogicalStateAssignment,
    ValueDef,
)
from scopecat.program.value_graph import (
    ComputeOutput,
    OperationId,
    ValueId,
    operation_result_id,
)


@dataclass(frozen=True, slots=True)
class StateAssignmentFixture:
    port_id: LogicalResourcePortId
    interface_id: InterfaceId
    property_id: str
    value: ScalarExpr
    component_path: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ComputeNodeFixture:
    id: OperationId
    implementation: LocalPythonImplementation
    result: ComputeOutput
    input_types: Mapping[str, Scalar]
    inputs: Mapping[str, ScalarExpr] = field(
        default_factory=lambda: dict[str, ScalarExpr]()
    )


@dataclass(frozen=True, slots=True)
class InvocationFixture:
    id: str
    port_id: LogicalResourcePortId
    interface_id: InterfaceId
    operation_id: str
    arguments: Mapping[str, ScalarExpr]
    component_path: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DomainResultFixture:
    id: str
    product_id: ProductId
    product_use_ids: tuple[ProductUseId, ...] = ()


@dataclass(frozen=True, slots=True)
class DomainExecutionFixture:
    id: str
    program: DomainProgramDef
    inputs: Mapping[str, ScalarExpr] = field(
        default_factory=lambda: dict[str, ScalarExpr]()
    )
    compiler_inputs: Mapping[str, ProgramValue] = field(
        default_factory=lambda: dict[str, ProgramValue]()
    )
    results: tuple[DomainResultFixture, ...] = ()


@dataclass(frozen=True, slots=True)
class ProgramFixture:
    logical: VerifiedLogicalProgram
    bindings: BoundProgramFacts


type EffectFixture = (
    StateAssignmentFixture | InvocationFixture | DomainExecutionFixture | AcquireEffect
)


def overlay_parameter_cell(
    table_id: str,
    *,
    row_index: int,
    key: dict[str, CellValue],
    column_id: str,
    axis_id: str,
    value_type: Scalar,
) -> PointParameterOverlay:
    """Build one statically bound point-local cell overlay."""

    return PointParameterOverlay(
        table_id=table_id,
        row_index=row_index,
        key=key,
        column_id=column_id,
        axis_id=axis_id,
        value_type=value_type,
    )


def compute_result(
    value: ValueId | OperationId | str,
    *,
    value_type: Scalar,
) -> ComputeResultScalarExpr:
    """Reference an exact output or one operation's current single result."""

    if isinstance(value, ValueId):
        selected = value
    else:
        operation_id = (
            value
            if isinstance(value, OperationId)
            else OperationId(SymbolId(local_id=value))
        )
        selected = operation_result_id(operation_id)
    return ComputeResultScalarExpr(value_id=selected, value_type=value_type)


def observable_product(
    id: str | ProductId,
    *,
    unit: str | None = None,
    dtype: MeasurementDType = "float64",
    axes: Sequence[ProductAxisDef] = (),
    metadata: dict[str, JsonValue] | None = None,
) -> ProductDef:
    return ProductDef(
        id=id if isinstance(id, ProductId) else product_id(id),
        unit=unit,
        dtype=dtype,
        axes=tuple(axes),
        metadata=metadata or {},
    )


def instrument_acquisition(
    product: ProductDef | ProductId,
    *,
    id: AcquireId | str | None = None,
    resource_port_id: LogicalResourcePortId | str = "source",
    interface: str,
    acquisition: str = "sample",
    component_path: Sequence[str] = (),
    result_id: str | None = None,
    metadata: dict[str, JsonValue] | None = None,
) -> AcquireEffect:
    """Build one explicit, single-product instrument acquisition."""

    selected_product_id = product.id if isinstance(product, ProductDef) else product
    if id is None:
        selected_acquire_id = AcquireId(
            SymbolId(
                scope=selected_product_id.scope,
                local_id=f"acquire-{selected_product_id.local_id}",
            )
        )
    elif isinstance(id, AcquireId):
        selected_acquire_id = id
    else:
        selected_acquire_id = AcquireId(SymbolId(local_id=id))
    selected_resource_port_id = (
        resource_port_id
        if isinstance(resource_port_id, LogicalResourcePortId)
        else logical_resource_port_id(resource_port_id)
    )
    return AcquireEffect(
        id=selected_acquire_id,
        resource_port_id=selected_resource_port_id,
        interface_id=interface,
        component_path=tuple(component_path),
        acquisition_id=acquisition,
        results=(
            AcquireResult(
                product_id=selected_product_id,
                result_id=result_id or selected_product_id.local_id,
                metadata=dict(metadata or {}),
            ),
        ),
    )


def instrument_acquisitions(
    *products: ProductDef | ProductId,
    resource_port_id: LogicalResourcePortId | str = "source",
    interface: str,
    acquisition: str = "sample",
) -> tuple[AcquireEffect, ...]:
    """Build one independently identified acquisition per logical product."""

    return tuple(
        instrument_acquisition(
            product,
            resource_port_id=resource_port_id,
            interface=interface,
            acquisition=acquisition,
        )
        for product in products
    )


def instrument_invocation(
    *,
    id: str,
    resource_port_id: LogicalResourcePortId | str,
    interface: str,
    operation: str,
    arguments: Mapping[str, ScalarExpr] | None = None,
    component_path: Sequence[str] = (),
) -> InvocationFixture:
    """Build one ordered atomic instrument invocation."""

    return InvocationFixture(
        id=id,
        port_id=(
            resource_port_id
            if isinstance(resource_port_id, LogicalResourcePortId)
            else logical_resource_port_id(resource_port_id)
        ),
        interface_id=interface,
        component_path=tuple(component_path),
        operation_id=operation,
        arguments=dict(arguments or {}),
    )


def program_fixture(
    *,
    point_domain: PointDomain,
    resource_requirements: Sequence[LogicalResourceRequirement] = (),
    parameter_overlays: Sequence[PointParameterOverlay] = (),
    compute_nodes: Sequence[ComputeNodeFixture] = (),
    domain_execution: DomainExecutionFixture | None = None,
    measurement_postprocessors: Sequence[BoundMeasurementPostprocessor] = (),
    state: Sequence[StateAssignmentFixture] = (),
    invocations: Sequence[InvocationFixture] = (),
    product_defs: Sequence[ProductDef] = (),
    instrument_acquisitions: Sequence[AcquireEffect] = (),
    product_uses: Sequence[ProductUse] = (),
    record_uses: Sequence[RecordUse] = (),
    effects: Sequence[EffectFixture] | None = None,
) -> ProgramFixture:
    """Build canonical logical semantics plus explicit config-derived facts."""

    value_defs: list[ValueDef] = []
    scalar_values: dict[ValueId, ScalarExpr] = {}
    next_value = 0

    def register(
        value: ProgramValue,
        role: str,
        *,
        value_type: ValueType | None = None,
    ) -> ValueId:
        nonlocal next_value
        if isinstance(value, ComputeResultScalarExpr):
            return value.value_id
        value_id = ValueId(SymbolId(local_id=f"{role}-{next_value}"))
        next_value += 1
        if isinstance(value, ScalarExpr):
            scalar = value
            scalar_values[value_id] = scalar
            value_defs.append(
                ValueDef(id=value_id, value_type=scalar.value_type, source=scalar)
            )
        else:
            if not isinstance(value_type, Table):
                raise AssertionError("table test input requires its declared type")
            value_defs.append(
                ValueDef(
                    id=value_id,
                    value_type=value_type,
                    source=value,
                )
            )
        return value_id

    logical_compute_nodes = tuple(
        LogicalComputeNode(
            id=node.id,
            inputs=tuple(
                (name, register(value, f"compute-{node.id.local_id}-{name}"))
                for name, value in node.inputs.items()
            ),
            input_types=tuple(node.input_types.items()),
            result_id=node.result.id,
            result_type=node.result.value_type,
        )
        for node in compute_nodes
    )
    implementations: dict[OperationId, LocalPythonImplementation] = {
        node.id: node.implementation for node in compute_nodes
    }
    selected_effects = tuple(effects) if effects is not None else None
    selected_state = (
        tuple(
            item
            for item in selected_effects
            if isinstance(item, StateAssignmentFixture)
        )
        if selected_effects is not None
        else tuple(state)
    )
    selected_invocations = (
        tuple(item for item in selected_effects if isinstance(item, InvocationFixture))
        if selected_effects is not None
        else tuple(invocations)
    )
    selected_domains = (
        tuple(
            item
            for item in selected_effects
            if isinstance(item, DomainExecutionFixture)
        )
        if selected_effects is not None
        else (() if domain_execution is None else (domain_execution,))
    )
    selected_acquisitions = (
        tuple(item for item in selected_effects if isinstance(item, AcquireEffect))
        if selected_effects is not None
        else tuple(instrument_acquisitions)
    )
    logical_state = tuple(
        LogicalStateAssignment(
            port_id=assignment.port_id,
            interface_id=assignment.interface_id,
            component_path=assignment.component_path,
            property_id=assignment.property_id,
            value_id=register(assignment.value, f"state-{index}"),
        )
        for index, assignment in enumerate(selected_state)
    )
    logical_invocations = tuple(
        LogicalInvocation(
            id=invocation.id,
            port_id=invocation.port_id,
            interface_id=invocation.interface_id,
            component_path=invocation.component_path,
            operation_id=invocation.operation_id,
            arguments=tuple(
                LogicalInvocationArgument(
                    id=argument_id,
                    value_id=register(
                        value,
                        f"invocation-{invocation.id}-{argument_id}",
                    ),
                )
                for argument_id, value in invocation.arguments.items()
            ),
        )
        for invocation in selected_invocations
    )
    logical_domain = tuple(
        LogicalDomainExecution(
            id=domain_execution.id,
            program=domain_execution.program,
            inputs=tuple(
                (name, register(value, f"domain-{name}"))
                for name, value in domain_execution.inputs.items()
            ),
            compiler_inputs=tuple(
                (
                    name,
                    register(
                        value,
                        f"domain-compiler-{name}",
                        value_type={
                            port.id: port.value_type
                            for port in domain_execution.program.compiler_input_ports
                        }[name],
                    ),
                )
                for name, value in domain_execution.compiler_inputs.items()
            ),
            results=tuple(
                (result.id, result.product_id) for result in domain_execution.results
            ),
        )
        for domain_execution in selected_domains
    )
    lowered_effects_by_id = {
        **{
            id(source): lowered
            for source, lowered in zip(selected_state, logical_state, strict=True)
        },
        **{
            id(source): lowered
            for source, lowered in zip(
                selected_invocations,
                logical_invocations,
                strict=True,
            )
        },
        **{
            id(source): lowered
            for source, lowered in zip(selected_domains, logical_domain, strict=True)
        },
        **{id(source): source for source in selected_acquisitions},
    }
    logical_effects = (
        tuple(lowered_effects_by_id[id(effect)] for effect in selected_effects)
        if selected_effects is not None
        else (
            *logical_state,
            *logical_invocations,
            *logical_domain,
            *selected_acquisitions,
        )
    )
    logical = VerifiedLogicalProgram(
        program=LogicalProgram(
            experiment_id="test.bound-program",
            kind="test",
            value_defs=tuple(value_defs),
            compute_nodes=logical_compute_nodes,
            implementations=implementations,
            effects=logical_effects,
        ),
        product_declarations={},
        scalar_values=scalar_values,
    )
    bindings = BoundProgramFacts(
        point_domain=point_domain,
        resource_requirements=tuple(resource_requirements),
        parameter_overlays=tuple(parameter_overlays),
        live_compute_ids=frozenset(node.id for node in compute_nodes),
        domain_result_use_ids={
            (execution.id, result.id): result.product_use_ids
            for execution in selected_domains
            for result in execution.results
        },
        measurement_postprocessors=tuple(measurement_postprocessors),
        product_defs=tuple(product_defs),
        product_uses=tuple(product_uses),
        record_uses=tuple(record_uses),
    )
    return ProgramFixture(logical=logical, bindings=bindings)


def bind_program_facts(
    program: ProgramFixture,
    environment: ConfigEnvironment,
    *,
    experiment_id: str = "test.bound-program",
    kind: str = "test",
) -> BoundPlan:
    """Bind trusted low-level facts to a minimal verified source for tests."""

    return _make_bound_plan(
        verified_logical_program_for(
            program,
            experiment_id=experiment_id,
            kind=kind,
        ),
        program.bindings,
        verify_bound_facts(
            program.logical,
            program.bindings,
            program_id=experiment_id,
            phase=ProblemPhase.PLANNING,
        ),
        environment,
    )


def verified_logical_program_for(
    program: ProgramFixture,
    *,
    experiment_id: str = "test.bound-program",
    kind: str = "test",
) -> VerifiedLogicalProgram:
    """Build the minimal canonical source needed by a low-level fact fixture."""

    if program.logical.experiment_id == experiment_id and program.logical.kind == kind:
        return program.logical
    return VerifiedLogicalProgram(
        program=replace(
            program.logical.program,
            experiment_id=experiment_id,
            kind=kind,
        ),
        product_declarations=program.logical.product_declarations,
        scalar_values=program.logical.scalar_values,
    )
