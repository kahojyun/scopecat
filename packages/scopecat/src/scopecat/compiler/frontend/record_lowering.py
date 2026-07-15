"""Config-dependent lowering of source record intents."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from scopecat.authoring._record_intents import (
    AxisSizeInput,
    ModuleProductPort,
    ProductSelectionIntent,
    RecordAxisIntent,
    RecordIntent,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_lower_value_ref,
)
from scopecat.authoring.values import MetadataValue
from scopecat.compiler.entity_resolution import (
    EntityResolutionError,
    resolve_entities,
)
from scopecat.compiler.frontend.problems import (
    raise_entity_resolution_problem,
    raise_frontend_problem,
)
from scopecat.compiler.frontend.static_evaluation import StaticRelationEvaluator
from scopecat.compiler.relations.model import (
    RelationExpr,
    ScalarExpr,
    SeriesExpr,
    as_scalar_expr,
)
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.typed.products import (
    InstrumentProductProducer,
    ProductAxisDef,
    ProductDef,
)
from scopecat.compiler.typed.program import product_axis as compiler_product_axis
from scopecat.compiler.typed.records import RecordUse
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.problems import ModelLocation
from scopecat.kernel.product_identity import (
    ProductId,
    ProductProducerId,
    ProductUse,
    ProductUseId,
    product_id,
    product_use,
)
from scopecat.kernel.value_types import Scalar, Series, Table, ValueType
from scopecat.records._run_request_values import normalize_json_value
from scopecat.records.config import Topology
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity

type BindSeriesInputRefs = Callable[[SeriesExpr, Mapping[str, object]], SeriesExpr]
type BindRelationInputRefs = Callable[
    [RelationExpr, Mapping[str, object]], RelationExpr
]
type InputRow = Callable[[Mapping[str, object]], Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class LoweredProductModel:
    """Orthogonal product declarations, producers, uses, and record consumers."""

    product_defs: tuple[ProductDef, ...] = ()
    instrument_product_producers: tuple[InstrumentProductProducer, ...] = ()
    product_uses: tuple[ProductUse, ...] = ()
    record_uses: tuple[RecordUse, ...] = ()


def lower_records(
    static_evaluator: StaticRelationEvaluator,
    topology: Topology,
    record_intents: Sequence[RecordIntent],
    inputs: Mapping[str, object],
    *,
    type_bindings: RelationTypeBindings,
    bind_series_input_refs: BindSeriesInputRefs,
    bind_relation_input_refs: BindRelationInputRefs,
    input_row: InputRow,
) -> LoweredProductModel:
    lowered = tuple(
        _lower_inline_product(
            static_evaluator,
            topology,
            record_intent,
            inputs,
            type_bindings=type_bindings,
            bind_series_input_refs=bind_series_input_refs,
            bind_relation_input_refs=bind_relation_input_refs,
            input_row=input_row,
        )
        for record_intent in record_intents
    )
    products = tuple(product for product, _producer in lowered)
    producers = tuple(producer for _product, producer in lowered)
    uses = tuple(product_use(product.id) for product in products)
    return LoweredProductModel(
        product_defs=products,
        instrument_product_producers=producers,
        product_uses=uses,
        record_uses=tuple(
            RecordUse(id=record.id, product_use_id=use.id)
            for record, use in zip(record_intents, uses, strict=True)
        ),
    )


_EMPTY_PRODUCT_IDS: frozenset[ProductId] = frozenset()


def lower_product_selections(
    static_evaluator: StaticRelationEvaluator,
    topology: Topology,
    selections: Sequence[ProductSelectionIntent],
    product_ports_by_id: Mapping[ProductId, ModuleProductPort],
    inputs: Mapping[str, object],
    *,
    type_bindings: RelationTypeBindings,
    bind_series_input_refs: BindSeriesInputRefs,
    bind_relation_input_refs: BindRelationInputRefs,
    input_row: InputRow,
    non_instrument_product_ids: frozenset[ProductId] = _EMPTY_PRODUCT_IDS,
) -> LoweredProductModel:
    lowered = tuple(
        _lower_product_port(
            static_evaluator,
            topology,
            product,
            inputs,
            type_bindings=type_bindings,
            bind_series_input_refs=bind_series_input_refs,
            bind_relation_input_refs=bind_relation_input_refs,
            input_row=input_row,
        )
        for product in product_ports_by_id.values()
    )
    products = tuple(product for product, _producer in lowered)
    producers = tuple(
        producer
        for product, producer in lowered
        if product.id not in non_instrument_product_ids
    )
    uses: list[ProductUse] = []
    uses_by_id: dict[ProductUseId, ProductUse] = {}
    records: list[RecordUse] = []
    for selection in selections:
        product = product_ports_by_id.get(selection.product_id)
        if product is None:
            raise AssertionError(
                "verified product selection is absent from the product map: "
                f"{selection.product_id.qualified_name}"
            )
        use = selection.product_use
        existing_use = uses_by_id.get(use.id)
        if existing_use is None:
            uses_by_id[use.id] = use
            uses.append(use)
        elif existing_use != use:
            raise AssertionError(
                f"verified product selections disagree for product use {use.id.value!r}"
            )
        records.append(
            RecordUse(
                id=selection.record_id or product.qualified_id,
                product_use_id=use.id,
                metadata=_durable_metadata(selection.metadata),
            )
        )
    return LoweredProductModel(
        product_defs=products,
        instrument_product_producers=producers,
        product_uses=tuple(uses),
        record_uses=tuple(records),
    )


def _lower_record_axis_intent(
    static_evaluator: StaticRelationEvaluator,
    topology: Topology,
    axis: RecordAxisIntent,
    inputs: Mapping[str, object],
    *,
    record_id: str,
    type_bindings: RelationTypeBindings,
    bind_series_input_refs: BindSeriesInputRefs,
    bind_relation_input_refs: BindRelationInputRefs,
    input_row: InputRow,
) -> ProductAxisDef:
    size, metadata = _static_axis_size(
        static_evaluator,
        topology,
        axis.size,
        default=1,
        location=ModelLocation(
            root="records",
            path=(record_id, "axes", axis.id, "size"),
        ),
        inputs=inputs,
        type_bindings=type_bindings,
        entity_axis=axis.entity_values,
        bind_series_input_refs=bind_series_input_refs,
        bind_relation_input_refs=bind_relation_input_refs,
        input_row=input_row,
    )
    return compiler_product_axis(
        axis.id,
        size=size,
        kind=axis.kind,
        unit=axis.unit,
        metadata=metadata,
    )


def _lower_inline_product(
    static_evaluator: StaticRelationEvaluator,
    topology: Topology,
    record: RecordIntent,
    inputs: Mapping[str, object],
    *,
    type_bindings: RelationTypeBindings,
    bind_series_input_refs: BindSeriesInputRefs,
    bind_relation_input_refs: BindRelationInputRefs,
    input_row: InputRow,
) -> tuple[ProductDef, InstrumentProductProducer]:
    product = ProductDef(
        id=product_id(record.id),
        kind=record.kind,
        unit=record.unit,
        dtype=record.dtype,
        axes=tuple(
            _lower_record_axis_intent(
                static_evaluator,
                topology,
                axis,
                inputs,
                record_id=record.id,
                type_bindings=type_bindings,
                bind_series_input_refs=bind_series_input_refs,
                bind_relation_input_refs=bind_relation_input_refs,
                input_row=input_row,
            )
            for axis in record.axes
        ),
        metadata=_durable_metadata(record.metadata),
    )
    return product, InstrumentProductProducer(
        id=ProductProducerId(product.id.symbol),
        product_id=product.id,
        resource_target=record.resource_port_id,
        capability=record.capability,
        provider_key=record.product_key or record.id,
        metadata=_durable_metadata(record.producer_metadata),
    )


def _lower_product_port(
    static_evaluator: StaticRelationEvaluator,
    topology: Topology,
    product: ModuleProductPort,
    inputs: Mapping[str, object],
    *,
    type_bindings: RelationTypeBindings,
    bind_series_input_refs: BindSeriesInputRefs,
    bind_relation_input_refs: BindRelationInputRefs,
    input_row: InputRow,
) -> tuple[ProductDef, InstrumentProductProducer]:
    product_def = ProductDef(
        id=product.product_id,
        kind=product.kind,
        unit=product.unit,
        dtype=product.dtype,
        axes=tuple(
            _lower_record_axis_intent(
                static_evaluator,
                topology,
                axis,
                inputs,
                record_id=product.qualified_id,
                type_bindings=type_bindings,
                bind_series_input_refs=bind_series_input_refs,
                bind_relation_input_refs=bind_relation_input_refs,
                input_row=input_row,
            )
            for axis in product.axes
        ),
        metadata=_durable_metadata(product.metadata),
    )
    return product_def, InstrumentProductProducer(
        id=ProductProducerId(product_def.id.symbol),
        product_id=product_def.id,
        resource_target=product.resource_port_id,
        capability=product.capability,
        provider_key=product.product_key or product.id,
        metadata=_durable_metadata(product.producer_metadata),
    )


def _static_positive_int(
    static_evaluator: StaticRelationEvaluator,
    value: ScalarExpr | Quantity | float | None,
    *,
    default: int,
    location: ModelLocation,
    inputs: Mapping[str, object],
    input_row: InputRow,
    type_bindings: RelationTypeBindings,
    expected_type: Scalar | None = None,
) -> int:
    if value is None:
        return default
    expression = value if isinstance(value, ScalarExpr) else as_scalar_expr(value)
    try:
        evaluated = static_evaluator.scalar(
            expression,
            bindings=type_bindings,
            expected_type=expected_type,
            inputs=input_row(inputs),
        )
    except (ArithmeticError, KeyError, TypeError, ValueError) as error:
        raise_frontend_problem(
            "module_records_value_invalid",
            f"records value must resolve during configuration binding: {error}",
            location.root,
            path=location.path,
        )
    if isinstance(evaluated, Quantity):
        number = evaluated.value
    elif isinstance(evaluated, int | float) and not isinstance(evaluated, bool):
        number = float(evaluated)
    else:
        raise_frontend_problem(
            "module_records_value_invalid",
            "records value must resolve to a numeric count",
            location.root,
            path=location.path,
        )
    if number <= 0 or int(number) != number:
        raise_frontend_problem(
            "module_records_value_invalid",
            "records value must be a positive integer",
            location.root,
            path=location.path,
        )
    return int(number)


def _static_axis_size(
    static_evaluator: StaticRelationEvaluator,
    topology: Topology,
    value: AxisSizeInput | None,
    *,
    default: int,
    location: ModelLocation,
    inputs: Mapping[str, object],
    type_bindings: RelationTypeBindings,
    entity_axis: bool = False,
    bind_series_input_refs: BindSeriesInputRefs,
    bind_relation_input_refs: BindRelationInputRefs,
    input_row: InputRow,
) -> tuple[int, dict[str, JsonValue]]:
    selected_value: object = value
    selected_type: ValueType | None = None
    if isinstance(value, ValueRef):
        selected_type = value.value_type
        lowered = internal_lower_value_ref(value)
        if isinstance(lowered, ComputeResultRef):
            raise AssertionError(
                "verified record axis unexpectedly depends on a compute result"
            )
        selected_value = lowered
    if isinstance(selected_value, SeriesExpr):
        try:
            evaluated = static_evaluator.series(
                bind_series_input_refs(selected_value, inputs),
                bindings=type_bindings,
                expected_type=(
                    selected_type if isinstance(selected_type, Series) else None
                ),
                inputs=inputs,
            )
        except (ArithmeticError, KeyError, TypeError, ValueError) as error:
            code = (
                "module_record_entity_axis_invalid"
                if entity_axis
                else "module_records_value_invalid"
            )
            raise_frontend_problem(
                code,
                "record axis could not be evaluated during configuration "
                f"binding: {error}",
                location.root,
                path=location.path,
            )
        if not entity_axis:
            return len(evaluated), {}
        entities = _axis_entities(topology, evaluated, location=location)
        return len(entities), _entity_axis_metadata(entities)
    if isinstance(selected_value, RelationExpr):
        if entity_axis:
            raise_frontend_problem(
                "module_record_entity_axis_invalid",
                "entity record axis must be scalar or series-shaped",
                location.root,
                path=location.path,
            )
        try:
            evaluated_rows = static_evaluator.relation(
                bind_relation_input_refs(selected_value, inputs),
                bindings=type_bindings,
                expected_type=(
                    selected_type if isinstance(selected_type, Table) else None
                ),
                inputs=inputs,
            )
        except (ArithmeticError, KeyError, TypeError, ValueError) as error:
            raise_frontend_problem(
                "module_records_value_invalid",
                "record axis could not be evaluated during configuration "
                f"binding: {error}",
                location.root,
                path=location.path,
            )
        return len(evaluated_rows), {}
    if isinstance(selected_value, Sequence) and not isinstance(
        selected_value, str | bytes
    ):
        if not entity_axis:
            return len(selected_value), {}
        entities = _axis_entities(
            topology,
            cast("Sequence[object]", selected_value),
            location=location,
        )
        return len(entities), _entity_axis_metadata(entities)
    if entity_axis:
        if not isinstance(selected_value, ScalarExpr):
            raise_frontend_problem(
                "module_record_entity_axis_invalid",
                "entity record axis must resolve to an entity series",
                location.root,
                path=location.path,
            )
        try:
            evaluated_entity = static_evaluator.scalar(
                selected_value,
                bindings=type_bindings,
                expected_type=(
                    selected_type if isinstance(selected_type, Scalar) else None
                ),
                inputs=input_row(inputs),
            )
        except (ArithmeticError, KeyError, TypeError, ValueError) as error:
            raise_frontend_problem(
                "module_record_entity_axis_invalid",
                "entity record axis could not be evaluated during "
                f"configuration binding: {error}",
                location.root,
                path=location.path,
            )
        entities = _axis_entities(topology, [evaluated_entity], location=location)
        return len(entities), _entity_axis_metadata(entities)
    if not isinstance(selected_value, ScalarExpr) and selected_value is not None:
        _validate_axis_size_literal(cast("AxisSizeInput", selected_value))
    positive_value = cast("ScalarExpr | Quantity | float | None", selected_value)
    return (
        _static_positive_int(
            static_evaluator,
            positive_value,
            default=default,
            location=location,
            inputs=inputs,
            input_row=input_row,
            type_bindings=type_bindings,
            expected_type=(
                selected_type if isinstance(selected_type, Scalar) else None
            ),
        ),
        {},
    )


def _validate_axis_size_literal(value: AxisSizeInput) -> None:
    if isinstance(value, Quantity | int | float) and not isinstance(value, bool):
        return
    msg = f"axis size must be numeric or an entity series, got {value!r}"
    raise TypeError(msg)


def _axis_entities(
    topology: Topology,
    values: Sequence[object],
    *,
    location: ModelLocation,
) -> tuple[EntityRef, ...]:
    if not values:
        raise_frontend_problem(
            "module_record_entity_axis_invalid",
            "entity record axis must not be empty",
            location.root,
            path=location.path,
        )
    if not all(isinstance(value, EntityRef | str) and bool(value) for value in values):
        raise_frontend_problem(
            "module_record_entity_axis_invalid",
            "entity record axis values must be entity references",
            location.root,
            path=location.path,
        )
    try:
        resolved = resolve_entities(
            topology,
            cast("Sequence[EntityRef | str]", values),
        )
    except EntityResolutionError as error:
        raise_entity_resolution_problem(error)
    entity_ids = [entity.id for entity in resolved]
    duplicates = sorted(
        entity_id for entity_id, count in Counter(entity_ids).items() if count > 1
    )
    if duplicates:
        raise_frontend_problem(
            "module_record_entity_axis_duplicate",
            "entity record axis contains duplicate entities: " + ", ".join(duplicates),
            location.root,
            path=location.path,
        )
    return resolved


def _entity_axis_metadata(value: Sequence[EntityRef]) -> dict[str, JsonValue]:
    entity_kind = value[0].kind if value else None
    if entity_kind is None or any(entity.kind != entity_kind for entity in value):
        entity_kind = None
    return {
        "entities": [entity.model_dump(mode="json") for entity in value],
        **({"entity_kind": entity_kind} if entity_kind else {}),
    }


def _durable_metadata(
    metadata: Mapping[str, MetadataValue],
) -> dict[str, JsonValue]:
    normalized = normalize_json_value(metadata)
    if not isinstance(normalized, dict):
        raise AssertionError("record metadata normalization must produce an object")
    return cast("dict[str, JsonValue]", normalized)


__all__ = [
    "lower_product_selections",
    "lower_records",
]
