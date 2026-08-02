"""Hardware-independent quantum measurement postprocessors."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator
from scopecat import ProductRef
from scopecat.measurements.results import (
    ComplexComponents,
    MeasurementArray,
    MeasurementScalar,
    MeasurementValue,
)
from scopecat.program.measurements import (
    MeasurementPostprocessor,
    measurement_postprocessor,
)

_PROBABILITY_0_ROLE = "probability_0"
_PROBABILITY_1_ROLE = "probability_1"


class IqCentroid(BaseModel):
    """One finite centroid in dimensionless integrated-IQ space."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    real: float
    imag: float
    unit: Literal["ratio"] = "ratio"

    @model_validator(mode="after")
    def validate_finite(self) -> IqCentroid:
        if not (math.isfinite(self.real) and math.isfinite(self.imag)):
            raise ValueError("binary IQ discriminator centroids must be finite")
        return self


class BinaryIqDiscriminator(BaseModel):
    """Nearest-centroid classification for binary integrated-IQ shots."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state_0_centroid: IqCentroid
    state_1_centroid: IqCentroid
    tie_policy: Literal["state_0", "state_1"] = "state_0"

    @model_validator(mode="after")
    def validate_distinct_centroids(self) -> BinaryIqDiscriminator:
        state_0 = self.state_0_centroid
        state_1 = self.state_1_centroid
        if state_0.real == state_1.real and state_0.imag == state_1.imag:
            raise ValueError("binary IQ discriminator centroids must be distinct")
        return self


def binary_iq_probability_postprocessor(
    postprocessor_id: str,
    *,
    iq_shots: str | ProductRef,
    probability_0: str | ProductRef,
    probability_1: str | ProductRef,
    discriminator: BinaryIqDiscriminator,
) -> MeasurementPostprocessor:
    """Calculate binary state probabilities independently at each scan point."""

    if not postprocessor_id:
        raise ValueError("binary IQ probability postprocessor ids must be non-empty")
    products = (iq_shots, probability_0, probability_1)
    if any(isinstance(product, str) and not product for product in products):
        raise ValueError("binary IQ product ids must be non-empty")
    product_ids = tuple(
        product.product_id if isinstance(product, ProductRef) else product
        for product in products
    )
    if len(set(product_ids)) != len(product_ids):
        raise ValueError("binary IQ probability products must be distinct")

    def calculate(value: MeasurementValue) -> dict[str, MeasurementValue]:
        result_0, result_1 = _binary_iq_probability_value(value, discriminator)
        return {
            _PROBABILITY_0_ROLE: result_0,
            _PROBABILITY_1_ROLE: result_1,
        }

    return measurement_postprocessor(
        postprocessor_id,
        input=iq_shots,
        outputs={
            _PROBABILITY_0_ROLE: probability_0,
            _PROBABILITY_1_ROLE: probability_1,
        },
        kernel=calculate,
    )


def _binary_iq_probability_value(
    value: MeasurementValue,
    discriminator: BinaryIqDiscriminator,
) -> tuple[MeasurementScalar, MeasurementScalar]:
    if not isinstance(value, MeasurementArray):
        raise TypeError("binary IQ postprocessor requires a MeasurementArray")
    if value.dtype != "complex128" or value.unit != "ratio" or len(value.shape) != 1:
        raise ValueError(
            "binary IQ postprocessor requires complex128 ratio [shot] values"
        )
    if value.shape[0] <= 0:
        raise ValueError("binary IQ postprocessor requires at least one shot")

    state_0_count = 0
    for shot in value.values:
        if not isinstance(shot, ComplexComponents):
            raise TypeError("binary IQ postprocessor requires complex shot leaves")
        if _classify_shot(shot, discriminator) == 0:
            state_0_count += 1

    probability_0 = state_0_count / len(value.values)
    return (
        MeasurementScalar.create(
            dtype="float64",
            value=probability_0,
            unit="ratio",
        ),
        MeasurementScalar.create(
            dtype="float64",
            value=1.0 - probability_0,
            unit="ratio",
        ),
    )


def _classify_shot(
    shot: ComplexComponents,
    discriminator: BinaryIqDiscriminator,
) -> Literal[0, 1]:
    state_0 = discriminator.state_0_centroid
    state_1 = discriminator.state_1_centroid
    distance_0 = (shot.real - state_0.real) ** 2 + (shot.imag - state_0.imag) ** 2
    distance_1 = (shot.real - state_1.real) ** 2 + (shot.imag - state_1.imag) ** 2
    if distance_0 < distance_1:
        return 0
    if distance_1 < distance_0:
        return 1
    return 0 if discriminator.tie_policy == "state_0" else 1


__all__ = [
    "BinaryIqDiscriminator",
    "IqCentroid",
    "binary_iq_probability_postprocessor",
]
