"""Resonator extraction and configuration proposal for flux spectroscopy."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, SupportsFloat, cast

import numpy as np
import scopecat as sc
from numpy.typing import ArrayLike, NDArray
from scipy.optimize import least_squares  # pyright: ignore[reportUnknownVariableType]
from scopecat.measurements.results import Dataset, Trace, Variable

from instrument_demo.configuration import (
    RESONANCE_FREQUENCY_PARAMETER_ID,
    RESONATOR_LINEWIDTH_PARAMETER_ID,
)
from instrument_demo.workflows.flux_spectroscopy import TEMPERATURE_RECORD_ID

FLUX_SPECTROSCOPY_ANALYSIS_ID = "instrument_demo.flux_spectroscopy.analysis"
FLUX_SPECTROSCOPY_PROPOSAL_ID = "readout-resonator-fit"
_FIT_MODEL_ID = "instrument_demo.complex_s21_notch.v1"
_FREQUENCY_SCALE_HZ = 1.0e6
_FIT_TABLE_COLUMNS = (
    sc.AnalysisTableColumn(id="model_id", label="Fit model"),
    sc.AnalysisTableColumn(id="dc_bias_v", label="DC bias", unit="V"),
    sc.AnalysisTableColumn(id="temperature_mK", label="Temperature", unit="mK"),
    sc.AnalysisTableColumn(
        id="resonance_frequency_hz",
        label="Resonance frequency",
        unit="Hz",
    ),
    sc.AnalysisTableColumn(id="linewidth_hz", label="Linewidth", unit="Hz"),
    sc.AnalysisTableColumn(id="quality_factor", label="Quality factor"),
    sc.AnalysisTableColumn(id="baseline_power", label="Baseline power"),
    sc.AnalysisTableColumn(id="minimum_power", label="Minimum power"),
    sc.AnalysisTableColumn(id="complex_rmse", label="Complex RMSE", unit="ratio"),
)


@dataclass(frozen=True, slots=True)
class ResonatorTraceFit:
    """One complex S21 notch fit at a fixed DC bias."""

    dc_bias: sc.Quantity
    temperature: sc.Quantity
    resonance_frequency: sc.Quantity
    linewidth: sc.Quantity
    baseline_power: float
    minimum_power: float
    complex_rmse: float

    @property
    def quality_factor(self) -> float:
        return _quantity_value(self.resonance_frequency, "Hz") / _quantity_value(
            self.linewidth,
            "Hz",
        )


class _LeastSquaresResult(Protocol):
    success: bool
    message: str
    x: NDArray[np.float64]


def fit_resonator_trace(
    frequencies_hz: ArrayLike,
    samples: ArrayLike,
    *,
    dc_bias: sc.Quantity,
    temperature: sc.Quantity,
) -> ResonatorTraceFit:
    """Fit a cable-delay-corrected complex S21 notch response."""

    frequency_hz = np.asarray(frequencies_hz, dtype=np.float64)
    complex_samples = np.asarray(samples, dtype=np.complex128)
    if frequency_hz.ndim != 1 or complex_samples.ndim != 1:
        raise ValueError("frequency and S-parameter inputs must be one-dimensional")
    if frequency_hz.size != complex_samples.size:
        raise ValueError("frequency and S-parameter arrays must have equal length")
    if frequency_hz.size < 7:
        raise ValueError("resonator fitting requires at least seven frequency points")
    if not np.all(np.isfinite(frequency_hz)) or not np.all(
        np.isfinite(complex_samples)
    ):
        raise ValueError("frequency and S-parameter arrays must contain finite values")
    if frequency_hz[0] <= 0.0:
        raise ValueError("resonator frequencies must be positive")
    if np.any(np.diff(frequency_hz) <= 0.0):
        raise ValueError("resonator frequencies must be strictly increasing")

    power = np.abs(complex_samples) ** 2
    smoothed_power = _smooth_power(power)
    minimum_index = int(np.argmin(smoothed_power))
    if minimum_index in {0, power.size - 1}:
        raise ValueError("resonance minimum lies on the sweep boundary")

    baseline_count = max(3, power.size // 10)
    baseline_power = float(
        np.mean(np.partition(power, power.size - baseline_count)[-baseline_count:])
    )
    minimum_power = float(cast("SupportsFloat", smoothed_power[minimum_index]))
    depth = baseline_power - minimum_power
    if depth <= max(1.0e-12, baseline_power * 1.0e-4):
        raise ValueError("trace does not contain a resolved resonance notch")

    half_depth = minimum_power + depth / 2.0
    left_crossing = _left_crossing(
        frequency_hz,
        smoothed_power,
        minimum_index=minimum_index,
        target=half_depth,
    )
    right_crossing = _right_crossing(
        frequency_hz,
        smoothed_power,
        minimum_index=minimum_index,
        target=half_depth,
    )
    initial_linewidth_hz = right_crossing - left_crossing
    initial_resonance_hz = _parabolic_minimum(
        frequency_hz,
        smoothed_power,
        minimum_index,
    )
    frequency_center_hz = float(np.mean(frequency_hz[[0, -1]]))
    frequency_mhz = (frequency_hz - frequency_center_hz) / _FREQUENCY_SCALE_HZ
    initial_parameters = _initial_notch_parameters(
        frequency_mhz,
        complex_samples,
        baseline_power=baseline_power,
        minimum_power=minimum_power,
        resonance_mhz=(initial_resonance_hz - frequency_center_hz)
        / _FREQUENCY_SCALE_HZ,
        linewidth_mhz=initial_linewidth_hz / _FREQUENCY_SCALE_HZ,
    )
    spacing_mhz = float(np.min(np.diff(frequency_mhz)))
    sweep_start_mhz = float(cast("SupportsFloat", frequency_mhz[0]))
    sweep_stop_mhz = float(cast("SupportsFloat", frequency_mhz[-1]))
    sweep_span_mhz = sweep_stop_mhz - sweep_start_mhz
    lower_bounds = np.asarray(
        [sweep_start_mhz, spacing_mhz / 10.0, 1.0e-6, 1.0e-12, -np.inf, -np.inf],
        dtype=np.float64,
    )
    upper_bounds = np.asarray(
        [sweep_stop_mhz, sweep_span_mhz, 1.5, np.inf, np.inf, np.inf],
        dtype=np.float64,
    )
    initial_residual = _notch_residual(
        initial_parameters,
        frequency_mhz,
        complex_samples,
    )
    robust_scale = max(
        1.0e-6,
        0.01 * math.sqrt(baseline_power),
        float(cast("SupportsFloat", np.median(np.abs(initial_residual)))),
    )
    result = cast(
        "_LeastSquaresResult",
        least_squares(
            _notch_residual,
            initial_parameters,
            args=(frequency_mhz, complex_samples),
            bounds=(lower_bounds, upper_bounds),
            loss="soft_l1",
            f_scale=robust_scale,
            x_scale="jac",
            max_nfev=5_000,
        ),
    )
    if not result.success:
        raise ValueError(f"complex resonator fit failed: {result.message}")

    fitted_parameters = result.x
    if not np.all(np.isfinite(fitted_parameters)):
        raise ValueError("complex resonator fit produced non-finite parameters")
    fitted_resonance_mhz = float(cast("SupportsFloat", fitted_parameters[0]))
    fitted_linewidth_mhz = float(cast("SupportsFloat", fitted_parameters[1]))
    fitted_depth = float(cast("SupportsFloat", fitted_parameters[2]))
    fitted_amplitude = float(cast("SupportsFloat", fitted_parameters[3]))
    resonance_hz = frequency_center_hz + fitted_resonance_mhz * _FREQUENCY_SCALE_HZ
    linewidth_hz = fitted_linewidth_mhz * _FREQUENCY_SCALE_HZ
    if resonance_hz <= 0.0 or linewidth_hz <= 0.0:
        raise ValueError(
            "fitted resonance frequency and quality factor must be positive"
        )
    fitted_samples = _notch_response(fitted_parameters, frequency_mhz)
    complex_rmse = float(
        cast(
            "SupportsFloat",
            np.sqrt(np.mean(np.abs(fitted_samples - complex_samples) ** 2)),
        )
    )
    return ResonatorTraceFit(
        dc_bias=dc_bias.to("V"),
        temperature=temperature.to("K"),
        resonance_frequency=sc.Quantity(resonance_hz, "Hz"),
        linewidth=sc.Quantity(linewidth_hz, "Hz"),
        baseline_power=float(fitted_amplitude**2),
        minimum_power=float((fitted_amplitude * (1.0 - fitted_depth)) ** 2),
        complex_rmse=complex_rmse,
    )


def fit_flux_spectroscopy(
    dataset: Dataset,
) -> tuple[ResonatorTraceFit, ...]:
    """Fit every persisted bias point in one spectroscopy dataset."""

    if not dataset:
        raise ValueError("flux spectroscopy analysis requires measurement records")
    try:
        dc_bias = dataset.coords["dc_bias"]
        temperature = dataset.data_vars[TEMPERATURE_RECORD_ID]
    except KeyError as error:
        raise ValueError(
            "run does not contain the flux-spectroscopy measurement schema"
        ) from error
    traces = dataset.traces(group="readout-vna/sweep")
    return tuple(
        _fit_point(dc_bias_value, temperature_value, trace, dc_bias, temperature)
        for trace, dc_bias_value, temperature_value in zip(
            traces,
            dc_bias.values,
            temperature.values,
            strict=True,
        )
    )


@sc.analysis_step(id=FLUX_SPECTROSCOPY_ANALYSIS_ID)
def flux_spectroscopy_analysis(context: sc.AnalysisContext) -> sc.Analysis:
    """Fit the resonator curve and propose reviewed readout parameters."""

    measurements = context.measurements()
    fits = fit_flux_spectroscopy(measurements)
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
            measurements.entry.id,
            role="fit-input",
            title="Flux spectroscopy measurements",
        )
        .table(
            sc.AnalysisTable.from_rows(fit_rows, columns=_FIT_TABLE_COLUMNS),
            title="Resonator fit by DC bias",
        )
        .table(
            sc.AnalysisTable.from_rows(
                [selected_row],
                columns=(
                    *_FIT_TABLE_COLUMNS,
                    sc.AnalysisTableColumn(id="selection", label="Selection"),
                ),
            ),
            title="Selected readout sweet spot",
        )
        .figure(
            sc.AnalysisFigure(
                kind="line",
                x_axis=sc.AnalysisFigureAxis(label="DC bias", unit="V"),
                y_axis=sc.AnalysisFigureAxis(
                    label="Fitted resonance frequency",
                    unit="GHz",
                ),
                series=[
                    sc.AnalysisFigureSeries(
                        id="fitted-resonance",
                        label="Notch fit",
                        x=[_quantity_value(fit.dc_bias, "V") for fit in fits],
                        y=[
                            _quantity_value(fit.resonance_frequency, "GHz")
                            for fit in fits
                        ],
                    )
                ],
            ),
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


def _fit_point(
    dc_bias_value: object,
    temperature_value: object,
    trace: Trace,
    dc_bias: Variable,
    temperature: Variable,
) -> ResonatorTraceFit:
    return fit_resonator_trace(
        trace.x,
        trace.y,
        dc_bias=_variable_quantity(dc_bias, dc_bias_value, "dc_bias"),
        temperature=_variable_quantity(
            temperature,
            temperature_value,
            "temperature",
        ),
    )


def _variable_quantity(variable: Variable, value: object, name: str) -> sc.Quantity:
    if (
        variable.dims != ("point",)
        or variable.dtype not in {"float64", "int64"}
        or variable.unit is None
        or isinstance(value, bool)
        or not isinstance(value, int | float)
    ):
        raise TypeError(f"{name} must be a numeric scalar with a unit")
    return sc.Quantity(float(value), variable.unit)


def _fit_row(fit: ResonatorTraceFit) -> dict[str, sc.AnalysisTableCell]:
    return {
        "model_id": _FIT_MODEL_ID,
        "dc_bias_v": _quantity_value(fit.dc_bias, "V"),
        "temperature_mK": _quantity_value(fit.temperature, "mK"),
        "resonance_frequency_hz": _quantity_value(fit.resonance_frequency, "Hz"),
        "linewidth_hz": _quantity_value(fit.linewidth, "Hz"),
        "quality_factor": fit.quality_factor,
        "baseline_power": fit.baseline_power,
        "minimum_power": fit.minimum_power,
        "complex_rmse": fit.complex_rmse,
    }


def _smooth_power(power: NDArray[np.float64]) -> NDArray[np.float64]:
    padded = np.pad(power, (1, 1), mode="edge")
    return np.convolve(padded, np.full(3, 1.0 / 3.0), mode="valid")


def _initial_notch_parameters(
    frequency_mhz: NDArray[np.float64],
    samples: NDArray[np.complex128],
    *,
    baseline_power: float,
    minimum_power: float,
    resonance_mhz: float,
    linewidth_mhz: float,
) -> NDArray[np.float64]:
    edge_count = max(3, frequency_mhz.size // 10)
    edge_indices = np.concatenate(
        (
            np.arange(edge_count),
            np.arange(frequency_mhz.size - edge_count, frequency_mhz.size),
        )
    )
    edge_frequency = frequency_mhz[edge_indices]
    edge_phase = np.unwrap(np.angle(samples[edge_indices]))
    phase_design = np.column_stack((np.ones_like(edge_frequency), edge_frequency))
    phase_coefficients, _residuals, _rank, _singular_values = np.linalg.lstsq(
        phase_design,
        edge_phase,
        rcond=None,
    )
    amplitude = math.sqrt(baseline_power)
    depth = 1.0 - math.sqrt(max(0.0, minimum_power / baseline_power))
    return np.asarray(
        [
            resonance_mhz,
            linewidth_mhz,
            min(1.49, max(1.0e-5, depth)),
            amplitude,
            float(cast("SupportsFloat", phase_coefficients[0])),
            float(cast("SupportsFloat", phase_coefficients[1])),
        ],
        dtype=np.float64,
    )


def _notch_response(
    parameters: NDArray[np.float64],
    frequency_mhz: NDArray[np.float64],
) -> NDArray[np.complex128]:
    resonance_mhz = float(cast("SupportsFloat", parameters[0]))
    linewidth_mhz = float(cast("SupportsFloat", parameters[1]))
    depth = float(cast("SupportsFloat", parameters[2]))
    amplitude = float(cast("SupportsFloat", parameters[3]))
    phase = float(cast("SupportsFloat", parameters[4]))
    phase_slope = float(cast("SupportsFloat", parameters[5]))
    detuning = 2.0 * (frequency_mhz - resonance_mhz) / linewidth_mhz
    baseline = amplitude * np.exp(1j * (phase + phase_slope * frequency_mhz))
    return np.asarray(
        baseline * (1.0 - depth / (1.0 + 1j * detuning)),
        dtype=np.complex128,
    )


def _notch_residual(
    parameters: NDArray[np.float64],
    frequency_mhz: NDArray[np.float64],
    samples: NDArray[np.complex128],
) -> NDArray[np.float64]:
    residual = _notch_response(parameters, frequency_mhz) - samples
    return np.concatenate((residual.real, residual.imag))


def _left_crossing(
    x: NDArray[np.float64],
    y: NDArray[np.float64],
    *,
    minimum_index: int,
    target: float,
) -> float:
    for index in range(minimum_index - 1, -1, -1):
        if y[index] >= target:
            return _interpolate_crossing(
                float(cast("SupportsFloat", x[index])),
                float(cast("SupportsFloat", y[index])),
                float(cast("SupportsFloat", x[index + 1])),
                float(cast("SupportsFloat", y[index + 1])),
                target,
            )
    raise ValueError("resonance left half-depth crossing is outside the sweep")


def _right_crossing(
    x: NDArray[np.float64],
    y: NDArray[np.float64],
    *,
    minimum_index: int,
    target: float,
) -> float:
    for index in range(minimum_index + 1, len(y)):
        if y[index] >= target:
            return _interpolate_crossing(
                float(cast("SupportsFloat", x[index - 1])),
                float(cast("SupportsFloat", y[index - 1])),
                float(cast("SupportsFloat", x[index])),
                float(cast("SupportsFloat", y[index])),
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
    x: NDArray[np.float64],
    y: NDArray[np.float64],
    minimum_index: int,
) -> float:
    left = minimum_index - 1
    right = minimum_index + 1
    selected_x = tuple(
        float(cast("SupportsFloat", x[index])) for index in (left, minimum_index, right)
    )
    selected_y = tuple(
        float(cast("SupportsFloat", y[index])) for index in (left, minimum_index, right)
    )
    spacing_left = selected_x[1] - selected_x[0]
    spacing_right = selected_x[2] - selected_x[1]
    if not math.isclose(spacing_left, spacing_right, rel_tol=1.0e-9):
        return selected_x[1]
    denominator = selected_y[0] - 2.0 * selected_y[1] + selected_y[2]
    if denominator <= 0:
        return selected_x[1]
    offset = 0.5 * (selected_y[0] - selected_y[2]) / denominator
    if abs(offset) > 1.0:
        return selected_x[1]
    return selected_x[1] + offset * spacing_left


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
