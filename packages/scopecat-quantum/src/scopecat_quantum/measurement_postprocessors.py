# pyright: reportPrivateUsage=false
"""Hardware-independent quantum measurement postprocessors."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, cast, override

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, model_validator
from scopecat import (
    ExperimentContext,
    ModuleContext,
    ProductRef,
    RecordRef,
)
from scopecat.authoring._module_results import ProductBundle, _RecordProduct
from scopecat.measurements.results import (
    MeasurementArray,
    MeasurementScalar,
    MeasurementValue,
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


@dataclass(frozen=True, slots=True)
class BinaryIqProbabilityRecords:
    """Typed durable records selected from binary IQ probabilities."""

    probability_0: RecordRef[float]
    probability_1: RecordRef[float]


@dataclass(frozen=True, slots=True)
class BinaryIqProbabilityProducts(ProductBundle[BinaryIqProbabilityRecords]):
    """Typed products emitted by one binary IQ discrimination step."""

    probability_0: ProductRef[float]
    probability_1: ProductRef[float]

    @override
    def _records_internal(
        self,
        record: _RecordProduct,
        /,
    ) -> BinaryIqProbabilityRecords:
        return BinaryIqProbabilityRecords(
            probability_0=record(self.probability_0),
            probability_1=record(self.probability_1),
        )


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

    products = BinaryIqProbabilityProducts(
        probability_0=cast(
            "ProductRef[float]",
            context._product(
                _output_id(output_prefix, "probability_0"),
                dtype="float64",
                unit="ratio",
            ),
        ),
        probability_1=cast(
            "ProductRef[float]",
            context._product(
                _output_id(output_prefix, "probability_1"),
                dtype="float64",
                unit="ratio",
            ),
        ),
    )

    def calculate(value: MeasurementValue) -> dict[str, MeasurementValue]:
        result_0, result_1 = _binary_iq_probability_value(value, discriminator)
        return {
            _PROBABILITY_0_ROLE: result_0,
            _PROBABILITY_1_ROLE: result_1,
        }

    context._postprocess(
        id,
        input=iq_shots,
        outputs={
            _PROBABILITY_0_ROLE: products.probability_0,
            _PROBABILITY_1_ROLE: products.probability_1,
        },
        kernel=calculate,
    )
    return products


def _output_id(prefix: str | None, name: str) -> str:
    return name if prefix is None else f"{prefix}_{name}"


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

    state_0 = complex(
        discriminator.state_0_centroid.real,
        discriminator.state_0_centroid.imag,
    )
    state_1 = complex(
        discriminator.state_1_centroid.real,
        discriminator.state_1_centroid.imag,
    )
    shots = cast("NDArray[np.complex128]", value.values)
    distance_0 = np.square(np.abs(shots - state_0))
    distance_1 = np.square(np.abs(shots - state_1))
    if discriminator.tie_policy == "state_0":
        state_0_count = int(np.count_nonzero(distance_0 <= distance_1))
    else:
        state_0_count = int(np.count_nonzero(distance_0 < distance_1))

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


__all__ = [
    "BinaryIqDiscriminator",
    "BinaryIqProbabilityProducts",
    "BinaryIqProbabilityRecords",
    "IqCentroid",
    "binary_iq_probabilities",
]
