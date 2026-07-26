"""Deterministic response functions driven by virtual-device state."""

from __future__ import annotations

from scopecat.measurements.results import (
    ComplexQuantity,
    MeasurementArray,
    MeasurementValue,
)
from scopecat.records.parameter import Quantity
from scopecat.sdk.instruments import (
    CollectCommand,
    CollectProductRequest,
)


def record_quantum_measurement(
    *,
    command: CollectCommand,
) -> dict[str, MeasurementValue]:
    requested_keys = {request.id for request in command.requests}
    products: dict[str, MeasurementValue] = {}
    scalar_products = [
        ("probability_0", "ratio"),
        ("probability_1", "ratio"),
        ("state0_iq_stdev", "ratio"),
        ("state1_iq_stdev", "ratio"),
    ]
    for variable_index, (product_key, unit) in enumerate(scalar_products):
        if product_key not in requested_keys:
            continue
        products[product_key] = Quantity(
            value=_observable_value(
                point_index=command.point_index,
                point_count=command.point_count,
                variable_index=variable_index,
            ),
            unit=unit,
        )
    multiplexed_product = _requested_product(command, "multiplexed_iq")
    if multiplexed_product is not None:
        products["multiplexed_iq"] = MeasurementArray(
            dtype="complex128",
            unit="ratio",
            shape=[_axis_size(multiplexed_product, "qubit")],
            values=[
                ComplexQuantity(
                    real=_observable_value(
                        point_index=command.point_index,
                        point_count=command.point_count,
                        variable_index=8 + entity_index,
                    ),
                    imag=_observable_value(
                        point_index=command.point_index,
                        point_count=command.point_count,
                        variable_index=16 + entity_index,
                    ),
                    unit="ratio",
                )
                for entity_index in range(_axis_size(multiplexed_product, "qubit"))
            ],
        )
    complex_products = ["raw_iq", "state0_iq", "state1_iq"]
    for variable_index, product_key in enumerate(
        complex_products,
        start=len(scalar_products),
    ):
        if product_key not in requested_keys:
            continue
        real = _observable_value(
            point_index=command.point_index,
            point_count=command.point_count,
            variable_index=variable_index,
        )
        imag = _observable_value(
            point_index=command.point_index,
            point_count=command.point_count,
            variable_index=variable_index + len(complex_products),
        )
        products[product_key] = ComplexQuantity(real=real, imag=imag, unit="ratio")
    return products


def _requested_product(
    command: CollectCommand,
    product_key: str,
) -> CollectProductRequest | None:
    for request in command.requests:
        if request.id == product_key:
            return request
    return None


def _axis_size(product: CollectProductRequest, axis_id: str) -> int:
    for dimension in product.dimensions:
        if dimension.id == axis_id:
            return dimension.size
    return 1


def _observable_value(
    *,
    point_index: int,
    point_count: int,
    variable_index: int,
) -> float:
    normalized = (point_index + 1) / (point_count + 1)
    return round(normalized + variable_index * 0.01, 12)


__all__ = [
    "record_quantum_measurement",
]
