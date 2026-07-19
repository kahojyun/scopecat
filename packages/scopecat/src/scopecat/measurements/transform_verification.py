"""Verification and canonical ordering of native transform graphs."""

from __future__ import annotations

import heapq
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import Problem, ProblemCategory, model_location
from scopecat.kernel.product_identity import ProductUseId
from scopecat.measurements.transform_model import (
    MeasurementTransformDef,
    NativeMeasurementTransformId,
)
from scopecat.measurements.values import (
    MeasurementValueCatalog,
    measurement_value_contract_fingerprint,
)


@dataclass(frozen=True, slots=True)
class VerifiedMeasurementTransformGraph:
    """Closed typed DAG with canonical topological node order."""

    catalog: MeasurementValueCatalog = field(repr=False)
    transforms: tuple[MeasurementTransformDef, ...]
    catalog_fingerprint: str = field(init=False)
    contract_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        transforms, catalog_fingerprint, contract_fingerprint = (
            _validate_measurement_transform_components(
                self.catalog,
                self.transforms,
            )
        )
        object.__setattr__(self, "transforms", transforms)
        object.__setattr__(
            self,
            "catalog_fingerprint",
            catalog_fingerprint,
        )
        object.__setattr__(self, "contract_fingerprint", contract_fingerprint)


def verify_measurement_transform_graph(
    catalog: MeasurementValueCatalog,
    transforms: Sequence[MeasurementTransformDef],
) -> VerifiedMeasurementTransformGraph:
    """Close a typed transform DAG without choosing a runtime implementation."""

    return VerifiedMeasurementTransformGraph(catalog, tuple(transforms))


def _validate_measurement_transform_components(
    catalog: MeasurementValueCatalog,
    transforms: Sequence[MeasurementTransformDef],
) -> tuple[tuple[MeasurementTransformDef, ...], str, str]:
    """Validate and canonicalize the components stored by a verified graph."""

    supplied = tuple(transforms)

    problems: list[Problem] = []
    declarations = supplied

    uses_by_id = {use.id: use for use in catalog.product_uses}
    products_by_id = {product.id: product for product in catalog.product_defs}

    transform_counts = Counter(transform.id for transform in declarations)
    for transform_id, count in transform_counts.items():
        if count > 1:
            problems.append(
                _check_problem(
                    "measurement_transform_duplicate",
                    f"measurement transform {transform_id.value!r} is duplicated",
                    path=("transforms", transform_id.value),
                    category=ProblemCategory.CONFLICT,
                )
            )

    owner_by_input: dict[
        ProductUseId,
        tuple[NativeMeasurementTransformId, str],
    ] = {}
    owner_by_output: dict[ProductUseId, NativeMeasurementTransformId] = {}
    for transform_index, transform in enumerate(declarations):
        if not transform.outputs:
            problems.append(
                _check_problem(
                    "measurement_transform_outputs_empty",
                    f"measurement transform {transform.id.value!r} has no outputs",
                    path=("transforms", transform_index, "outputs"),
                )
            )
        elif not any(port.product_use_ids for port in transform.outputs):
            problems.append(
                _check_problem(
                    "measurement_transform_outputs_undemanded",
                    f"measurement transform {transform.id.value!r} has no "
                    "demanded output slots",
                    path=("transforms", transform_index, "outputs"),
                )
            )
        for direction, ports in (
            ("inputs", transform.inputs),
            ("outputs", transform.outputs),
        ):
            port_counts = Counter(port.id for port in ports)
            for port_id, count in port_counts.items():
                if count > 1:
                    problems.append(
                        _check_problem(
                            "measurement_transform_port_duplicate",
                            f"measurement transform {transform.id.value!r} repeats "
                            f"{direction[:-1]} port {port_id!r}",
                            path=(
                                "transforms",
                                transform_index,
                                direction,
                                port_id,
                            ),
                            category=ProblemCategory.CONFLICT,
                        )
                    )
        for port_index, port in enumerate(transform.inputs):
            existing_input_owner = owner_by_input.get(port.product_use_id)
            if existing_input_owner is not None:
                owner_id, owner_port_id = existing_input_owner
                problems.append(
                    _check_problem(
                        "measurement_transform_input_owner_duplicate",
                        f"product use {port.product_use_id.value!r} is consumed by "
                        f"both transform {owner_id.value!r}/{owner_port_id!r} and "
                        f"{transform.id.value!r}/{port.id!r}",
                        path=(
                            "transforms",
                            transform_index,
                            "inputs",
                            port_index,
                            "product_use_id",
                        ),
                        category=ProblemCategory.CONFLICT,
                    )
                )
            else:
                owner_by_input[port.product_use_id] = (transform.id, port.id)
            use = uses_by_id.get(port.product_use_id)
            if use is None:
                problems.append(
                    _check_problem(
                        "measurement_transform_product_use_missing",
                        f"measurement transform input {port.id!r} references "
                        f"unknown product use {port.product_use_id.value!r}",
                        path=(
                            "transforms",
                            transform_index,
                            "inputs",
                            port_index,
                            "product_use_id",
                        ),
                        category=ProblemCategory.NOT_FOUND,
                    )
                )
                continue
            expected_product = products_by_id.get(use.product_id)
            if expected_product is None:
                problems.append(
                    _check_problem(
                        "measurement_transform_product_missing",
                        f"measurement transform input {port.id!r} references "
                        "a product use without a definition",
                        path=(
                            "transforms",
                            transform_index,
                            "inputs",
                            port_index,
                            "product",
                        ),
                        category=ProblemCategory.NOT_FOUND,
                    )
                )
            elif port.product != expected_product:
                problems.append(
                    _check_problem(
                        "measurement_transform_product_contract_mismatch",
                        f"measurement transform input {port.id!r} does not retain "
                        "the exact linked product contract",
                        path=(
                            "transforms",
                            transform_index,
                            "inputs",
                            port_index,
                            "product",
                        ),
                        category=ProblemCategory.CONFLICT,
                    )
                )
        for port_index, port in enumerate(transform.outputs):
            expected_product = products_by_id.get(port.product.id)
            if expected_product is None:
                problems.append(
                    _check_problem(
                        "measurement_transform_product_missing",
                        f"measurement transform output {port.id!r} references "
                        "an unknown product definition",
                        path=(
                            "transforms",
                            transform_index,
                            "outputs",
                            port_index,
                            "product",
                        ),
                        category=ProblemCategory.NOT_FOUND,
                    )
                )
            elif port.product != expected_product:
                problems.append(
                    _check_problem(
                        "measurement_transform_product_contract_mismatch",
                        f"measurement transform output {port.id!r} does not retain "
                        "the exact linked product contract",
                        path=(
                            "transforms",
                            transform_index,
                            "outputs",
                            port_index,
                            "product",
                        ),
                        category=ProblemCategory.CONFLICT,
                    )
                )
            for use_index, use_id in enumerate(port.product_use_ids):
                use = uses_by_id.get(use_id)
                if use is None:
                    problems.append(
                        _check_problem(
                            "measurement_transform_product_use_missing",
                            f"measurement transform output {port.id!r} references "
                            f"unknown product use {use_id.value!r}",
                            path=(
                                "transforms",
                                transform_index,
                                "outputs",
                                port_index,
                                "product_use_ids",
                                use_index,
                            ),
                            category=ProblemCategory.NOT_FOUND,
                        )
                    )
                    continue
                if use.product_id != port.product.id:
                    problems.append(
                        _check_problem(
                            "measurement_transform_product_use_mismatch",
                            f"measurement transform output {port.id!r} contains "
                            "a use of another logical product",
                            path=(
                                "transforms",
                                transform_index,
                                "outputs",
                                port_index,
                                "product_use_ids",
                                use_index,
                            ),
                            category=ProblemCategory.CONFLICT,
                        )
                    )
                existing = owner_by_output.get(use_id)
                if existing is not None:
                    problems.append(
                        _check_problem(
                            "measurement_transform_output_owner_duplicate",
                            f"product use {use_id.value!r} is output by transforms "
                            f"{existing.value!r} and {transform.id.value!r}",
                            path=(
                                "transforms",
                                transform_index,
                                "outputs",
                                port_index,
                            ),
                            category=ProblemCategory.CONFLICT,
                        )
                    )
                else:
                    owner_by_output[use_id] = transform.id

    canonical = _canonical_topological_order(declarations, owner_by_output)
    if canonical is None:
        problems.append(
            _check_problem(
                "measurement_transform_cycle",
                "measurement transform graph contains a dependency cycle",
                path=("transforms",),
                category=ProblemCategory.CONFLICT,
            )
        )
    if problems:
        raise CheckFailed(problems)
    if canonical is None:
        raise AssertionError("successful transform verification lost topology")

    selected = canonical
    catalog_fingerprint = measurement_value_contract_fingerprint(catalog)
    contract_fingerprint = _graph_contract_fingerprint(
        catalog_fingerprint,
        selected,
    )
    return selected, catalog_fingerprint, contract_fingerprint


def _canonical_topological_order(
    transforms: Sequence[MeasurementTransformDef],
    owner_by_output: Mapping[ProductUseId, NativeMeasurementTransformId],
) -> tuple[MeasurementTransformDef, ...] | None:
    by_id: dict[NativeMeasurementTransformId, MeasurementTransformDef] = {}
    for transform in transforms:
        by_id.setdefault(transform.id, transform)
    dependencies: dict[
        NativeMeasurementTransformId,
        set[NativeMeasurementTransformId],
    ] = {transform_id: set() for transform_id in by_id}
    dependants: dict[
        NativeMeasurementTransformId,
        set[NativeMeasurementTransformId],
    ] = {transform_id: set() for transform_id in by_id}
    for transform_id, transform in by_id.items():
        for port in transform.inputs:
            owner = owner_by_output.get(port.product_use_id)
            if owner is None or owner not in by_id:
                continue
            dependencies[transform_id].add(owner)
            dependants[owner].add(transform_id)
    ready = [
        (transform_id.value, transform_id)
        for transform_id, owners in dependencies.items()
        if not owners
    ]
    heapq.heapify(ready)
    ordered: list[MeasurementTransformDef] = []
    while ready:
        _name, transform_id = heapq.heappop(ready)
        ordered.append(by_id[transform_id])
        for dependant in sorted(
            dependants[transform_id],
            key=lambda item: item.value,
        ):
            dependencies[dependant].discard(transform_id)
            if not dependencies[dependant]:
                heapq.heappush(ready, (dependant.value, dependant))
    if len(ordered) != len(by_id):
        return None
    return tuple(ordered)


def _graph_contract_fingerprint(
    catalog_fingerprint: str,
    transforms: Sequence[MeasurementTransformDef],
) -> str:
    return stable_content_hash(
        content_fingerprint(
            {
                "schema": "scopecat.measurement_transform_graph.v1",
                "catalog_fingerprint": catalog_fingerprint,
                "transforms": tuple(transforms),
            }
        )
    )


def _check_problem(
    code: str,
    message: str,
    *,
    path: tuple[str | int, ...],
    category: ProblemCategory = ProblemCategory.INVALID_INPUT,
    details: Mapping[str, object] | None = None,
) -> Problem:
    return compiler_problem(
        code,
        message,
        model_location("measurement_transforms", *path),
        category=category,
        details=details,
    )
