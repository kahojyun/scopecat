"""Canonical integrated-IQ convention shared by target and virtual device."""

from __future__ import annotations

import cmath
import math
from collections.abc import Sequence

INTEGRATED_IQ_SEMANTICS_ID = "reference_lab.integrated_iq.ssb_midpoint.v1"


def integrate_rectangular_iq(
    trace: Sequence[float],
    *,
    start_sample: int,
    sample_count: int,
    sample_rate_hz: float,
    demodulation_frequency_hz: float,
) -> complex:
    """Demodulate at sample centers using exp(-iωt) and SSB amplitude scaling.

    The result retains the trace unit. Non-zero IFs receive a factor of two;
    zero IF retains unity normalization. The rectangular window is averaged by
    its exact sample count.
    """

    normalization = 1.0 if demodulation_frequency_hz == 0.0 else 2.0
    return (
        normalization
        * sum(
            trace[start_sample + index]
            * cmath.exp(
                -1j
                * 2.0
                * math.pi
                * demodulation_frequency_hz
                * (start_sample + index + 0.5)
                / sample_rate_hz
            )
            for index in range(sample_count)
        )
        / sample_count
    )


__all__ = ["INTEGRATED_IQ_SEMANTICS_ID", "integrate_rectangular_iq"]
