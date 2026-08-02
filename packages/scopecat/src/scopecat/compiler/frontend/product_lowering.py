"""Config-dependent lowering of products and durable record selections."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from scopecat.compiler.bound_facts import product_axis as compiler_product_axis
from scopecat.compiler.entity_resolution import (
    EntityResolutionError,
    resolve_entities,
)
from scopecat.compiler.frontend.problems import (
    raise_entity_resolution_problem,
    raise_frontend_problem,
)
from scopecat.compiler.frontend.static_evaluation import StaticRelationEvaluator
from scopecat.compiler.relations.verification import ExpressionTypeBindings
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.problems import ModelLocation
from scopecat.kernel.product_identity import ProductId, ProductUse, ProductUseId
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_types import Scalar, ValueType
from scopecat.measurements.products import ProductAxisDef, ProductDef
from scopecat.measurements.records import RecordUse
from scopecat.program.expressions import (
    ComputeResultScalarExpr,
    ScalarExpr,
    as_scalar_expr,
)
from scopecat.program.products import (
    AxisSizeInput,
    ModuleProductDecl,
    ProductAxis,
    RecordSelection,
    product_axis_dimension_id,
)
from scopecat.program.value_refs import (
    ValueRef,
    internal_lower_value_ref,
)
from scopecat.program.values import MetadataValue
from scopecat.records._run_request_values import normalize_json_value
from scopecat.records.config import Topology

type InputRow = Callable[[Mapping[str, object]], Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class LoweredProductModel:
    """Orthogonal product declarations, uses, and record consumers."""

    product_defs: tuple[ProductDef, ...] = ()
    product_uses: tuple[ProductUse, ...] = ()
    record_uses: tuple[RecordUse, ...] = ()


def lower_products(
    static_evaluator: StaticRelationEvaluator,
    topology: Topology,
    selections: Sequence[RecordSelection],
    product_declarations_by_id: Mapping[ProductId, ModuleProductDecl],
    inputs: Mapping[str, object],
    *,
    type_bindings: ExpressionTypeBindings,
    input_row: InputRow,
) -> LoweredProductModel:
    products = tuple(
        _lower_product_declaration(
            static_evaluator,
            topology,
            product,
            inputs,
            type_bindings=type_bindings,
            input_row=input_row,
        )
        for product in product_declarations_by_id.values()
    )
    uses: list[ProductUse] = []
    uses_by_id: dict[ProductUseId, ProductUse] = {}
    records: list[RecordUse] = []
    for selection in selections:
        product = product_declarations_by_id.get(selection.product_id)
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
                role=selection.role,
                recording_group_id=selection.recording_group_id,
                metadata=_durable_metadata(selection.metadata),
            )
        )
    return LoweredProductModel(
        product_defs=products,
        product_uses=tuple(uses),
        record_uses=tuple(records),
    )


def _lower_product_axis(
    static_evaluator: StaticRelationEvaluator,
    topology: Topology,
    axis: ProductAxis,
    inputs: Mapping[str, object],
    *,
    product: ModuleProductDecl,
    type_bindings: ExpressionTypeBindings,
    input_row: InputRow,
) -> ProductAxisDef:
    size, metadata = _static_axis_size(
        static_evaluator,
        topology,
        axis.size,
        default=1,
        location=ModelLocation(
            root="products",
            path=(product.qualified_id, "axes", axis.id, "size"),
        ),
        inputs=inputs,
        type_bindings=type_bindings,
        entity_axis=axis.entity_values,
        input_row=input_row,
    )
    return compiler_product_axis(
        axis.id,
        dimension_id=product_axis_dimension_id(product, axis),
        dimension_label=axis.shared_as or axis.id,
        size=size,
        kind=axis.kind,
        unit=axis.unit,
        metadata=metadata,
    )


def _lower_product_declaration(
    static_evaluator: StaticRelationEvaluator,
    topology: Topology,
    product: ModuleProductDecl,
    inputs: Mapping[str, object],
    *,
    type_bindings: ExpressionTypeBindings,
    input_row: InputRow,
) -> ProductDef:
    return ProductDef(
        id=product.product_id,
        unit=product.unit,
        dtype=product.dtype,
        axes=tuple(
            _lower_product_axis(
                static_evaluator,
                topology,
                axis,
                inputs,
                product=product,
                type_bindings=type_bindings,
                input_row=input_row,
            )
            for axis in product.axes
        ),
        metadata=_durable_metadata(product.metadata),
    )


def _static_positive_int(
    static_evaluator: StaticRelationEvaluator,
    value: ScalarExpr | Quantity | float | None,
    *,
    default: int,
    location: ModelLocation,
    inputs: Mapping[str, object],
    input_row: InputRow,
    type_bindings: ExpressionTypeBindings,
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
            "product_axis_size_invalid",
            f"product axis size must resolve during configuration binding: {error}",
            location.root,
            path=location.path,
        )
    if isinstance(evaluated, Quantity):
        number = evaluated.value
    elif isinstance(evaluated, int | float) and not isinstance(evaluated, bool):
        number = float(evaluated)
    else:
        raise_frontend_problem(
            "product_axis_size_invalid",
            "product axis size must resolve to a numeric count",
            location.root,
            path=location.path,
        )
    if number <= 0 or int(number) != number:
        raise_frontend_problem(
            "product_axis_size_invalid",
            "product axis size must be a positive integer",
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
    type_bindings: ExpressionTypeBindings,
    entity_axis: bool = False,
    input_row: InputRow,
) -> tuple[int, dict[str, JsonValue]]:
    selected_value: object = value
    selected_type: ValueType | None = None
    if isinstance(value, ValueRef):
        selected_type = value.value_type
        lowered = internal_lower_value_ref(value)
        if isinstance(lowered, ComputeResultScalarExpr):
            raise AssertionError(
                "verified product axis unexpectedly depends on a compute result"
            )
        selected_value = lowered
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
                "product_entity_axis_invalid",
                "entity product axis must resolve to an entity or literal sequence",
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
                "product_entity_axis_invalid",
                "entity product axis could not be evaluated during "
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
    msg = f"axis size must be numeric or a literal sequence, got {value!r}"
    raise TypeError(msg)


def _axis_entities(
    topology: Topology,
    values: Sequence[object],
    *,
    location: ModelLocation,
) -> tuple[EntityRef, ...]:
    if not values:
        raise_frontend_problem(
            "product_entity_axis_invalid",
            "entity product axis must not be empty",
            location.root,
            path=location.path,
        )
    if not all(isinstance(value, EntityRef | str) and bool(value) for value in values):
        raise_frontend_problem(
            "product_entity_axis_invalid",
            "entity product axis values must be entity references",
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
            "product_entity_axis_duplicate",
            "entity product axis contains duplicate entities: " + ", ".join(duplicates),
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
