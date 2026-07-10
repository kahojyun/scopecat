"""Config-dependent lowering of source record intents."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast

from scopecat._compiler.program import record_axis as compiler_record_axis
from scopecat._compute_result import ComputeResultRef
from scopecat._planning.records import (
    RecordAxisSpec,
    RecordSpec,
)
from scopecat._relations import (
    CellValue,
    EvalContext,
    RelationExpr,
    ScalarExpr,
    SeriesExpr,
    as_scalar_expr,
)
from scopecat.authoring._context import ExperimentAuthoringContext
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
from scopecat.models._run_request_values import normalize_json_value
from scopecat.models.entity import EntityRef
from scopecat.models.parameter import Quantity

type BindSeriesInputRefs = Callable[[SeriesExpr, Mapping[str, object]], SeriesExpr]
type BindRelationInputRefs = Callable[
    [RelationExpr, Mapping[str, object]], RelationExpr
]
type InputRow = Callable[[Mapping[str, object]], dict[str, CellValue]]


def lower_records(
    ctx: ExperimentAuthoringContext,
    record_intents: Sequence[RecordIntent],
    inputs: Mapping[str, object],
    *,
    bind_series_input_refs: BindSeriesInputRefs,
    bind_relation_input_refs: BindRelationInputRefs,
    input_row: InputRow,
) -> list[RecordSpec]:
    return [
        _lower_record_intent(
            ctx,
            record_intent,
            inputs,
            bind_series_input_refs=bind_series_input_refs,
            bind_relation_input_refs=bind_relation_input_refs,
            input_row=input_row,
        )
        for record_intent in record_intents
    ]


def lower_product_selections(
    ctx: ExperimentAuthoringContext,
    selections: Sequence[ProductSelectionIntent],
    product_ports: Sequence[ModuleProductPort],
    inputs: Mapping[str, object],
    *,
    bind_series_input_refs: BindSeriesInputRefs,
    bind_relation_input_refs: BindRelationInputRefs,
    input_row: InputRow,
) -> list[RecordSpec]:
    product_by_id = _product_ports_by_id(ctx, product_ports)
    records: list[RecordSpec] = []
    for selection in selections:
        product = product_by_id.get(selection.product_id)
        if product is None:
            ctx.raise_diagnostic(
                "module_product_unknown",
                f"experiment selects unknown product {selection.product_id}",
                "records",
            )
        record = _lower_product_port(
            ctx,
            product,
            inputs,
            record_id=selection.record_id or selection.product_id,
            bind_series_input_refs=bind_series_input_refs,
            bind_relation_input_refs=bind_relation_input_refs,
            input_row=input_row,
        )
        records.append(
            record.model_copy(
                update={
                    "metadata": _durable_metadata(
                        {**record.metadata, **selection.metadata}
                    )
                }
            )
        )
    return records


def _product_ports_by_id(
    ctx: ExperimentAuthoringContext,
    product_ports: Sequence[ModuleProductPort],
) -> dict[str, ModuleProductPort]:
    ids = [product.id for product in product_ports]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        ctx.raise_diagnostic(
            "module_product_duplicate",
            "experiment assembly defines duplicate products: " + ", ".join(duplicates),
            "products",
        )
    return {product.id: product for product in product_ports}


def _lower_record_axis_intent(
    ctx: ExperimentAuthoringContext,
    axis: RecordAxisIntent,
    inputs: Mapping[str, object],
    *,
    record_id: str,
    bind_series_input_refs: BindSeriesInputRefs,
    bind_relation_input_refs: BindRelationInputRefs,
    input_row: InputRow,
) -> RecordAxisSpec:
    size, metadata = _static_axis_size(
        ctx,
        axis.size,
        default=1,
        path=f"records.{record_id}.axes.{axis.id}.size",
        inputs=inputs,
        entity_axis=axis.entity_values,
        bind_series_input_refs=bind_series_input_refs,
        bind_relation_input_refs=bind_relation_input_refs,
        input_row=input_row,
    )
    return compiler_record_axis(
        axis.id,
        size=size,
        kind=axis.kind,
        unit=axis.unit,
        metadata=metadata,
    )


def _lower_record_intent(
    ctx: ExperimentAuthoringContext,
    record: RecordIntent,
    inputs: Mapping[str, object],
    *,
    bind_series_input_refs: BindSeriesInputRefs,
    bind_relation_input_refs: BindRelationInputRefs,
    input_row: InputRow,
) -> RecordSpec:
    return RecordSpec(
        id=record.id,
        kind=record.kind,
        source=record.source,
        resource=record.resource,
        capability=record.capability,
        product_key=record.product_key,
        unit=record.unit,
        dtype=record.dtype,
        axes=[
            _lower_record_axis_intent(
                ctx,
                axis,
                inputs,
                record_id=record.id,
                bind_series_input_refs=bind_series_input_refs,
                bind_relation_input_refs=bind_relation_input_refs,
                input_row=input_row,
            )
            for axis in record.axes
        ],
        metadata=_durable_metadata(record.metadata),
    )


def _lower_product_port(
    ctx: ExperimentAuthoringContext,
    product: ModuleProductPort,
    inputs: Mapping[str, object],
    *,
    record_id: str,
    bind_series_input_refs: BindSeriesInputRefs,
    bind_relation_input_refs: BindRelationInputRefs,
    input_row: InputRow,
) -> RecordSpec:
    return _lower_record_intent(
        ctx,
        RecordIntent(
            id=record_id,
            kind=product.kind,
            source=product.source,
            resource=product.resource,
            capability=product.capability,
            product_key=product.product_key,
            unit=product.unit,
            dtype=product.dtype,
            axes=product.axes,
            metadata={"product_id": product.id, **product.metadata},
        ),
        inputs,
        bind_series_input_refs=bind_series_input_refs,
        bind_relation_input_refs=bind_relation_input_refs,
        input_row=input_row,
    )


def _static_positive_int(
    ctx: ExperimentAuthoringContext,
    value: ScalarExpr | Quantity | float | None,
    *,
    default: int,
    path: str,
    inputs: Mapping[str, object],
    input_row: InputRow,
) -> int:
    if value is None:
        return default
    expression = value if isinstance(value, ScalarExpr) else as_scalar_expr(value)
    try:
        evaluated = expression.eval(
            EvalContext(
                params=ctx.parameters,
                inputs=input_row(inputs),
            )
        )
    except Exception as error:
        ctx.raise_diagnostic(
            "module_records_value_invalid",
            f"records value must resolve from config at authoring time: {error}",
            path,
        )
    if isinstance(evaluated, Quantity):
        number = evaluated.value
    elif isinstance(evaluated, int | float) and not isinstance(evaluated, bool):
        number = float(evaluated)
    else:
        ctx.raise_diagnostic(
            "module_records_value_invalid",
            "records value must resolve to a numeric count",
            path,
        )
    if number <= 0 or int(number) != number:
        ctx.raise_diagnostic(
            "module_records_value_invalid",
            "records value must be a positive integer",
            path,
        )
    return int(number)


def _static_axis_size(
    ctx: ExperimentAuthoringContext,
    value: AxisSizeInput | None,
    *,
    default: int,
    path: str,
    inputs: Mapping[str, object],
    entity_axis: bool = False,
    bind_series_input_refs: BindSeriesInputRefs,
    bind_relation_input_refs: BindRelationInputRefs,
    input_row: InputRow,
) -> tuple[int, dict[str, Any]]:
    selected_value: object = value
    if isinstance(value, ValueRef):
        lowered = internal_lower_value_ref(value)
        if isinstance(lowered, ComputeResultRef):
            ctx.raise_diagnostic(
                "module_record_axis_compute_value_invalid",
                "record axis size cannot depend on a point-local compute result",
                path,
            )
        selected_value = lowered
    if isinstance(selected_value, SeriesExpr):
        evaluated = bind_series_input_refs(selected_value, inputs).evaluate(
            EvalContext(
                params=ctx.parameters,
                inputs=dict(inputs),
            )
        )
        if not entity_axis:
            return len(evaluated), {}
        entities = _axis_entities(ctx, evaluated, path=path)
        return len(entities), _entity_axis_metadata(entities)
    if isinstance(selected_value, RelationExpr):
        if entity_axis:
            ctx.raise_diagnostic(
                "module_record_entity_axis_invalid",
                "entity record axis must be scalar or series-shaped",
                path,
            )
        evaluated_rows = bind_relation_input_refs(selected_value, inputs).evaluate(
            ctx.parameters,
            inputs=dict(inputs),
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
            path=path,
        )
        return len(entities), _entity_axis_metadata(entities)
    if entity_axis:
        if not isinstance(selected_value, ScalarExpr):
            ctx.raise_diagnostic(
                "module_record_entity_axis_invalid",
                "entity record axis must resolve to an entity series",
                path,
            )
        try:
            evaluated_entity = selected_value.eval(
                EvalContext(
                    params=ctx.parameters,
                    inputs=input_row(inputs),
                )
            )
        except Exception as error:
            ctx.raise_diagnostic(
                "module_record_entity_axis_invalid",
                f"entity record axis could not be evaluated: {error}",
                path,
            )
        entities = _axis_entities(ctx, [evaluated_entity], path=path)
        return len(entities), _entity_axis_metadata(entities)
    if not isinstance(selected_value, ScalarExpr) and selected_value is not None:
        _validate_axis_size_literal(cast("AxisSizeInput", selected_value))
    positive_value = cast("ScalarExpr | Quantity | float | None", selected_value)
    return (
        _static_positive_int(
            ctx,
            positive_value,
            default=default,
            path=path,
            inputs=inputs,
            input_row=input_row,
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
    path: str,
) -> tuple[EntityRef, ...]:
    if not values:
        ctx.raise_diagnostic(
            "module_record_entity_axis_invalid",
            "entity record axis must not be empty",
            path,
        )
    if not all(isinstance(value, EntityRef | str) and bool(value) for value in values):
        ctx.raise_diagnostic(
            "module_record_entity_axis_invalid",
            "entity record axis values must be entity references",
            path,
        )
    resolved = ctx.require_entities(cast("Sequence[EntityRef | str]", values))
    entity_ids = [entity.id for entity in resolved]
    duplicates = sorted(
        entity_id for entity_id, count in Counter(entity_ids).items() if count > 1
    )
    if duplicates:
        ctx.raise_diagnostic(
            "module_record_entity_axis_duplicate",
            "entity record axis contains duplicate entities: " + ", ".join(duplicates),
            path,
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
