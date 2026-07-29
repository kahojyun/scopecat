"""Resonator extraction and configuration proposal for flux spectroscopy."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

import scopecat as sc
from instrument_demo.configuration import (
    RESONANCE_FREQUENCY_PARAMETER_ID,
    RESONATOR_LINEWIDTH_PARAMETER_ID,
)
from scopecat.records.measurement import (
    ComplexComponents,
    MeasurementArray,
    MeasurementRecord,
    MeasurementScalar,
)

FLUX_SPECTROSCOPY_ANALYSIS_ID = "instrument_demo.flux_spectroscopy.analysis"
FLUX_SPECTROSCOPY_PROPOSAL_ID = "readout-resonator-fit"
_FIT_MODEL_ID = "instrument_demo.notch_half_depth.v1"


@dataclass(frozen=True, slots=True)
class ResonatorTraceFit:
    """One magnitude-notch fit at a fixed DC bias."""

    dc_bias: sc.Quantity
    temperature: sc.Quantity
    resonance_frequency: sc.Quantity
    linewidth: sc.Quantity
    baseline_power: float
    minimum_power: float

    @property
    def quality_factor(self) -> float:
        return _quantity_value(self.resonance_frequency, "Hz") / _quantity_value(
            self.linewidth,
            "Hz",
        )


def fit_resonator_trace(
    frequencies_hz: Sequence[float],
    samples: Sequence[ComplexComponents],
    *,
    dc_bias: sc.Quantity,
    temperature: sc.Quantity,
) -> ResonatorTraceFit:
    """Extract a notch center and loaded linewidth from one complex trace."""

    frequency_hz = tuple(float(value) for value in frequencies_hz)
    complex_samples = tuple(complex(value.real, value.imag) for value in samples)
    if len(frequency_hz) != len(complex_samples):
        raise ValueError("frequency and S-parameter arrays must have equal length")
    if len(frequency_hz) < 7:
        raise ValueError("resonator fitting requires at least seven frequency points")
    if any(right <= left for left, right in pairwise(frequency_hz)):
        raise ValueError("resonator frequencies must be strictly increasing")

    power = tuple(abs(value) ** 2 for value in complex_samples)
    minimum_index = min(range(len(power)), key=power.__getitem__)
    if minimum_index in {0, len(power) - 1}:
        raise ValueError("resonance minimum lies on the sweep boundary")

    baseline_count = max(3, len(power) // 10)
    baseline_power = sum(sorted(power, reverse=True)[:baseline_count]) / baseline_count
    minimum_power = power[minimum_index]
    depth = baseline_power - minimum_power
    if depth <= max(1.0e-12, baseline_power * 1.0e-4):
        raise ValueError("trace does not contain a resolved resonance notch")

    half_depth = minimum_power + depth / 2.0
    left_crossing = _left_crossing(
        frequency_hz,
        power,
        minimum_index=minimum_index,
        target=half_depth,
    )
    right_crossing = _right_crossing(
        frequency_hz,
        power,
        minimum_index=minimum_index,
        target=half_depth,
    )
    linewidth_hz = right_crossing - left_crossing
    if not math.isfinite(linewidth_hz) or linewidth_hz <= 0:
        raise ValueError("fitted resonator linewidth must be positive")

    resonance_hz = _parabolic_minimum(frequency_hz, power, minimum_index)
    return ResonatorTraceFit(
        dc_bias=dc_bias.to("V"),
        temperature=temperature.to("K"),
        resonance_frequency=sc.Quantity(resonance_hz, "Hz"),
        linewidth=sc.Quantity(linewidth_hz, "Hz"),
        baseline_power=baseline_power,
        minimum_power=minimum_power,
    )


def fit_flux_spectroscopy(
    records: Sequence[MeasurementRecord],
) -> tuple[ResonatorTraceFit, ...]:
    """Fit every persisted bias point in one spectroscopy dataset."""

    if not records:
        raise ValueError("flux spectroscopy analysis requires measurement records")
    return tuple(_fit_record(record) for record in records)


@sc.analysis_step(id=FLUX_SPECTROSCOPY_ANALYSIS_ID)
def flux_spectroscopy_analysis(context: sc.AnalysisContext) -> sc.Analysis:
    """Fit the resonator curve and propose reviewed readout parameters."""

    measurements = context.data.measurements()
    fits = fit_flux_spectroscopy(measurements.dataset.records)
    sweet_spot = max(
        fits,
        key=lambda fit: _quantity_value(fit.resonance_frequency, "Hz"),
    )
    fit_rows = [_fit_row(fit) for fit in fits]
    selected_row = {
        **_fit_row(sweet_spot),
        "selection": "maximum fitted resonance frequency",
    }
    return (
        context.result("Resonator flux spectroscopy")
        .input(
            measurements.dataset_entry.id,
            role="fit-input",
            title="Flux spectroscopy measurements",
        )
        .table(fit_rows, title="Resonator fit by DC bias")
        .table([selected_row], title="Selected readout sweet spot")
        .figure(
            {
                "kind": "resonator_flux_map",
                "x": "dc_bias",
                "y": "frequency",
                "color": "s_parameter_magnitude",
                "source_dataset": measurements.dataset_entry.id,
                "fit_model": _FIT_MODEL_ID,
            },
            title="Resonator frequency versus flux bias",
        )
        .propose(
            FLUX_SPECTROSCOPY_PROPOSAL_ID,
            sc.replace_scalar_parameter(
                RESONANCE_FREQUENCY_PARAMETER_ID,
                sweet_spot.resonance_frequency,
            ),
            sc.replace_scalar_parameter(
                RESONATOR_LINEWIDTH_PARAMETER_ID,
                sweet_spot.linewidth,
            ),
            reason=(
                "Use the maximum-frequency flux sweet spot from the fitted S21 "
                "notch: "
                f"f0={_quantity_value(sweet_spot.resonance_frequency, 'GHz'):.6f} "
                f"GHz, linewidth={_quantity_value(sweet_spot.linewidth, 'MHz'):.6f} "
                "MHz."
            ),
        )
    )


def _fit_record(record: MeasurementRecord) -> ResonatorTraceFit:
    try:
        dc_bias = record.coordinates["dc_bias"]
        frequency = record.observables["frequency"]
        s_parameter = record.observables["s_parameter"]
        temperature = record.observables["temperature"]
    except KeyError as error:
        raise ValueError(
            "run does not contain the flux-spectroscopy measurement schema"
        ) from error
    if not isinstance(dc_bias, MeasurementScalar):
        raise TypeError("dc_bias coordinates must be measurement scalars")
    if not isinstance(temperature, MeasurementScalar):
        raise TypeError("temperature observations must be measurement scalars")
    frequencies = _numeric_array(frequency, dtype="float64", unit="Hz")
    samples = _complex_array(s_parameter, unit="ratio")
    return fit_resonator_trace(
        frequencies,
        samples,
        dc_bias=_measurement_quantity(dc_bias, "dc_bias"),
        temperature=_measurement_quantity(temperature, "temperature"),
    )


def _numeric_array(
    value: object,
    *,
    dtype: str,
    unit: str,
) -> tuple[float, ...]:
    if not isinstance(value, MeasurementArray):
        raise TypeError("frequency observations must be measurement arrays")
    if value.dtype != dtype or value.unit != unit or len(value.shape) != 1:
        raise TypeError("frequency observations have the wrong array contract")
    selected: list[float] = []
    for item in value.values:
        if isinstance(item, bool) or not isinstance(item, int | float):
            raise TypeError("frequency array leaves must be numeric")
        selected.append(float(item))
    return tuple(selected)


def _complex_array(
    value: object,
    *,
    unit: str,
) -> tuple[ComplexComponents, ...]:
    if not isinstance(value, MeasurementArray):
        raise TypeError("S-parameter observations must be measurement arrays")
    if value.dtype != "complex128" or value.unit != unit or len(value.shape) != 1:
        raise TypeError("S-parameter observations have the wrong array contract")
    selected: list[ComplexComponents] = []
    for item in value.values:
        if not isinstance(item, ComplexComponents):
            raise TypeError("S-parameter array leaves must be complex components")
        selected.append(item)
    return tuple(selected)


def _measurement_quantity(value: MeasurementScalar, name: str) -> sc.Quantity:
    if (
        value.dtype not in {"float64", "int64"}
        or isinstance(value.value, bool)
        or not isinstance(value.value, int | float)
        or value.unit is None
    ):
        raise TypeError(f"{name} must be a numeric scalar with a unit")
    return sc.Quantity(float(value.value), value.unit)


def _fit_row(fit: ResonatorTraceFit) -> dict[str, object]:
    return {
        "model_id": _FIT_MODEL_ID,
        "dc_bias_v": _quantity_value(fit.dc_bias, "V"),
        "temperature_mK": _quantity_value(fit.temperature, "mK"),
        "resonance_frequency_hz": _quantity_value(fit.resonance_frequency, "Hz"),
        "linewidth_hz": _quantity_value(fit.linewidth, "Hz"),
        "quality_factor": fit.quality_factor,
        "baseline_power": fit.baseline_power,
        "minimum_power": fit.minimum_power,
    }


def _left_crossing(
    x: Sequence[float],
    y: Sequence[float],
    *,
    minimum_index: int,
    target: float,
) -> float:
    for index in range(minimum_index - 1, -1, -1):
        if y[index] >= target:
            return _interpolate_crossing(
                x[index],
                y[index],
                x[index + 1],
                y[index + 1],
                target,
            )
    raise ValueError("resonance left half-depth crossing is outside the sweep")


def _right_crossing(
    x: Sequence[float],
    y: Sequence[float],
    *,
    minimum_index: int,
    target: float,
) -> float:
    for index in range(minimum_index + 1, len(y)):
        if y[index] >= target:
            return _interpolate_crossing(
                x[index - 1],
                y[index - 1],
                x[index],
                y[index],
                target,
            )
    raise ValueError("resonance right half-depth crossing is outside the sweep")


def _interpolate_crossing(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    target: float,
) -> float:
    if y1 == y0:
        return (x0 + x1) / 2.0
    fraction = (target - y0) / (y1 - y0)
    return x0 + min(1.0, max(0.0, fraction)) * (x1 - x0)


def _parabolic_minimum(
    x: Sequence[float],
    y: Sequence[float],
    minimum_index: int,
) -> float:
    left = minimum_index - 1
    right = minimum_index + 1
    spacing_left = x[minimum_index] - x[left]
    spacing_right = x[right] - x[minimum_index]
    if not math.isclose(spacing_left, spacing_right, rel_tol=1.0e-9):
        return x[minimum_index]
    denominator = y[left] - 2.0 * y[minimum_index] + y[right]
    if denominator <= 0:
        return x[minimum_index]
    offset = 0.5 * (y[left] - y[right]) / denominator
    if abs(offset) > 1.0:
        return x[minimum_index]
    return x[minimum_index] + offset * spacing_left


def _quantity_value(value: sc.Quantity, unit: str) -> float:
    selected = float(value.to(unit).value)
    if not math.isfinite(selected):
        raise ValueError("fit quantities must be finite")
    return selected


__all__ = [
    "FLUX_SPECTROSCOPY_ANALYSIS_ID",
    "FLUX_SPECTROSCOPY_PROPOSAL_ID",
    "ResonatorTraceFit",
    "fit_flux_spectroscopy",
    "fit_resonator_trace",
    "flux_spectroscopy_analysis",
]
