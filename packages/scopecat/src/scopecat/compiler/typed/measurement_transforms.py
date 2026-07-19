"""Verification and canonical ordering for typed measurement transforms."""

from __future__ import annotations

import heapq
from collections.abc import Mapping

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.semantic.model import MeasurementTransformId
from scopecat.compiler.typed.products import MeasurementTransformProductProducer
from scopecat.compiler.typed.program import CoreProgram, TypedMeasurementTransform
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemPhase,
    model_location,
)
from scopecat.kernel.product_identity import ProductId


def typed_measurement_transform_problems(
    program: CoreProgram,
) -> tuple[tuple[TypedMeasurementTransform, ...], tuple[Problem, ...]]:
    """Verify the demand-closed transform graph and return canonical order."""

    problems: list[Problem] = []
    transforms = program.measurement_transforms
    transform_ids = tuple(transform.id for transform in transforms)
    duplicate_transform_ids = {
        transform_id
        for transform_id in transform_ids
        if transform_ids.count(transform_id) > 1
    }
    for transform_id in sorted(
        duplicate_transform_ids,
        key=lambda item: item.qualified_name,
    ):
        problems.append(
            _problem(
                "measurement_transform_duplicate",
                "measurement transform "
                f"{transform_id.qualified_name!r} is declared more than once",
                model_location(
                    "measurement_transforms",
                    transform_id.qualified_name,
                ),
            )
        )

    products = {product.id for product in program.product_defs}
    uses_by_id = {use.id: use for use in program.product_uses}
    uses_by_product = {
        product_id: tuple(
            use.id for use in program.product_uses if use.product_id == product_id
        )
        for product_id in {use.product_id for use in program.product_uses}
    }
    record_use_ids = {record.product_use_id for record in program.record_uses}
    producers_by_product: dict[ProductId, list[object]] = {}
    for producer in (
        *program.instrument_product_producers,
        *program.domain_product_producers,
        *program.measurement_transform_product_producers,
    ):
        producers_by_product.setdefault(producer.product_id, []).append(producer)

    producers_by_output: dict[
        tuple[MeasurementTransformId, str],
        list[MeasurementTransformProductProducer],
    ] = {}
    for producer in program.measurement_transform_product_producers:
        producers_by_output.setdefault(
            (producer.transform_id, producer.output_id),
            [],
        ).append(producer)
    for selected in producers_by_output.values():
        if len(selected) < 2:
            continue
        producer = selected[0]
        problems.append(
            _problem(
                "measurement_transform_output_producer_duplicate",
                "one measurement transform output has more than one product producer",
                model_location(
                    "measurement_transform_product_producers",
                    producer.id.qualified_name,
                ),
            )
        )

    declared_output_keys: set[tuple[MeasurementTransformId, str]] = set()
    input_use_owners: dict[object, tuple[MeasurementTransformId, str]] = {}
    output_owner_by_product: dict[
        ProductId,
        tuple[MeasurementTransformId, str],
    ] = {}
    duplicate_output_products: set[ProductId] = set()
    for transform in transforms:
        location = model_location(
            "measurement_transforms",
            transform.id.qualified_name,
        )
        if transform.rate != "point":
            problems.append(
                _problem(
                    "measurement_transform_rate_unsupported",
                    "typed measurement transforms currently support point rate only",
                    model_location(location.root, *location.path, "rate"),
                )
            )
        input_roles = tuple(item.id for item in transform.inputs)
        for role in sorted(
            {role for role in input_roles if input_roles.count(role) > 1}
        ):
            problems.append(
                _problem(
                    "measurement_transform_input_duplicate",
                    f"measurement transform input role {role!r} is duplicated",
                    model_location(
                        location.root,
                        *location.path,
                        "inputs",
                        role,
                    ),
                )
            )
        output_roles = tuple(item.id for item in transform.outputs)
        for role in sorted(
            {role for role in output_roles if output_roles.count(role) > 1}
        ):
            problems.append(
                _problem(
                    "measurement_transform_output_duplicate",
                    f"measurement transform output role {role!r} is duplicated",
                    model_location(
                        location.root,
                        *location.path,
                        "outputs",
                        role,
                    ),
                )
            )
        if not transform.outputs:
            problems.append(
                _problem(
                    "measurement_transform_output_missing",
                    "measurement transforms require at least one output",
                    model_location(location.root, *location.path, "outputs"),
                )
            )

        demanded = False
        for input_port in transform.inputs:
            input_location = model_location(
                location.root,
                *location.path,
                "inputs",
                input_port.id,
            )
            if input_port.product_id not in products:
                problems.append(
                    _problem(
                        "measurement_transform_input_product_missing",
                        "measurement transform input references unknown product "
                        f"{input_port.product_id.qualified_name!r}",
                        model_location(
                            input_location.root,
                            *input_location.path,
                            "product_id",
                        ),
                    )
                )
            use = uses_by_id.get(input_port.product_use_id)
            if use is None or use.product_id != input_port.product_id:
                problems.append(
                    _problem(
                        "measurement_transform_input_product_use_mismatch",
                        "measurement transform input references a missing or "
                        "foreign product use "
                        f"{input_port.product_use_id.value!r}",
                        model_location(
                            input_location.root,
                            *input_location.path,
                            "product_use_id",
                        ),
                    )
                )
            existing_owner = input_use_owners.get(input_port.product_use_id)
            if existing_owner is not None:
                owner_id, owner_role = existing_owner
                problems.append(
                    _problem(
                        "measurement_transform_input_product_use_duplicate",
                        "product use "
                        f"{input_port.product_use_id.value!r} is consumed by both "
                        f"{owner_id.qualified_name!r}/{owner_role!r} and "
                        f"{transform.id.qualified_name!r}/{input_port.id!r}",
                        model_location(
                            input_location.root,
                            *input_location.path,
                            "product_use_id",
                        ),
                    )
                )
            else:
                input_use_owners[input_port.product_use_id] = (
                    transform.id,
                    input_port.id,
                )
            if input_port.product_use_id in record_use_ids:
                problems.append(
                    _problem(
                        "measurement_transform_input_product_use_conflict",
                        "one product-use occurrence cannot be both a transform "
                        "input and a record destination",
                        model_location(
                            input_location.root,
                            *input_location.path,
                            "product_use_id",
                        ),
                    )
                )
            if not producers_by_product.get(input_port.product_id):
                problems.append(
                    _problem(
                        "measurement_transform_input_producer_missing",
                        "measurement transform input product "
                        f"{input_port.product_id.qualified_name!r} has no producer",
                        input_location,
                    )
                )

        for output in transform.outputs:
            output_location = model_location(
                location.root,
                *location.path,
                "outputs",
                output.id,
            )
            key = (transform.id, output.id)
            declared_output_keys.add(key)
            if output.product_id not in products:
                problems.append(
                    _problem(
                        "measurement_transform_output_product_missing",
                        "measurement transform output references unknown product "
                        f"{output.product_id.qualified_name!r}",
                        model_location(
                            output_location.root,
                            *output_location.path,
                            "product_id",
                        ),
                    )
                )
            existing_owner = output_owner_by_product.get(output.product_id)
            if existing_owner is not None:
                duplicate_output_products.add(output.product_id)
                owner_id, owner_role = existing_owner
                problems.append(
                    _problem(
                        "measurement_transform_product_producer_duplicate",
                        f"logical product {output.product_id.qualified_name!r} is "
                        f"produced by both {owner_id.qualified_name!r}/"
                        f"{owner_role!r} and {transform.id.qualified_name!r}/"
                        f"{output.id!r}",
                        output_location,
                    )
                )
            else:
                output_owner_by_product[output.product_id] = key
            expected_use_ids = uses_by_product.get(output.product_id, ())
            if expected_use_ids:
                demanded = True
            if output.product_use_ids != expected_use_ids:
                problems.append(
                    _problem(
                        "measurement_transform_output_product_use_coverage_mismatch",
                        "measurement transform output does not retain every exact "
                        "downstream product-use occurrence",
                        model_location(
                            output_location.root,
                            *output_location.path,
                            "product_use_ids",
                        ),
                    )
                )
            selected_producers = producers_by_output.get(key, ())
            producer = selected_producers[0] if len(selected_producers) == 1 else None
            if (
                producer is None
                or producer.id != output.producer_id
                or producer.product_id != output.product_id
            ):
                problems.append(
                    _problem(
                        "measurement_transform_output_producer_mismatch",
                        "measurement transform output does not have one matching "
                        "producer declaration",
                        output_location,
                    )
                )
        if transform.outputs and not demanded:
            problems.append(
                _problem(
                    "measurement_transform_not_demanded",
                    "typed measurement transforms must be reachable from at least "
                    "one exact downstream product use",
                    location,
                )
            )

    for key, selected in producers_by_output.items():
        if key in declared_output_keys:
            continue
        producer = selected[0]
        problems.append(
            _problem(
                "measurement_transform_product_producer_orphan",
                "measurement transform product producer references an unknown "
                "transform output",
                model_location(
                    "measurement_transform_product_producers",
                    producer.id.qualified_name,
                ),
            )
        )

    if duplicate_transform_ids or duplicate_output_products:
        return transforms, tuple(problems)
    ordered, order_problems = _order_typed_measurement_transforms(
        transforms,
        output_owner_by_product,
    )
    problems.extend(order_problems)
    return ordered, tuple(problems)


def _order_typed_measurement_transforms(
    transforms: tuple[TypedMeasurementTransform, ...],
    output_owner_by_product: Mapping[
        ProductId,
        tuple[MeasurementTransformId, str],
    ],
) -> tuple[tuple[TypedMeasurementTransform, ...], tuple[Problem, ...]]:
    """Return deterministic producer-before-consumer transform order."""

    by_id = {transform.id: transform for transform in transforms}
    dependencies: dict[MeasurementTransformId, set[MeasurementTransformId]] = {
        transform.id: set() for transform in transforms
    }
    dependants: dict[MeasurementTransformId, set[MeasurementTransformId]] = {
        transform.id: set() for transform in transforms
    }
    for transform in transforms:
        for input_port in transform.inputs:
            owner = output_owner_by_product.get(input_port.product_id)
            if owner is None:
                continue
            owner_id, _owner_role = owner
            dependencies[transform.id].add(owner_id)
            dependants[owner_id].add(transform.id)

    ordinal = {transform.id: index for index, transform in enumerate(transforms)}
    ready = [
        (transform_id.qualified_name, ordinal[transform_id], transform_id)
        for transform_id, owners in dependencies.items()
        if not owners
    ]
    heapq.heapify(ready)
    ordered: list[TypedMeasurementTransform] = []
    while ready:
        _name, _ordinal, transform_id = heapq.heappop(ready)
        ordered.append(by_id[transform_id])
        for dependant in sorted(
            dependants[transform_id],
            key=lambda item: item.qualified_name,
        ):
            dependencies[dependant].discard(transform_id)
            if not dependencies[dependant]:
                heapq.heappush(
                    ready,
                    (
                        dependant.qualified_name,
                        ordinal[dependant],
                        dependant,
                    ),
                )
    if len(ordered) == len(transforms):
        return tuple(ordered), ()
    cycle_ids = tuple(
        sorted(
            (transform_id for transform_id, owners in dependencies.items() if owners),
            key=lambda item: item.qualified_name,
        )
    )
    first = cycle_ids[0]
    return (
        transforms,
        (
            _problem(
                "measurement_transform_cycle",
                "typed measurement transform graph contains a dependency cycle: "
                + ", ".join(item.qualified_name for item in cycle_ids),
                model_location(
                    "measurement_transforms",
                    first.qualified_name,
                ),
            ),
        ),
    )


def _problem(code: str, message: str, location: ModelLocation) -> Problem:
    return compiler_problem(
        code,
        message,
        location,
        phase=ProblemPhase.AUTHORING,
    )
