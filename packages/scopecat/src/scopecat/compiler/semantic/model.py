"""Backend-neutral typed value and pure-operation graph."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import cast

from scopecat.compiler.relations.analysis import (
    PlanReferenceKind,
)
from scopecat.compiler.relations.model import (
    RelationExpr,
    ScalarExpr,
    SeriesExpr,
)
from scopecat.compiler.relations.verification import (
    ExternalRowInterface,
    TypedPlanImport,
    VerifiedRelationPlan,
)
from scopecat.compiler.semantic.operation_contract import (
    OperationContract,
)
from scopecat.domain.program import DomainProgramDef
from scopecat.kernel.frozen import FrozenMapping, freeze_json_mapping
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.product_identity import ProductId
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import ValueType
from scopecat.measurements.semantics import (
    MeasurementTransformSemanticContract,
)
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity as QuantityValue

type PlanExpression = ScalarExpr | SeriesExpr | RelationExpr
type VerifiedPlanExpression = VerifiedRelationPlan[PlanExpression]
type SemanticValueType = ValueType


def _empty_metadata() -> FrozenMapping[str, JsonValue]:
    return FrozenMapping()


@dataclass(frozen=True, slots=True)
class AcquireId:
    """Nominal identity in the acquisition-effect symbol space."""

    symbol: SymbolId

    @property
    def qualified_name(self) -> str:
        return self.symbol.qualified_name

    def prefixed(self, *scope: str) -> AcquireId:
        return AcquireId(self.symbol.prefixed(*scope))


@dataclass(frozen=True, slots=True)
class OperationId:
    """Nominal identity in the semantic-operation symbol space."""

    symbol: SymbolId

    @property
    def qualified_name(self) -> str:
        return self.symbol.qualified_name

    @property
    def scope(self) -> tuple[str, ...]:
        return self.symbol.scope

    @property
    def local_id(self) -> str:
        return self.symbol.local_id

    def prefixed(self, *scope: str) -> OperationId:
        return OperationId(self.symbol.prefixed(*scope))


@dataclass(frozen=True, slots=True)
class MeasurementTransformId:
    """Nominal identity in the authored measurement-transform symbol space."""

    symbol: SymbolId

    @property
    def qualified_name(self) -> str:
        return self.symbol.qualified_name

    @property
    def scope(self) -> tuple[str, ...]:
        return self.symbol.scope

    @property
    def local_id(self) -> str:
        return self.symbol.local_id

    def prefixed(self, *scope: str) -> MeasurementTransformId:
        return MeasurementTransformId(self.symbol.prefixed(*scope))


@dataclass(frozen=True, slots=True)
class ValueId:
    """Nominal identity in the semantic-value symbol space."""

    symbol: SymbolId

    @property
    def qualified_name(self) -> str:
        return self.symbol.qualified_name

    @property
    def scope(self) -> tuple[str, ...]:
        return self.symbol.scope

    @property
    def local_id(self) -> str:
        return self.symbol.local_id

    def prefixed(self, *scope: str) -> ValueId:
        return ValueId(self.symbol.prefixed(*scope))


def operation_result_id(operation_id: OperationId) -> ValueId:
    return ValueId(
        SymbolId(
            scope=(*operation_id.scope, operation_id.local_id, "outputs"),
            local_id="result",
        )
    )


@dataclass(frozen=True, slots=True, init=False)
class PlanExpressionSource:
    _expression: PlanExpression = field(hash=False, repr=False)
    _certified_type: ValueType
    _imports: tuple[TypedPlanImport, ...] = field(hash=False, repr=False)
    # The verified plan is excluded from comparison, so retain its row interface
    # to distinguish sources with different external requirements.
    _row_interface: ExternalRowInterface = field(hash=False, repr=False)
    _verified_plan: VerifiedPlanExpression = field(
        hash=False,
        repr=False,
        compare=False,
    )

    def __init__(
        self,
        verified_plan: VerifiedPlanExpression,
    ) -> None:
        object.__setattr__(self, "_expression", verified_plan.root)
        object.__setattr__(self, "_certified_type", verified_plan.certified_type)
        object.__setattr__(self, "_imports", verified_plan.imports)
        object.__setattr__(self, "_row_interface", verified_plan.external_row_interface)
        object.__setattr__(self, "_verified_plan", verified_plan)

    @property
    def expression(self) -> PlanExpression:
        """Return a defensive copy of the retained plan semantics."""

        return deepcopy(self._expression)

    @property
    def source_inputs(self) -> tuple[str, ...]:
        """Return input dependencies derived from the retained expression."""

        return self._verified_plan.references.ids(
            PlanReferenceKind.INPUT_SCALAR,
            PlanReferenceKind.INPUT_SERIES,
            PlanReferenceKind.INPUT_TABLE,
        )

    @property
    def certified_type(self) -> ValueType:
        return self._certified_type

    @property
    def imports(self) -> tuple[TypedPlanImport, ...]:
        return self._imports

    @property
    def verified_plan(self) -> VerifiedPlanExpression:
        return self._verified_plan


@dataclass(frozen=True, slots=True, init=False)
class LiteralValueSource:
    """A closed scalar captured by value at semantic elaboration time."""

    _value: object = field(hash=False, repr=False)

    def __init__(self, value: object) -> None:
        object.__setattr__(self, "_value", _snapshot_literal(value))

    @property
    def value(self) -> object:
        """Return a defensive copy of the retained literal."""

        return _snapshot_literal(self._value)


type ValueSource = PlanExpressionSource | LiteralValueSource


@dataclass(frozen=True, slots=True)
class ValueDef:
    """One plan-available value; operation results live on their operation."""

    id: ValueId
    value_type: SemanticValueType
    source: ValueSource


@dataclass(frozen=True, slots=True)
class ValueUse:
    """A use contains only the identity of its target definition."""

    value_id: ValueId


@dataclass(frozen=True, slots=True)
class SemanticOperation:
    id: OperationId
    contract: OperationContract
    inputs: tuple[tuple[str, ValueUse], ...]
    result_id: ValueId
    result_type: SemanticValueType

    def __post_init__(self) -> None:
        _require_unique_names("operation input", self.inputs)


@dataclass(frozen=True, slots=True)
class SemanticDomainExecution:
    """One program and its plan-stage logical product bindings."""

    id: str
    program: DomainProgramDef
    inputs: tuple[tuple[str, ValueUse], ...] = ()
    compiler_inputs: tuple[tuple[str, ValueUse], ...] = ()
    results: tuple[tuple[str, ProductId], ...] = ()
    resources: tuple[tuple[str, LogicalResourcePortId], ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("semantic domain execution id must be non-empty")
        _require_unique_names("domain execution input", self.inputs)
        _require_unique_names("domain execution compiler input", self.compiler_inputs)
        _require_unique_names("domain execution result", self.results)
        _require_unique_names("domain execution resource", self.resources)


@dataclass(frozen=True, slots=True)
class SemanticMeasurementTransform:
    """One pure authored transform with explicit logical-product edges."""

    id: MeasurementTransformId
    semantic: MeasurementTransformSemanticContract
    inputs: tuple[tuple[str, ProductId], ...] = ()
    outputs: tuple[tuple[str, ProductId], ...] = ()

    def __post_init__(self) -> None:
        _require_unique_names("measurement transform input", self.inputs)
        _require_unique_names("measurement transform output", self.outputs)
        if not self.outputs:
            msg = "semantic measurement transforms require at least one output"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class AcquireProduct:
    """Provider-facing mapping for one product in an acquisition effect."""

    product_id: ProductId
    provider_key: str
    metadata: Mapping[str, JsonValue] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        if not self.provider_key:
            raise ValueError("acquired product provider key must be non-empty")
        object.__setattr__(
            self,
            "metadata",
            freeze_json_mapping(
                self.metadata,
                path=f"acquired product {self.product_id.qualified_name!r} metadata",
            ),
        )


@dataclass(frozen=True, slots=True)
class AcquireEffect:
    """Ordered acquisition through one logical resource capability."""

    id: AcquireId
    resource_port_id: LogicalResourcePortId
    capability_id: str
    products: tuple[AcquireProduct, ...]

    def __post_init__(self) -> None:
        if not self.products:
            raise ValueError("acquire effects require at least one product")
        if not self.capability_id:
            raise ValueError("acquire effect capability must be non-empty")
        if len(self.product_ids) != len(set(self.product_ids)):
            raise ValueError("acquire effect product ids must be unique")
        provider_keys = tuple(product.provider_key for product in self.products)
        if len(provider_keys) != len(set(provider_keys)):
            raise ValueError("acquire effect provider keys must be unique")

    @property
    def product_ids(self) -> tuple[ProductId, ...]:
        return tuple(product.product_id for product in self.products)


@dataclass(frozen=True, slots=True)
class SemanticGraphIR:
    value_defs: tuple[ValueDef, ...] = ()
    operations: tuple[SemanticOperation, ...] = ()
    measurement_transforms: tuple[SemanticMeasurementTransform, ...] = ()


@dataclass(frozen=True, slots=True)
class ImplementationId:
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            msg = "implementation ids must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class LocalPythonImplementation:
    id: ImplementationId
    kernel: Callable[..., object] = field(repr=False, compare=False)


def _snapshot_literal(value: object) -> object:
    """Snapshot closed data without cloning opaque runtime payload bodies."""

    if isinstance(value, PayloadValue):
        return value
    if isinstance(value, EntityRef | QuantityValue):
        return value.model_copy(deep=True)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        return {
            key: _snapshot_literal(nested_value)
            for key, nested_value in mapping.items()
        }
    if isinstance(value, list):
        items = cast("list[object]", value)
        return [_snapshot_literal(item) for item in items]
    if isinstance(value, tuple):
        items = cast("tuple[object, ...]", value)
        return tuple(_snapshot_literal(item) for item in items)
    # Unknown objects belong to the opaque payload/implementation boundary.
    # Their identity is semantic data; attempting a generic deepcopy would make
    # construction depend on incidental handle internals such as locks/devices.
    return value


def _require_unique_names(label: str, values: tuple[tuple[str, object], ...]) -> None:
    names = tuple(name for name, _value in values)
    if any(not name for name in names):
        msg = f"{label} names must be non-empty"
        raise ValueError(msg)
    duplicates = sorted(name for name in set(names) if names.count(name) > 1)
    if duplicates:
        msg = f"duplicate {label} names: " + ", ".join(duplicates)
        raise ValueError(msg)
