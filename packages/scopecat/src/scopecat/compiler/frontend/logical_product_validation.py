"""Verify logical products, record selections, and axis contracts."""

from __future__ import annotations

from collections.abc import Sequence

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemLocation,
    ProblemPhase,
    model_location,
)
from scopecat.kernel.product_identity import ProductId, ProductUse, ProductUseId
from scopecat.kernel.quantity import Quantity as QuantityValue
from scopecat.kernel.units import is_supported_unit
from scopecat.program.logical import LogicalProgram
from scopecat.program.point_domain import (
    analyze_point_domain,
    is_point_coordinate_type,
)
from scopecat.program.products import (
    EntityAxisDef,
    EntityRecordMemberSelection,
    EntityRecordSelection,
    ModuleProductDecl,
    ProductAxis,
    ProductRecordSelection,
    RecordSelection,
    product_axis_dimension_id,
)
from scopecat.program.recording import LogicalValueRecordSelection
from scopecat.program.value_refs import (
    ValueRef,
    internal_value_ref_point_dependencies,
    internal_value_ref_requires_execution,
)


def verify_product_schema(
    program: LogicalProgram,
    problems: list[Problem],
) -> dict[ProductId, ModuleProductDecl]:
    product_by_id: dict[ProductId, ModuleProductDecl] = {}
    duplicate_products: set[ProductId] = set()
    for product in program.product_declarations:
        if product.product_id in product_by_id:
            duplicate_products.add(product.product_id)
            continue
        product_by_id[product.product_id] = product
    for acquire_index, acquire in enumerate(program.acquisitions):
        for result_index, result in enumerate(acquire.results):
            if result.product_id in product_by_id:
                continue
            problems.append(
                _problem(
                    "acquire_product_definition_missing",
                    f"acquisition {acquire.id.qualified_name!r} references unknown "
                    f"product {result.product_id.qualified_name!r}",
                    model_location(
                        "acquisitions",
                        acquire_index,
                        "results",
                        result_index,
                        "product_id",
                    ),
                )
            )
    if duplicate_products:
        problems.append(
            _problem(
                "module_product_duplicate",
                "logical program defines duplicate products: "
                + ", ".join(sorted(item.qualified_name for item in duplicate_products)),
                model_location("products"),
            )
        )

    product_uses: dict[ProductUseId, ProductUse] = {}
    conflicting_product_uses: dict[ProductUseId, tuple[ProductUse, ProductUse]] = {}
    for selection in program.product_record_selections:
        for member in _product_selection_members(selection):
            use = member.product_use
            existing_use = product_uses.get(use.id)
            if existing_use is None:
                product_uses[use.id] = use
            elif existing_use != use:
                conflicting_product_uses.setdefault(use.id, (existing_use, use))
            product = product_by_id.get(member.product_id)
            if product is None:
                problems.append(
                    _problem(
                        "module_product_unknown",
                        "experiment selects unknown product "
                        f"{member.product_id.qualified_name}",
                        model_location("record_selections"),
                    )
                )
                continue
            if (
                member.product_origin is not None
                and member.product_origin != product.origin
            ):
                problems.append(
                    _problem(
                        "module_product_foreign_instance",
                        "experiment selects product "
                        f"{member.product_id.qualified_name!r} from "
                        "another module instance",
                        model_location("record_selections"),
                    )
                )
    for use_id in sorted(conflicting_product_uses, key=lambda item: item.value):
        existing_use, conflicting_use = conflicting_product_uses[use_id]
        problems.append(
            _problem(
                "product_use_identity_conflict",
                f"product use {use_id.value!r} refers to both "
                f"{existing_use.product_id.qualified_name!r} and "
                f"{conflicting_use.product_id.qualified_name!r}",
                model_location("record_selections"),
            )
        )

    record_ids = [
        (
            selection.id
            if isinstance(selection, LogicalValueRecordSelection)
            else _product_record_id(selection)
        )
        for selection in program.record_selections
    ]
    duplicate_records = _duplicates(record_ids)
    if duplicate_records:
        problems.append(
            _problem(
                "experiment_record_duplicate",
                "experiment definition selects duplicate record ids: "
                + ", ".join(duplicate_records),
                model_location("record_selections"),
            )
        )

    point_columns = {
        column.id
        for column in analyze_point_domain(
            program.point_domain,
            layout=program.point_domain_layout,
        ).value_type.columns
        if is_point_coordinate_type(column.value_type)
    }
    for record_id in sorted(set(record_ids) & point_columns):
        problems.append(
            _problem(
                "experiment_record_coordinate_collision",
                f"record {record_id!r} conflicts with a point coordinate",
                model_location("record_selections", record_id),
            )
        )

    _verify_product_axes(program.product_declarations, problems)
    _verify_entity_record_axes(program.product_record_selections, problems)
    return product_by_id


def _product_selection_members(
    selection: ProductRecordSelection,
) -> tuple[RecordSelection | EntityRecordMemberSelection, ...]:
    return (selection,) if isinstance(selection, RecordSelection) else selection.members


def _product_record_id(selection: ProductRecordSelection) -> str:
    if isinstance(selection, EntityRecordSelection):
        return selection.record_id
    return selection.record_id or selection.product_id.qualified_name


def _verify_entity_record_axes(
    selections: Sequence[ProductRecordSelection],
    problems: list[Problem],
) -> None:
    axes_by_id: dict[str, EntityAxisDef] = {}
    for selection in selections:
        if not isinstance(selection, EntityRecordSelection):
            continue
        existing = axes_by_id.setdefault(selection.axis.id, selection.axis)
        if existing == selection.axis:
            continue
        problems.append(
            _problem(
                "entity_record_axis_conflict",
                f"entity axis {selection.axis.id!r} is reused with different members",
                model_location("record_selections", selection.record_id, "axis"),
            )
        )


def verify_product_axis_dependencies(
    program: LogicalProgram,
    problems: list[Problem],
) -> None:
    for product in program.product_declarations:
        for axis in product.axes:
            if not isinstance(axis.size, ValueRef):
                continue
            location = model_location(
                "products",
                *product.scope,
                product.id,
                "axes",
                axis.id,
                "size",
            )
            if internal_value_ref_requires_execution(axis.size):
                problems.append(
                    _problem(
                        "product_axis_value_requires_execution",
                        "product axis size cannot depend on an external operation",
                        location,
                    )
                )
            elif internal_value_ref_point_dependencies(axis.size):
                problems.append(
                    _problem(
                        "product_axis_value_depends_on_point",
                        "product axis size cannot depend on point coordinates",
                        location,
                    )
                )


def _verify_product_axes(
    products: Sequence[ModuleProductDecl],
    problems: list[Problem],
) -> None:
    shared_axes_by_dimension_id: dict[str, tuple[str, ProductAxis]] = {}
    for product in products:
        product_id = product.qualified_id
        _verify_product_definition(product, problems)
        seen_axis_ids: set[str] = set()
        seen_shared_dimensions: set[str] = set()
        for axis in product.axes:
            if axis.id in seen_axis_ids:
                continue
            seen_axis_ids.add(axis.id)
            if axis.shared_as is None:
                continue
            dimension_id = product_axis_dimension_id(product, axis)
            if dimension_id in seen_shared_dimensions:
                continue
            seen_shared_dimensions.add(dimension_id)
            existing = shared_axes_by_dimension_id.get(dimension_id)
            if existing is None:
                shared_axes_by_dimension_id[dimension_id] = (product_id, axis)
                continue
            existing_product_id, existing_axis = existing
            if _source_axes_can_conflict(existing_axis, axis):
                problems.append(
                    _problem(
                        "product_axis_conflict",
                        f"product {product_id!r} axis {axis.id!r} conflicts with "
                        f"product {existing_product_id!r} on shared dimension "
                        f"{dimension_id!r}; shared axes must have identical kinds, "
                        "sizes, and units",
                        model_location("products", product_id, "axes", axis.id),
                        related_locations=(
                            model_location(
                                "products",
                                existing_product_id,
                                "axes",
                                existing_axis.id,
                            ),
                        ),
                    )
                )


def _verify_product_definition(
    product: ModuleProductDecl,
    problems: list[Problem],
) -> None:
    product_id = product.qualified_id
    location = model_location("products", *product.scope, product.id)
    if product.unit is not None and not is_supported_unit(product.unit):
        problems.append(
            _problem(
                "product_unit_unsupported",
                f"product {product_id!r} uses unsupported unit {product.unit!r}",
                model_location(location.root, *location.path, "unit"),
            )
        )
    duplicate_axes = _duplicates([axis.id for axis in product.axes])
    for axis_id in duplicate_axes:
        problems.append(
            _problem(
                "product_axis_duplicate",
                f"product {product_id!r} axis {axis_id!r} is duplicated",
                model_location(location.root, *location.path, "axes"),
            )
        )
    axes_by_dimension_id: dict[str, ProductAxis] = {}
    for axis in product.axes:
        dimension_id = product_axis_dimension_id(product, axis)
        existing_axis = axes_by_dimension_id.get(dimension_id)
        if existing_axis is None:
            axes_by_dimension_id[dimension_id] = axis
            continue
        if existing_axis.id == axis.id:
            continue
        problems.append(
            _problem(
                "product_axis_dimension_duplicate",
                f"product {product_id!r} axes {existing_axis.id!r} and "
                f"{axis.id!r} use the same dataset dimension {dimension_id!r}",
                model_location(location.root, *location.path, "axes", axis.id),
                related_locations=(
                    model_location(
                        location.root,
                        *location.path,
                        "axes",
                        existing_axis.id,
                    ),
                ),
            )
        )
    for axis in product.axes:
        axis_location = model_location(location.root, *location.path, "axes", axis.id)
        if axis.unit is not None and not is_supported_unit(axis.unit):
            problems.append(
                _problem(
                    "product_axis_unit_unsupported",
                    f"product {product_id!r} axis {axis.id!r} uses unsupported "
                    f"unit {axis.unit!r}",
                    model_location(axis_location.root, *axis_location.path, "unit"),
                )
            )
        size = _literal_axis_size(axis)
        if size is not None and size <= 0:
            problems.append(
                _problem(
                    "product_axis_size_invalid",
                    "product axis size must be a positive integer",
                    model_location(axis_location.root, *axis_location.path, "size"),
                )
            )


def _source_axes_can_conflict(left: ProductAxis, right: ProductAxis) -> bool:
    if (left.kind or left.id) != (right.kind or right.id):
        return True
    if left.unit != right.unit or left.entity_values != right.entity_values:
        return True
    left_size = _literal_axis_size(left)
    right_size = _literal_axis_size(right)
    return left_size is not None and right_size is not None and left_size != right_size


def _literal_axis_size(axis: ProductAxis) -> int | None:
    value = axis.size
    if isinstance(value, tuple):
        return len(value)
    if isinstance(value, QuantityValue):
        number = value.value
    elif isinstance(value, int | float) and not isinstance(value, bool):
        number = float(value)
    else:
        return None
    if not number.is_integer():
        return -1
    return int(number)


def _duplicates(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return tuple(sorted(duplicates))


def _problem(
    code: str,
    message: str,
    location: ModelLocation,
    *,
    related_locations: Sequence[ProblemLocation] = (),
) -> Problem:
    return compiler_problem(
        code,
        message,
        location,
        phase=ProblemPhase.AUTHORING,
        related_locations=related_locations,
    )
