"""Quadratic fitting and review evidence for the DRAG-beta workflow."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import SupportsFloat, cast

import numpy as np
import scopecat as sc
from scopecat import Quantity
from scopecat.records.measurement import MeasurementRecord, MeasurementScalar

from quantum_lab_demo.virtual_lab.parameters import (
    DRAG_BETA_PARAMETER_COLUMN,
    QUBIT_PARAMETER_TABLE,
    q0_parameter_key,
)
from quantum_lab_demo.workflows.drag_beta_calibration import (
    NEGATIVE_CANDIDATE_ID,
    POSITIVE_CANDIDATE_ID,
)
from quantum_lab_demo.workflows.drag_beta_experiment import PROBABILITY_1_RECORD_ID

_DRAG_BETA_FIT_MODEL_ID = "quantum_lab_demo.drag_beta.shared_n2_quadratic.v1"
_DRAG_BETA_ANALYSIS_KEY = "drag-beta-calibration"
_DRAG_BETA_PROPOSAL_ID = "q0-drag-beta"


@dataclass(frozen=True, slots=True)
class DragBetaObservation:
    """One measured probability at a beta and amplification count."""

    beta: Quantity
    amplification: int
    p1: float


@dataclass(frozen=True, slots=True)
class DragBetaFit:
    """Fit of ``p1 = baseline + N²(a beta² + b beta + c)``."""

    beta_hat: Quantity
    baseline: float
    quadratic: float
    linear: float
    scaled_offset: float
    rmse: float


def fit_drag_beta(observations: Sequence[DragBetaObservation]) -> DragBetaFit:
    """Fit the shared quadratic and return its minimum and residual."""

    selected = tuple(observations)
    if len(selected) < 4:
        raise ValueError("DRAG-beta fitting requires at least four observations")

    design = np.asarray(
        [
            (
                1.0,
                observation.amplification**2 * _beta_ns(observation.beta) ** 2,
                observation.amplification**2 * _beta_ns(observation.beta),
                float(observation.amplification**2),
            )
            for observation in selected
        ],
        dtype=float,
    )
    response = np.asarray([observation.p1 for observation in selected], dtype=float)
    coefficients, _residuals, rank, _singular_values = np.linalg.lstsq(
        design,
        response,
        rcond=None,
    )
    if int(rank) != 4:
        raise ValueError("DRAG-beta observations do not identify a joint quadratic")

    baseline, quadratic, linear, scaled_offset = (
        float(value) for value in coefficients
    )
    if quadratic <= 0:
        raise ValueError("DRAG-beta quadratic must have positive curvature")

    beta_hat = -linear / (2.0 * quadratic)
    scanned_betas = tuple(_beta_ns(observation.beta) for observation in selected)
    if not min(scanned_betas) <= beta_hat <= max(scanned_betas):
        raise ValueError("fitted DRAG beta lies outside the scanned range")

    residual = design @ coefficients - response
    rmse = float(cast("SupportsFloat", np.sqrt(np.mean(residual**2))))
    return DragBetaFit(
        beta_hat=Quantity(beta_hat, "ns"),
        baseline=baseline,
        quadratic=quadratic,
        linear=linear,
        scaled_offset=scaled_offset,
        rmse=rmse,
    )


@sc.analysis_step(id=_DRAG_BETA_ANALYSIS_KEY)
def drag_beta_analysis(context: sc.AnalysisContext) -> sc.Analysis:
    """Fit one DRAG run and author its table, figure, and proposal."""

    measurements = context.data.measurements()
    observations = tuple(
        _observation_from_record(record) for record in measurements.records
    )
    fit = fit_drag_beta(observations)

    return (
        context.result("DRAG beta calibration")
        .input(
            measurements.entry.id,
            role="fit-input",
            title="DRAG beta measurements",
        )
        .table(
            [
                {
                    "beta_ns": _beta_ns(observation.beta),
                    "amplification": observation.amplification,
                    "probability_1": observation.p1,
                }
                for observation in observations
            ],
            title="DRAG beta observations",
        )
        .table([_fit_summary(fit)], title="DRAG beta quadratic fit")
        .figure(
            {
                "kind": "drag_beta_fit",
                "x": "beta",
                "y": "probability_1",
                "series": "amplification",
                "source_dataset": measurements.entry.id,
                "model_id": _DRAG_BETA_FIT_MODEL_ID,
            },
            title="DRAG beta fit",
        )
        .propose(
            _DRAG_BETA_PROPOSAL_ID,
            sc.update_parameter_rows(
                QUBIT_PARAMETER_TABLE,
                key=q0_parameter_key(),
                values={DRAG_BETA_PARAMETER_COLUMN: fit.beta_hat},
            ),
            reason=(
                "Shared N² quadratic fit selected the q0 DRAG beta used by "
                f"{POSITIVE_CANDIDATE_ID!r} and {NEGATIVE_CANDIDATE_ID!r}; "
                f"RMSE={fit.rmse:.6g}."
            ),
        )
    )


def _observation_from_record(record: MeasurementRecord) -> DragBetaObservation:
    try:
        beta = record.coordinates["beta"]
        amplification = record.coordinates["amplification"]
        probability_one = record.observables[PROBABILITY_1_RECORD_ID]
    except KeyError as error:
        raise ValueError(
            "run does not contain the DRAG-beta measurement schema"
        ) from error
    if not isinstance(beta, MeasurementScalar):
        raise TypeError("DRAG-beta beta coordinates must be measurement scalars")
    if (
        not isinstance(amplification, MeasurementScalar)
        or amplification.dtype != "int64"
        or type(amplification.value) is not int
    ):
        raise TypeError("DRAG-beta amplification coordinates must be integers")
    if not isinstance(probability_one, MeasurementScalar):
        raise TypeError("DRAG-beta probability_1 values must be measurement scalars")
    return DragBetaObservation(
        beta=_measurement_quantity(beta, "beta").to("ns"),
        amplification=amplification.value,
        p1=float(
            _measurement_quantity(probability_one, "probability_1").to("ratio").value
        ),
    )


def _fit_summary(fit: DragBetaFit) -> dict[str, object]:
    return {
        "model_id": _DRAG_BETA_FIT_MODEL_ID,
        "beta_hat": _beta_ns(fit.beta_hat),
        "beta_unit": "ns",
        "baseline": fit.baseline,
        "quadratic": fit.quadratic,
        "linear": fit.linear,
        "scaled_offset": fit.scaled_offset,
        "rmse": fit.rmse,
    }


def _beta_ns(value: Quantity) -> float:
    selected = float(value.to("ns").value)
    if not math.isfinite(selected):
        raise ValueError("DRAG beta must be finite")
    return selected


def _measurement_quantity(value: MeasurementScalar, name: str) -> Quantity:
    if (
        value.dtype not in {"float64", "int64"}
        or isinstance(value.value, bool)
        or not isinstance(value.value, int | float)
        or value.unit is None
    ):
        raise TypeError(f"DRAG-beta {name} must be a numeric scalar with a unit")
    return Quantity(float(value.value), value.unit)


__all__ = [
    "DragBetaFit",
    "DragBetaObservation",
    "drag_beta_analysis",
    "fit_drag_beta",
]
