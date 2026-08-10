# pyright: reportPrivateUsage=false
"""Hardware-independent quantum measurement postprocessors."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, cast

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, model_validator
from scopecat import (
    ExperimentContext,
    ModuleContext,
    ProductRef,
    QuantityType,
    ScalarType,
)
from scopecat.authoring._module_results import ProductBundle
from scopecat.program.products import ProductRefs


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


@dataclass(frozen=True, slots=True)
class BinaryIqProbabilityProducts(ProductBundle):
    """Typed products emitted by one binary IQ discrimination step."""

    probability_0: ProductRef[float]
    probability_1: ProductRef[float]


def binary_iq_probabilities(
    context: ModuleContext | ExperimentContext,
    iq_shots: ProductRef,
    /,
    *,
    discriminator: BinaryIqDiscriminator,
    id: str = "binary-iq-probability",
    output_prefix: str | None = None,
) -> BinaryIqProbabilityProducts:
    """Declare binary state probabilities independently at each scan point."""

    probability_0_id = _output_id(output_prefix, "probability_0")
    probability_1_id = _output_id(output_prefix, "probability_1")

    def calculate(*, iq_shots: object) -> dict[str, float]:
        result_0, result_1 = _binary_iq_probability_value(
            np.asarray(iq_shots),
            discriminator,
        )
        return {
            probability_0_id: result_0,
            probability_1_id: result_1,
        }

    computed = context.compute(
        id,
        fn=calculate,
        inputs={"iq_shots": iq_shots},
        output_type={
            probability_0_id: ScalarType(QuantityType(unit="ratio")),
            probability_1_id: ScalarType(QuantityType(unit="ratio")),
        },
    )
    if not isinstance(computed, ProductRefs):
        raise AssertionError("structured measurement compute must return products")
    return BinaryIqProbabilityProducts(
        probability_0=cast("ProductRef[float]", computed[probability_0_id]),
        probability_1=cast("ProductRef[float]", computed[probability_1_id]),
    )


def _output_id(prefix: str | None, name: str) -> str:
    return name if prefix is None else f"{prefix}_{name}"


def _binary_iq_probability_value(
    value: NDArray[np.generic],
    discriminator: BinaryIqDiscriminator,
) -> tuple[float, float]:
    if value.dtype != np.dtype("complex128") or value.ndim != 1:
        raise ValueError("binary IQ compute requires complex128 [shot] values")
    if value.shape[0] <= 0:
        raise ValueError("binary IQ postprocessor requires at least one shot")

    state_0 = complex(
        discriminator.state_0_centroid.real,
        discriminator.state_0_centroid.imag,
    )
    state_1 = complex(
        discriminator.state_1_centroid.real,
        discriminator.state_1_centroid.imag,
    )
    shots = cast("NDArray[np.complex128]", value)
    distance_0 = np.square(np.abs(shots - state_0))
    distance_1 = np.square(np.abs(shots - state_1))
    if discriminator.tie_policy == "state_0":
        state_0_count = int(np.count_nonzero(distance_0 <= distance_1))
    else:
        state_0_count = int(np.count_nonzero(distance_0 < distance_1))

    probability_0 = state_0_count / len(value)
    return probability_0, 1.0 - probability_0


__all__ = [
    "BinaryIqDiscriminator",
    "BinaryIqProbabilityProducts",
    "IqCentroid",
    "binary_iq_probabilities",
]
