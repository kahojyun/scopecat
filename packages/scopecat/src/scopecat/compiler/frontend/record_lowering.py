"""Config-dependent lowering of source record intents."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

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
from scopecat.compiler.frontend.context import ExperimentAuthoringContext
from scopecat.compiler.relations.backend import (
    EvalContext,
    evaluate_relation,
    evaluate_scalar,
    evaluate_series,
    select_relation_plan,
)
from scopecat.compiler.relations.model import (
    CellValue,
    RelationExpr,
    ScalarExpr,
    SeriesExpr,
    as_scalar_expr,
)
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    verify_relation_plan,
)
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.typed.products import (
    InstrumentProductProducer,
    ProductAxisDef,
    ProductDef,
)
from scopecat.compiler.typed.program import product_axis as compiler_product_axis
from scopecat.compiler.typed.records import RecordUse
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
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity

type BindSeriesInputRefs = Callable[[SeriesExpr, Mapping[str, object]], SeriesExpr]
type BindRelationInputRefs = Callable[
    [RelationExpr, Mapping[str, object]], RelationExpr
]
type InputRow = Callable[[Mapping[str, object]], dict[str, CellValue]]


@dataclass(frozen=True, slots=True)
class LoweredProductModel:
    """Orthogonal product declarations, producers, uses, and record consumers."""

    product_defs: tuple[ProductDef, ...] = ()
    instrument_product_producers: tuple[InstrumentProductProducer, ...] = ()
    product_uses: tuple[ProductUse, ...] = ()
    record_uses: tuple[RecordUse, ...] = ()


def _static_relation_bindings(
    bindings: RelationTypeBindings,
) -> RelationTypeBindings:
    """Keep durable imports while excluding point-local lexical rows.

    Record metadata is folded before a run has a point, current, or outer row.
    Verifying against those rows would certify an environment that the static
    authoring evaluator can never provide.
    """

    return RelationTypeBindings(
        inputs=bindings.inputs,
        parameters=bindings.parameters,
        parameter_lookups=bindings.parameter_lookups,
    )


def lower_records(
    ctx: ExperimentAuthoringContext,
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
            ctx,
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


def lower_product_selections(
    ctx: ExperimentAuthoringContext,
    selections: Sequence[ProductSelectionIntent],
    product_ports: Sequence[ModuleProductPort],
    inputs: Mapping[str, object],
    *,
    type_bindings: RelationTypeBindings,
    bind_series_input_refs: BindSeriesInputRefs,
    bind_relation_input_refs: BindRelationInputRefs,
    input_row: InputRow,
) -> LoweredProductModel:
    product_by_id = _product_ports_by_id(ctx, product_ports)
    lowered = tuple(
        _lower_product_port(
            ctx,
            product,
            inputs,
            type_bindings=type_bindings,
            bind_series_input_refs=bind_series_input_refs,
            bind_relation_input_refs=bind_relation_input_refs,
            input_row=input_row,
        )
        for product in product_ports
    )
    products = tuple(product for product, _producer in lowered)
    producers = tuple(producer for _product, producer in lowered)
    uses: list[ProductUse] = []
    uses_by_id: dict[ProductUseId, ProductUse] = {}
    records: list[RecordUse] = []
    for selection in selections:
        product = product_by_id.get(selection.product_id)
        if product is None:
            ctx.raise_problem(
                "module_product_unknown",
                "experiment selects unknown product "
                f"{selection.product_id.qualified_name}",
                "records",
            )
        use = selection.product_use
        existing_use = uses_by_id.get(use.id)
        if existing_use is None:
            uses_by_id[use.id] = use
            uses.append(use)
        elif existing_use != use:
            ctx.raise_problem(
                "product_use_identity_conflict",
                f"product use {use.id.value!r} refers to both "
                f"{existing_use.product_id.qualified_name!r} and "
                f"{use.product_id.qualified_name!r}",
                "records",
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


def _product_ports_by_id(
    ctx: ExperimentAuthoringContext,
    product_ports: Sequence[ModuleProductPort],
) -> dict[ProductId, ModuleProductPort]:
    ids = [product.product_id for product in product_ports]
    duplicates = sorted(
        {item for item in ids if ids.count(item) > 1},
        key=lambda item: item.qualified_name,
    )
    if duplicates:
        ctx.raise_problem(
            "module_product_duplicate",
            "experiment assembly defines duplicate products: "
            + ", ".join(item.qualified_name for item in duplicates),
            "products",
        )
    return {product.product_id: product for product in product_ports}


def _lower_record_axis_intent(
    ctx: ExperimentAuthoringContext,
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
        ctx,
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
    ctx: ExperimentAuthoringContext,
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
                ctx,
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
    ctx: ExperimentAuthoringContext,
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
                ctx,
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
    ctx: ExperimentAuthoringContext,
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
        evaluated = evaluate_scalar(
            ctx.static_relation_backend,
            select_relation_plan(
                ctx.static_relation_backend,
                verify_relation_plan(
                    expression,
                    bindings=_static_relation_bindings(type_bindings),
                    expected_type=expected_type,
                ),
            ),
            EvalContext(
                params=ctx.parameters,
                inputs=input_row(inputs),
            ),
        )
    except (ArithmeticError, KeyError, TypeError, ValueError) as error:
        ctx.raise_problem(
            "module_records_value_invalid",
            f"records value must resolve from config at authoring time: {error}",
            location.root,
            path=location.path,
        )
    if isinstance(evaluated, Quantity):
        number = evaluated.value
    elif isinstance(evaluated, int | float) and not isinstance(evaluated, bool):
        number = float(evaluated)
    else:
        ctx.raise_problem(
            "module_records_value_invalid",
            "records value must resolve to a numeric count",
            location.root,
            path=location.path,
        )
    if number <= 0 or int(number) != number:
        ctx.raise_problem(
            "module_records_value_invalid",
            "records value must be a positive integer",
            location.root,
            path=location.path,
        )
    return int(number)


def _static_axis_size(
    ctx: ExperimentAuthoringContext,
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
) -> tuple[int, dict[str, Any]]:
    selected_value: object = value
    selected_type: ValueType | None = None
    if isinstance(value, ValueRef):
        selected_type = value.value_type
        lowered = internal_lower_value_ref(value)
        if isinstance(lowered, ComputeResultRef):
            ctx.raise_problem(
                "module_record_axis_compute_value_invalid",
                "record axis size cannot depend on a point-local compute result",
                location.root,
                path=location.path,
            )
        selected_value = lowered
    if isinstance(selected_value, SeriesExpr):
        try:
            evaluated = evaluate_series(
                ctx.static_relation_backend,
                select_relation_plan(
                    ctx.static_relation_backend,
                    verify_relation_plan(
                        bind_series_input_refs(selected_value, inputs),
                        bindings=_static_relation_bindings(type_bindings),
                        expected_type=(
                            selected_type if isinstance(selected_type, Series) else None
                        ),
                    ),
                ),
                EvalContext(
                    params=ctx.parameters,
                    inputs=dict(inputs),
                ),
            )
        except (ArithmeticError, KeyError, TypeError, ValueError) as error:
            code = (
                "module_record_entity_axis_invalid"
                if entity_axis
                else "module_records_value_invalid"
            )
            ctx.raise_problem(
                code,
                f"record axis could not be evaluated at authoring time: {error}",
                location.root,
                path=location.path,
            )
        if not entity_axis:
            return len(evaluated), {}
        entities = _axis_entities(ctx, evaluated, location=location)
        return len(entities), _entity_axis_metadata(entities)
    if isinstance(selected_value, RelationExpr):
        if entity_axis:
            ctx.raise_problem(
                "module_record_entity_axis_invalid",
                "entity record axis must be scalar or series-shaped",
                location.root,
                path=location.path,
            )
        try:
            evaluated_rows = evaluate_relation(
                ctx.static_relation_backend,
                select_relation_plan(
                    ctx.static_relation_backend,
                    verify_relation_plan(
                        bind_relation_input_refs(selected_value, inputs),
                        bindings=_static_relation_bindings(type_bindings),
                        expected_type=(
                            selected_type if isinstance(selected_type, Table) else None
                        ),
                    ),
                ),
                ctx.parameters,
                inputs=dict(inputs),
            )
        except (ArithmeticError, KeyError, TypeError, ValueError) as error:
            ctx.raise_problem(
                "module_records_value_invalid",
                f"record axis could not be evaluated at authoring time: {error}",
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
            ctx,
            cast("Sequence[object]", selected_value),
            location=location,
        )
        return len(entities), _entity_axis_metadata(entities)
    if entity_axis:
        if not isinstance(selected_value, ScalarExpr):
            ctx.raise_problem(
                "module_record_entity_axis_invalid",
                "entity record axis must resolve to an entity series",
                location.root,
                path=location.path,
            )
        try:
            evaluated_entity = evaluate_scalar(
                ctx.static_relation_backend,
                select_relation_plan(
                    ctx.static_relation_backend,
                    verify_relation_plan(
                        selected_value,
                        bindings=_static_relation_bindings(type_bindings),
                        expected_type=(
                            selected_type if isinstance(selected_type, Scalar) else None
                        ),
                    ),
                ),
                EvalContext(
                    params=ctx.parameters,
                    inputs=input_row(inputs),
                ),
            )
        except (ArithmeticError, KeyError, TypeError, ValueError) as error:
            ctx.raise_problem(
                "module_record_entity_axis_invalid",
                f"entity record axis could not be evaluated: {error}",
                location.root,
                path=location.path,
            )
        entities = _axis_entities(ctx, [evaluated_entity], location=location)
        return len(entities), _entity_axis_metadata(entities)
    if not isinstance(selected_value, ScalarExpr) and selected_value is not None:
        _validate_axis_size_literal(cast("AxisSizeInput", selected_value))
    positive_value = cast("ScalarExpr | Quantity | float | None", selected_value)
    return (
        _static_positive_int(
            ctx,
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
    ctx: ExperimentAuthoringContext,
    values: Sequence[object],
    *,
    location: ModelLocation,
) -> tuple[EntityRef, ...]:
    if not values:
        ctx.raise_problem(
            "module_record_entity_axis_invalid",
            "entity record axis must not be empty",
            location.root,
            path=location.path,
        )
    if not all(isinstance(value, EntityRef | str) and bool(value) for value in values):
        ctx.raise_problem(
            "module_record_entity_axis_invalid",
            "entity record axis values must be entity references",
            location.root,
            path=location.path,
        )
    resolved = ctx.require_entities(cast("Sequence[EntityRef | str]", values))
    entity_ids = [entity.id for entity in resolved]
    duplicates = sorted(
        entity_id for entity_id, count in Counter(entity_ids).items() if count > 1
    )
    if duplicates:
        ctx.raise_problem(
            "module_record_entity_axis_duplicate",
            "entity record axis contains duplicate entities: " + ", ".join(duplicates),
            location.root,
            path=location.path,
        )
    return resolved


def _entity_axis_metadata(value: Sequence[EntityRef]) -> dict[str, Any]:
    entity_kind = value[0].kind if value else None
    if entity_kind is None or any(entity.kind != entity_kind for entity in value):
        entity_kind = None
    return {
        "entities": [entity.model_dump(mode="json") for entity in value],
        **({"entity_kind": entity_kind} if entity_kind else {}),
    }


def _durable_metadata(
    metadata: Mapping[str, MetadataValue],
) -> dict[str, object]:
    normalized = normalize_json_value(metadata)
    if not isinstance(normalized, dict):
        raise AssertionError("record metadata normalization must produce an object")
    return cast("dict[str, object]", normalized)


__all__ = [
    "lower_product_selections",
    "lower_records",
]
