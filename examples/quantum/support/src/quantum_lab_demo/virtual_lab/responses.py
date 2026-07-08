"""Deterministic response functions driven by virtual-device state."""

from __future__ import annotations

from scopecat.instruments import (
    CollectCommand,
    CollectProductRequest,
)
from scopecat.models.parameter import Quantity
from scopecat.results import ComplexQuantity, MeasurementArray, MeasurementValue

from quantum_lab_demo.virtual_lab.devices import VirtualDevice


def record_quantum_measurement(
    *,
    command: CollectCommand,
    readout: VirtualDevice,
    implementation_id: str,
) -> dict[str, MeasurementValue]:
    del readout, implementation_id
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
    qnd_product = _requested_product(command, "qnd_iq")
    if qnd_product is not None:
        round_count = _axis_size(qnd_product, "round")
        shot_count = _axis_size(qnd_product, "shot")
        products["qnd_iq"] = MeasurementArray(
            dtype="complex128",
            unit="ratio",
            shape=[round_count, shot_count],
            values=[
                [
                    ComplexQuantity(
                        real=_observable_value(
                            point_index=command.point_index + round_index,
                            point_count=max(command.point_count, 1),
                            variable_index=24 + shot_index,
                        ),
                        imag=_observable_value(
                            point_index=command.point_index + shot_index,
                            point_count=max(command.point_count, 1),
                            variable_index=32 + round_index,
                        ),
                        unit="ratio",
                    )
                    for shot_index in range(shot_count)
                ]
                for round_index in range(round_count)
            ],
        )
    stabilizer_product = _requested_product(command, "stabilizer_iq")
    if stabilizer_product is not None:
        round_count = _axis_size(stabilizer_product, "round")
        qubit_count = _axis_size(stabilizer_product, "qubit")
        products["stabilizer_iq"] = MeasurementArray(
            dtype="complex128",
            unit="ratio",
            shape=[round_count, qubit_count],
            values=[
                [
                    ComplexQuantity(
                        real=_observable_value(
                            point_index=command.point_index + round_index,
                            point_count=max(command.point_count, 1),
                            variable_index=40 + qubit_index,
                        ),
                        imag=_observable_value(
                            point_index=command.point_index + qubit_index,
                            point_count=max(command.point_count, 1),
                            variable_index=48 + round_index,
                        ),
                        unit="ratio",
                    )
                    for qubit_index in range(qubit_count)
                ]
                for round_index in range(round_count)
            ],
        )
    backend_product = _requested_product(command, "backend_probabilities")
    if backend_product is not None:
        backend_point_count = _axis_size(backend_product, "backend_point")
        products["backend_probabilities"] = MeasurementArray(
            dtype="float64",
            unit="ratio",
            shape=[backend_point_count],
            values=[
                Quantity(
                    value=_observable_value(
                        point_index=backend_index,
                        point_count=max(backend_point_count, 1),
                        variable_index=56,
                    ),
                    unit="ratio",
                )
                for backend_index in range(backend_point_count)
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
