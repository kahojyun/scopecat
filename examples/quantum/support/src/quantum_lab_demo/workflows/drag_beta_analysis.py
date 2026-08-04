"""Quadratic fitting and review evidence for the DRAG-beta workflow."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import SupportsFloat, cast

import numpy as np
import scopecat as sc
from scopecat import Quantity
from scopecat.measurements.results import Dataset, Variable

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
_OBSERVATION_COLUMNS = (
    sc.AnalysisTableColumn(id="beta_ns", label="DRAG beta", unit="ns"),
    sc.AnalysisTableColumn(id="amplification", label="Amplification"),
    sc.AnalysisTableColumn(id="probability_1", label="P(1)", unit="ratio"),
)
_FIT_COLUMNS = (
    sc.AnalysisTableColumn(id="model_id", label="Fit model"),
    sc.AnalysisTableColumn(id="beta_hat", label="Selected beta", unit="ns"),
    sc.AnalysisTableColumn(id="baseline", label="Baseline"),
    sc.AnalysisTableColumn(id="quadratic", label="Quadratic coefficient"),
    sc.AnalysisTableColumn(id="linear", label="Linear coefficient"),
    sc.AnalysisTableColumn(id="scaled_offset", label="Scaled offset"),
    sc.AnalysisTableColumn(id="rmse", label="RMSE"),
)


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

    measurements = context.measurements()
    observations = _observations_from_dataset(measurements)
    fit = fit_drag_beta(observations)

    return (
        context.result("DRAG beta calibration")
        .input(
            measurements.entry.id,
            role="fit-input",
            title="DRAG beta measurements",
        )
        .table(
            sc.AnalysisTable.from_rows(
                [
                    {
                        "beta_ns": _beta_ns(observation.beta),
                        "amplification": observation.amplification,
                        "probability_1": observation.p1,
                    }
                    for observation in observations
                ],
                columns=_OBSERVATION_COLUMNS,
            ),
            title="DRAG beta observations",
        )
        .table(
            sc.AnalysisTable.from_rows([_fit_summary(fit)], columns=_FIT_COLUMNS),
            title="DRAG beta quadratic fit",
        )
        .figure(
            sc.AnalysisFigure(
                kind="scatter",
                x_axis=sc.AnalysisFigureAxis(label="DRAG beta", unit="ns"),
                y_axis=sc.AnalysisFigureAxis(label="P(1)", unit="ratio"),
                series=[
                    sc.AnalysisFigureSeries(
                        id=f"amplification-{amplification}",
                        label=f"N={amplification}",
                        x=[
                            _beta_ns(observation.beta)
                            for observation in observations
                            if observation.amplification == amplification
                        ],
                        y=[
                            observation.p1
                            for observation in observations
                            if observation.amplification == amplification
                        ],
                    )
                    for amplification in sorted(
                        {observation.amplification for observation in observations}
                    )
                ],
            ),
            title="DRAG beta observations by amplification",
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


def _observations_from_dataset(
    dataset: Dataset,
) -> tuple[DragBetaObservation, ...]:
    try:
        beta = dataset.coords["beta"]
        amplification = dataset.coords["amplification"]
        probability_one = dataset.data_vars[PROBABILITY_1_RECORD_ID]
    except KeyError as error:
        raise ValueError(
            "run does not contain the DRAG-beta measurement schema"
        ) from error
    if amplification.dims != ("point",) or amplification.dtype != "int64":
        raise TypeError("DRAG-beta amplification coordinates must be integers")
    return tuple(
        _observation_from_values(
            beta_value,
            amplification_value,
            probability_one_value,
            beta=beta,
            probability_one=probability_one,
        )
        for beta_value, amplification_value, probability_one_value in zip(
            beta.values,
            amplification.values,
            probability_one.values,
            strict=True,
        )
    )


def _observation_from_values(
    beta_value: object,
    amplification_value: object,
    probability_one_value: object,
    *,
    beta: Variable,
    probability_one: Variable,
) -> DragBetaObservation:
    if type(amplification_value) is not int:
        raise TypeError("DRAG-beta amplification coordinates must be integers")
    return DragBetaObservation(
        beta=_variable_quantity(beta, beta_value, "beta").to("ns"),
        amplification=amplification_value,
        p1=float(
            _variable_quantity(
                probability_one,
                probability_one_value,
                "probability_1",
            )
            .to("ratio")
            .value
        ),
    )


def _fit_summary(fit: DragBetaFit) -> dict[str, sc.AnalysisTableCell]:
    return {
        "model_id": _DRAG_BETA_FIT_MODEL_ID,
        "beta_hat": _beta_ns(fit.beta_hat),
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


def _variable_quantity(variable: Variable, value: object, name: str) -> Quantity:
    if (
        variable.dims != ("point",)
        or variable.dtype not in {"float64", "int64"}
        or variable.unit is None
        or isinstance(value, bool)
        or not isinstance(value, int | float)
    ):
        raise TypeError(f"DRAG-beta {name} must be a numeric scalar with a unit")
    return Quantity(float(value), variable.unit)


__all__ = [
    "DragBetaFit",
    "DragBetaObservation",
    "drag_beta_analysis",
    "fit_drag_beta",
]
