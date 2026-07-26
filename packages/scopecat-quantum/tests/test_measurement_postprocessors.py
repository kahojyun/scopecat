from __future__ import annotations

import math
from typing import Literal

import pytest
from pydantic import ValidationError
from scopecat import MeasurementPostprocessor, Quantity
from scopecat.measurements.results import ComplexQuantity, MeasurementArray

from scopecat_quantum.measurement_postprocessors import (
    BinaryIqDiscriminator,
    IqCentroid,
    binary_iq_probability_postprocessor,
)


def _discriminator(
    *,
    tie_policy: Literal["state_0", "state_1"] = "state_0",
) -> BinaryIqDiscriminator:
    return BinaryIqDiscriminator(
        state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
        state_1_centroid=IqCentroid(real=1.0, imag=0.0),
        tie_policy=tie_policy,
    )


def _iq_shots(*values: complex) -> MeasurementArray:
    return MeasurementArray(
        dtype="complex128",
        unit="ratio",
        shape=[len(values)],
        values=[
            ComplexQuantity(real=value.real, imag=value.imag, unit="ratio")
            for value in values
        ],
    )


def test_binary_iq_discriminator_requires_finite_distinct_centroids() -> None:
    with pytest.raises(ValidationError, match="must be distinct"):
        BinaryIqDiscriminator(
            state_0_centroid=IqCentroid(real=0.0, imag=0.0),
            state_1_centroid=IqCentroid(real=0.0, imag=0.0),
        )
    with pytest.raises(ValidationError, match="must be finite"):
        IqCentroid(real=math.inf, imag=0.0)


@pytest.mark.parametrize(
    ("tie_policy", "expected"),
    [
        ("state_0", (0.75, 0.25)),
        ("state_1", (0.5, 0.5)),
    ],
)
def test_binary_iq_postprocessor_classifies_one_point(
    tie_policy: Literal["state_0", "state_1"],
    expected: tuple[float, float],
) -> None:
    postprocessor = binary_iq_probability_postprocessor(
        "discriminate",
        iq_shots="iq",
        probability_0="p0",
        probability_1="p1",
        discriminator=_discriminator(tie_policy=tie_policy),
    )

    assert isinstance(postprocessor, MeasurementPostprocessor)
    assert postprocessor.input_binding.qualified_name == "iq"
    assert tuple(
        (role, product_id.qualified_name)
        for role, product_id in postprocessor.output_bindings
    ) == (("probability_0", "p0"), ("probability_1", "p1"))

    outputs = postprocessor.kernel(
        _iq_shots(-1.0 + 0.0j, -0.8 + 0.0j, 1.0 + 0.0j, 0.0 + 0.0j)
    )
    assert outputs == {
        "probability_0": Quantity(expected[0], "ratio"),
        "probability_1": Quantity(expected[1], "ratio"),
    }


def test_binary_iq_postprocessor_rejects_non_iq_input() -> None:
    postprocessor = binary_iq_probability_postprocessor(
        "discriminate",
        iq_shots="iq",
        probability_0="p0",
        probability_1="p1",
        discriminator=_discriminator(),
    )

    with pytest.raises(TypeError, match="MeasurementArray"):
        postprocessor.kernel(Quantity(0.0, "ratio"))
