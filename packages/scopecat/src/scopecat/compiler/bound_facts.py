"""Configuration-derived facts attached to a verified logical program.

The logical program remains the sole owner of operations and effect order.
These records contain only values and selections introduced by configuration
binding; planning combines them with ``VerifiedLogicalProgram`` instead of
consuming a second copied program.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from scopecat.compiler.parameter_overlays import PointParameterOverlay
from scopecat.compiler.point_domain import PointDomain
from scopecat.kernel.graph_identity import ValueId
from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.product_identity import (
    ProductId,
    ProductUse,
    ProductUseId,
    product_use,
)
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
)
from scopecat.measurements.postprocessor_contract import (
    MeasurementPostprocessorKernel,
)
from scopecat.measurements.products import (
    ProductAxisDef,
    ProductDef,
)
from scopecat.measurements.records import BoundRecordUse, RecordUse, ValueRecordUse
from scopecat.measurements.results import MeasurementVariableRole
from scopecat.program.expressions import ScalarExpr
from scopecat.program.logical import (
    MeasurementPostprocessorId,
)
from scopecat.program.value_graph import OperationId


def _empty_value_overrides() -> dict[ValueId, ScalarExpr]:
    return {}


def _empty_domain_result_use_ids() -> dict[tuple[str, str], tuple[ProductUseId, ...]]:
    return {}


@dataclass(frozen=True, slots=True)
class BoundMeasurementPostprocessorOutput:
    """One calculated product and all of its downstream use slots."""

    id: str
    product_id: ProductId
    product_use_ids: tuple[ProductUseId, ...] = ()


@dataclass(frozen=True, slots=True)
class BoundMeasurementPostprocessor:
    """One live point-local postprocessor retained by record demand."""

    id: MeasurementPostprocessorId
    input_product_id: ProductId
    input_product_use_id: ProductUseId
    outputs: tuple[BoundMeasurementPostprocessorOutput, ...]
    kernel: MeasurementPostprocessorKernel = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class LogicalResourceRequirement:
    """Stable logical interfaces plus point-local object selection.

    ``interfaces`` is the compile-time contract for the logical port, while
    ``entity_uses`` selects its objects at each point. Physical instrument and
    channel identity enter only during target materialization.
    """

    port_id: LogicalResourcePortId
    interfaces: tuple[InterfaceId, ...] = ()
    entity_uses: tuple[ScalarExpr, ...] = ()


@dataclass(frozen=True, slots=True)
class BoundProgramFacts:
    """Facts introduced by binding one canonical logical program."""

    point_domain: PointDomain
    value_overrides: Mapping[ValueId, ScalarExpr] = field(
        default_factory=_empty_value_overrides
    )
    resource_requirements: tuple[LogicalResourceRequirement, ...] = ()
    parameter_overlays: tuple[PointParameterOverlay, ...] = ()
    live_compute_ids: frozenset[OperationId] = frozenset()
    domain_result_use_ids: Mapping[tuple[str, str], tuple[ProductUseId, ...]] = field(
        default_factory=_empty_domain_result_use_ids
    )
    measurement_postprocessors: tuple[BoundMeasurementPostprocessor, ...] = ()
    product_defs: tuple[ProductDef, ...] = ()
    product_uses: tuple[ProductUse, ...] = ()
    record_uses: tuple[BoundRecordUse, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "value_overrides", dict(self.value_overrides))
        object.__setattr__(
            self,
            "domain_result_use_ids",
            dict(self.domain_result_use_ids),
        )

    @property
    def product_record_uses(self) -> tuple[RecordUse, ...]:
        return tuple(
            record for record in self.record_uses if isinstance(record, RecordUse)
        )

    @property
    def value_record_uses(self) -> tuple[ValueRecordUse, ...]:
        return tuple(
            record for record in self.record_uses if isinstance(record, ValueRecordUse)
        )


def product_axis(
    id: str,
    *,
    dimension_id: str,
    dimension_label: str | None = None,
    size: int,
    kind: str | None = None,
    unit: str | None = None,
    metadata: Mapping[str, JsonValue] | None = None,
) -> ProductAxisDef:
    return ProductAxisDef(
        id=id,
        dimension_id=dimension_id,
        dimension_label=dimension_label,
        kind=kind or id,
        size=size,
        unit=unit,
        metadata=metadata or {},
    )


def shot_axis(size: int, *, dimension_id: str) -> ProductAxisDef:
    return product_axis(
        "shot",
        dimension_id=dimension_id,
        size=size,
        kind="shot",
        unit="count",
    )


def record_product(
    product: ProductDef | ProductId,
    *,
    record_id: str | None = None,
    role: MeasurementVariableRole = "observable",
    recording_group_id: str | None = None,
    metadata: Mapping[str, JsonValue] | None = None,
) -> tuple[ProductUse, RecordUse]:
    """Create one product-use occurrence and one durable record consumer."""

    selected_id = product.id if isinstance(product, ProductDef) else product
    use = product_use(selected_id)
    return use, RecordUse(
        id=record_id or selected_id.qualified_name,
        product_use_id=use.id,
        role=role,
        recording_group_id=recording_group_id,
        metadata=metadata or {},
    )
