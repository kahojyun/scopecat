"""Low-level compiler program builders used only by tests."""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy

from scopecat.compiler.frontend.environment import ValidatedConfigEnvironment
from scopecat.compiler.linking.linked import (
    LinkedPlan,
    link_verified_program,
)
from scopecat.compiler.relations.model import ScalarExpr, as_scalar_expr
from scopecat.compiler.relations.uses import relation_use
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.semantic.model import (
    AcquireId,
    ImplementationCatalog,
    OperationId,
    ValueId,
    operation_result_id,
)
from scopecat.compiler.semantic.value_expressions import verify_scalar_value_expr
from scopecat.compiler.typed.action import ActionSpec
from scopecat.compiler.typed.parameter_overlays import PointParameterOverlay
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.products import (
    ProductAxisDef,
    ProductDef,
)
from scopecat.compiler.typed.program import (
    AcquireProductSpec,
    AcquireSpec,
    CoreProgram,
    LogicalResourceRequirement,
    TypedComputeNode,
    TypedDomainExecution,
    TypedMeasurementTransform,
    product_output,
)
from scopecat.compiler.typed.records import RecordUse
from scopecat.compiler.typed.state import StateSpecVariant
from scopecat.compiler.typed.verification import seal_typed_program
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.problems import (
    ProblemPhase,
    has_blocking_problems,
)
from scopecat.kernel.product_identity import (
    ProductId,
    ProductUse,
)
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    logical_resource_port_id,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Scalar
from scopecat.measurements.results import MeasurementDType


def overlay_parameter_cell(
    table_id: str,
    *,
    key: dict[str, object],
    key_types: dict[str, Scalar],
    column_id: str,
    value: object,
    value_type: Scalar,
    bindings: RelationTypeBindings,
) -> PointParameterOverlay:
    """Build a typed point-local cell overlay."""

    if set(key) != set(key_types):
        msg = "parameter overlay key and key_types must contain the same columns"
        raise ValueError(msg)
    return PointParameterOverlay(
        table_id=table_id,
        key_uses={
            name: relation_use(
                verify_scalar_value_expr(
                    _require_scalar_expression(expression),
                    bindings=bindings,
                    expected_type=key_types[name],
                )
            )
            for name, expression in key.items()
        },
        column_id=column_id,
        value_use=relation_use(
            verify_scalar_value_expr(
                _require_scalar_expression(value),
                bindings=bindings,
                expected_type=value_type,
            )
        ),
    )


def compute_result(value: ValueId | OperationId | str) -> ComputeResultRef:
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
    return ComputeResultRef(value_id=selected)


def observable_product(
    id: str | ProductId,  # noqa: A002
    *,
    unit: str | None = None,
    dtype: MeasurementDType = "float64",
    axes: Sequence[ProductAxisDef] = (),
    metadata: dict[str, JsonValue] | None = None,
) -> ProductDef:
    return product_output(
        id,
        kind="observable",
        unit=unit,
        dtype=dtype,
        axes=axes,
        metadata=metadata,
    )


def instrument_acquisition(
    product: ProductDef | ProductId,
    *,
    id: AcquireId | str | None = None,  # noqa: A002
    resource_port_id: LogicalResourcePortId | str = "source",
    capability: str,
    provider_key: str | None = None,
    metadata: dict[str, JsonValue] | None = None,
) -> AcquireSpec:
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
    return AcquireSpec(
        id=selected_acquire_id,
        resource_port_id=selected_resource_port_id,
        capability_id=capability,
        products=(
            AcquireProductSpec(
                product_id=selected_product_id,
                provider_key=provider_key or selected_product_id.local_id,
                metadata=dict(metadata or {}),
            ),
        ),
    )


def instrument_acquisitions(
    *products: ProductDef | ProductId,
    resource_port_id: LogicalResourcePortId | str = "source",
    capability: str,
) -> tuple[AcquireSpec, ...]:
    """Build one independently identified acquisition per logical product."""

    return tuple(
        instrument_acquisition(
            product,
            resource_port_id=resource_port_id,
            capability=capability,
        )
        for product in products
    )


def typed_program(
    *,
    id: str,  # noqa: A002
    kind: str,
    point_domain: PointDomain,
    resource_requirements: Sequence[LogicalResourceRequirement] = (),
    parameter_overlays: Sequence[PointParameterOverlay] = (),
    compute_nodes: Sequence[TypedComputeNode] = (),
    domain_execution: TypedDomainExecution | None = None,
    measurement_transforms: Sequence[TypedMeasurementTransform] = (),
    implementation_catalog: ImplementationCatalog | None = None,
    state: Sequence[StateSpecVariant] = (),
    actions: Sequence[ActionSpec] = (),
    product_defs: Sequence[ProductDef] = (),
    instrument_acquisitions: Sequence[AcquireSpec] = (),
    product_uses: Sequence[ProductUse] = (),
    record_uses: Sequence[RecordUse] = (),
    metadata: dict[str, JsonValue] | None = None,
) -> CoreProgram:
    """Build one low-level typed program from explicitly ordered components."""

    return CoreProgram(
        id=id,
        kind=kind,
        point_domain=point_domain,
        resource_requirements=tuple(resource_requirements),
        parameter_overlays=tuple(parameter_overlays),
        compute_nodes=tuple(compute_nodes),
        effects=(
            *state,
            *actions,
            *((domain_execution,) if domain_execution is not None else ()),
            *instrument_acquisitions,
        ),
        measurement_transforms=tuple(measurement_transforms),
        implementation_catalog=implementation_catalog or ImplementationCatalog(),
        product_defs=tuple(product_defs),
        product_uses=tuple(product_uses),
        record_uses=tuple(record_uses),
        metadata=dict(metadata or {}),
    )


def link_program(
    program: CoreProgram,
    environment: ValidatedConfigEnvironment,
) -> LinkedPlan:
    """Snapshot, seal, and link an externally constructed test program."""

    try:
        verified_program = seal_typed_program(
            deepcopy(program),
            phase=ProblemPhase.PLANNING,
        )
    except CheckFailed as error:
        problems = [*environment.problems, *error.problems]
        if has_blocking_problems(problems):
            raise CheckFailed(problems) from error
        raise AssertionError(
            "failed program seal produced no blocking problem"
        ) from error
    return link_verified_program(verified_program, environment)


def _require_scalar_expression(value: object) -> ScalarExpr:
    return value if isinstance(value, ScalarExpr) else as_scalar_expr(value)
