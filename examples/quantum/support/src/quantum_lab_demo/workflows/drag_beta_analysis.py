"""Observations, fitting, and run-to-review analysis for DRAG beta."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, SupportsFloat, cast

import numpy as np
import scopecat as sc
from scopecat import Quantity

from quantum_lab_demo.virtual_lab.parameters import (
    DRAG_BETA_PARAMETER_COLUMN,
    QUBIT_PARAMETER_TABLE,
    q0_parameter_key,
)
from quantum_lab_demo.workflows.drag_beta_calibration import (
    NEGATIVE_CANDIDATE_ID,
    POSITIVE_CANDIDATE_ID,
)

DRAG_BETA_FIT_MODEL_ID = "quantum_lab_demo.drag_beta.shared_n2_quadratic.v1"
DRAG_BETA_ANALYSIS_KEY = "drag-beta-calibration"
DRAG_BETA_PROPOSAL_ID = "q0-drag-beta"

_MAX_ELIGIBLE_RMSE = 0.02
_MIN_ELIGIBLE_BETA_SIGNAL_SPAN = 0.02
_MIN_ELIGIBLE_BETA_SIGNAL_TO_RMSE = 3.0
_MIN_ELIGIBLE_EDGE_MARGIN_FRACTION = 0.10
_RMSE_FLOOR = 1e-12


@dataclass(frozen=True, slots=True)
class DragBetaObservation:
    """One probability observation at a beta value and amplification count."""

    beta: Quantity
    amplification: int
    p1: float

    def __post_init__(self) -> None:
        _beta_ns(self.beta)
        _require_positive_amplification(self.amplification)
        if isinstance(self.p1, bool):
            msg = "DRAG-beta p1 observations must be finite numbers"
            raise TypeError(msg)
        selected = float(self.p1)
        if not math.isfinite(selected):
            msg = "DRAG-beta p1 observations must be finite numbers"
            raise ValueError(msg)
        if not 0.0 <= selected <= 1.0:
            msg = "DRAG-beta p1 observations must lie in [0, 1]"
            raise ValueError(msg)
        object.__setattr__(self, "p1", selected)


@dataclass(frozen=True, slots=True)
class DragBetaFit:
    """Shared fit of ``p1 = baseline + N^2 (a beta^2 + b beta + c)``."""

    beta_hat: Quantity
    baseline: float
    quadratic: float
    linear: float
    scaled_offset: float
    rmse: float


def fit_drag_beta(observations: Sequence[DragBetaObservation]) -> DragBetaFit:
    """Jointly fit beta scans from multiple amplification counts.

    The linear least-squares basis is ``1, N^2 beta^2, N^2 beta, N^2``.
    A full-rank fit therefore requires enough beta coverage and more than one
    amplification count; the optimum is the shared vertex ``-b / (2a)``.
    """

    selected = tuple(observations)
    if len(selected) < 4:
        msg = "DRAG-beta fitting requires at least four typed observations"
        raise ValueError(msg)
    rows: list[tuple[float, float, float, float]] = []
    values: list[float] = []
    for observation in selected:
        beta_ns = _beta_ns(observation.beta)
        amplification = _require_positive_amplification(observation.amplification)
        scale = float(amplification**2)
        rows.append((1.0, scale * beta_ns**2, scale * beta_ns, scale))
        values.append(observation.p1)

    design = np.asarray(rows, dtype=float)
    response = np.asarray(values, dtype=float)
    coefficients, _residuals, rank, _singular_values = np.linalg.lstsq(
        design,
        response,
        rcond=None,
    )
    if int(rank) != 4:
        msg = "DRAG-beta observations do not identify a joint quadratic"
        raise ValueError(msg)
    baseline, quadratic, linear, scaled_offset = (
        float(value) for value in coefficients
    )
    if not math.isfinite(quadratic) or quadratic <= 0:
        msg = "DRAG-beta joint quadratic must have positive curvature"
        raise ValueError(msg)
    beta_hat = -linear / (2.0 * quadratic)
    scanned_betas = tuple(_beta_ns(observation.beta) for observation in selected)
    if not min(scanned_betas) <= beta_hat <= max(scanned_betas):
        msg = "fitted DRAG beta lies outside the scanned beta range"
        raise ValueError(msg)
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


@dataclass(frozen=True, slots=True)
class DragBetaFitAssessment:
    """Typed quality assessment used to decide whether a fit may be proposed.

    ``quality_score`` is deliberately a bounded heuristic composed from fit
    residual, observed signal span, and distance from the scan boundary.  It is
    review evidence, not a statistical confidence interval.
    """

    quality_score: float
    fit_rmse: float
    observed_beta_span: float
    fitted_beta_span: float
    beta_signal_span: float
    beta_signal_to_rmse: float
    edge_margin_fraction: float
    failed_checks: tuple[str, ...]
    score_kind: Literal["heuristic"] = "heuristic"

    def __post_init__(self) -> None:
        for name, value in (
            ("quality_score", self.quality_score),
            ("fit_rmse", self.fit_rmse),
            ("observed_beta_span", self.observed_beta_span),
            ("fitted_beta_span", self.fitted_beta_span),
            ("beta_signal_span", self.beta_signal_span),
            ("beta_signal_to_rmse", self.beta_signal_to_rmse),
            ("edge_margin_fraction", self.edge_margin_fraction),
        ):
            if isinstance(value, bool):
                msg = f"DRAG-beta assessment {name} must be a finite number"
                raise TypeError(msg)
            if not math.isfinite(float(value)):
                msg = f"DRAG-beta assessment {name} must be a finite number"
                raise ValueError(msg)
        if not 0.0 <= self.quality_score <= 1.0:
            msg = "DRAG-beta heuristic quality score must lie in [0, 1]"
            raise ValueError(msg)
        if self.fit_rmse < 0.0 or any(
            value < 0.0
            for value in (
                self.observed_beta_span,
                self.fitted_beta_span,
                self.beta_signal_span,
                self.beta_signal_to_rmse,
            )
        ):
            msg = "DRAG-beta assessment residual and beta signal must be non-negative"
            raise ValueError(msg)
        if self.beta_signal_span != min(
            self.observed_beta_span,
            self.fitted_beta_span,
        ):
            msg = "DRAG-beta signal span must be the conservative observed/fit span"
            raise ValueError(msg)
        if not 0.0 <= self.edge_margin_fraction <= 0.5:
            msg = "DRAG-beta assessment edge margin fraction must lie in [0, 0.5]"
            raise ValueError(msg)
        selected_checks = tuple(self.failed_checks)
        if len(set(selected_checks)) != len(selected_checks) or any(
            not check for check in selected_checks
        ):
            msg = "DRAG-beta failed quality checks must be unique non-empty text"
            raise ValueError(msg)
        object.__setattr__(self, "quality_score", float(self.quality_score))
        object.__setattr__(self, "fit_rmse", float(self.fit_rmse))
        object.__setattr__(
            self,
            "observed_beta_span",
            float(self.observed_beta_span),
        )
        object.__setattr__(self, "fitted_beta_span", float(self.fitted_beta_span))
        object.__setattr__(self, "beta_signal_span", float(self.beta_signal_span))
        object.__setattr__(
            self,
            "beta_signal_to_rmse",
            float(self.beta_signal_to_rmse),
        )
        object.__setattr__(
            self,
            "edge_margin_fraction",
            float(self.edge_margin_fraction),
        )
        object.__setattr__(self, "failed_checks", selected_checks)

    @property
    def eligible(self) -> bool:
        """Return whether the fit clears every proposal guardrail."""

        return not self.failed_checks

    @property
    def recommendation(self) -> Literal["propose", "hold"]:
        """Return the stable review recommendation derived from the checks."""

        return "propose" if self.eligible else "hold"


@dataclass(frozen=True, slots=True)
class DragBetaRunAnalysis:
    """Typed fit outcome plus its native, explicitly saveable analysis record."""

    run_id: str
    observations: tuple[DragBetaObservation, ...]
    fit: DragBetaFit
    assessment: DragBetaFitAssessment
    analysis: sc.Analysis
    proposal_id: str | None

    def __post_init__(self) -> None:
        selected = tuple(self.observations)
        if not selected:
            msg = "DRAG-beta run analysis requires observations"
            raise ValueError(msg)
        if self.analysis.run.id != self.run_id:
            msg = "DRAG-beta analysis record must belong to its analyzed run"
            raise ValueError(msg)
        proposal_ids = tuple(
            proposal.id for proposal in self.analysis.parameter_proposals
        )
        expected_ids = () if self.proposal_id is None else (self.proposal_id,)
        if proposal_ids != expected_ids:
            msg = "DRAG-beta proposal identity must match its native Analysis"
            raise ValueError(msg)
        if self.assessment.eligible != (self.proposal_id is not None):
            msg = "DRAG-beta proposal presence must match fit eligibility"
            raise ValueError(msg)
        object.__setattr__(self, "observations", selected)


def assess_drag_beta_fit(
    fit: DragBetaFit,
    observations: tuple[DragBetaObservation, ...],
) -> DragBetaFitAssessment:
    """Assess one valid fit with explicit proposal guardrails."""

    selected = tuple(observations)
    if not selected:
        msg = "DRAG-beta assessment requires observations"
        raise ValueError(msg)
    fit_rmse = float(fit.rmse)
    if not math.isfinite(fit_rmse) or fit_rmse < 0.0:
        msg = "DRAG-beta fit RMSE must be finite and non-negative"
        raise ValueError(msg)

    betas_ns = tuple(_beta_ns(observation.beta) for observation in selected)
    scan_min = min(betas_ns)
    scan_max = max(betas_ns)
    scan_span = scan_max - scan_min
    if scan_span <= 0.0:
        msg = "DRAG-beta assessment requires a non-zero beta scan span"
        raise ValueError(msg)
    beta_hat_ns = _beta_ns(fit.beta_hat)
    if not scan_min <= beta_hat_ns <= scan_max:
        msg = "DRAG-beta fitted optimum must lie inside its scan"
        raise ValueError(msg)

    beta_grid, observations_by_amplification = _rectangular_beta_grid(selected)
    maximum_amplification = max(observations_by_amplification)
    maximum_amplification_observations = observations_by_amplification[
        maximum_amplification
    ]
    observed_beta_span = _span(
        tuple(observation.p1 for observation in maximum_amplification_observations)
    )
    fitted_beta_values = tuple(
        maximum_amplification**2 * (fit.quadratic * beta_ns**2 + fit.linear * beta_ns)
        for beta_ns in beta_grid
    )
    fitted_beta_span = _span(fitted_beta_values)
    beta_signal_span = min(observed_beta_span, fitted_beta_span)
    beta_signal_to_rmse = beta_signal_span / max(fit_rmse, _RMSE_FLOOR)
    edge_margin_fraction = (
        min(
            beta_hat_ns - scan_min,
            scan_max - beta_hat_ns,
        )
        / scan_span
    )

    failed_checks: list[str] = []
    if fit_rmse > _MAX_ELIGIBLE_RMSE:
        failed_checks.append("rmse_above_limit")
    if beta_signal_span < _MIN_ELIGIBLE_BETA_SIGNAL_SPAN:
        failed_checks.append("beta_signal_span_below_limit")
    if beta_signal_to_rmse < _MIN_ELIGIBLE_BETA_SIGNAL_TO_RMSE:
        failed_checks.append("beta_signal_to_rmse_below_limit")
    if edge_margin_fraction < _MIN_ELIGIBLE_EDGE_MARGIN_FRACTION:
        failed_checks.append("optimum_too_close_to_scan_edge")

    rmse_score = _bounded_score(1.0 - fit_rmse / (2.0 * _MAX_ELIGIBLE_RMSE))
    signal_score = _bounded_score(
        beta_signal_span / (2.0 * _MIN_ELIGIBLE_BETA_SIGNAL_SPAN)
    )
    signal_to_rmse_score = _bounded_score(
        beta_signal_to_rmse / (2.0 * _MIN_ELIGIBLE_BETA_SIGNAL_TO_RMSE)
    )
    edge_score = _bounded_score(
        edge_margin_fraction / (2.0 * _MIN_ELIGIBLE_EDGE_MARGIN_FRACTION)
    )
    return DragBetaFitAssessment(
        quality_score=(rmse_score + signal_score + signal_to_rmse_score + edge_score)
        / 4.0,
        fit_rmse=fit_rmse,
        observed_beta_span=observed_beta_span,
        fitted_beta_span=fitted_beta_span,
        beta_signal_span=beta_signal_span,
        beta_signal_to_rmse=beta_signal_to_rmse,
        edge_margin_fraction=edge_margin_fraction,
        failed_checks=tuple(failed_checks),
    )


def analyze_drag_beta_run(run: sc.RunHandle) -> DragBetaRunAnalysis:
    """Fit a completed run and author durable evidence plus an eligible proposal."""

    if run.manifest.status != "completed":
        msg = "DRAG-beta analysis requires a completed run"
        raise ValueError(msg)
    measurements = run.data().measurements()
    records = tuple(measurements.dataset.records)
    if not records:
        msg = "DRAG-beta analysis requires measurement records"
        raise ValueError(msg)
    observations: list[DragBetaObservation] = []
    for record in records:
        try:
            beta = record.coordinates["beta"]
            amplification = record.coordinates["amplification"]
            probability_one = record.observables["probability_1"]
        except KeyError as error:
            msg = "run does not contain the DRAG-beta reference measurement schema"
            raise ValueError(msg) from error
        if not isinstance(beta, Quantity):
            msg = "DRAG-beta run beta coordinates must be Quantity values"
            raise TypeError(msg)
        if type(amplification) is not int:
            msg = "DRAG-beta run amplification coordinates must be integers"
            raise TypeError(msg)
        if not isinstance(probability_one, Quantity):
            msg = "DRAG-beta run probability_1 values must be Quantity values"
            raise TypeError(msg)
        try:
            p1 = float(probability_one.to("ratio").value)
        except ValueError as error:
            msg = "DRAG-beta run probability_1 values must be ratios"
            raise ValueError(msg) from error
        observations.append(
            DragBetaObservation(
                beta=beta,
                amplification=amplification,
                p1=p1,
            )
        )

    selected = tuple(observations)
    fit = fit_drag_beta(selected)
    assessment = assess_drag_beta_fit(fit, selected)
    analysis = (
        run.analysis("DRAG beta calibration", key=DRAG_BETA_ANALYSIS_KEY)
        .input(
            measurements.dataset_entry.id,
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
                for observation in selected
            ],
            title="DRAG beta observations",
        )
        .table(
            [_fit_summary(fit, assessment)],
            title="DRAG beta fit assessment",
        )
        .figure(
            {
                "kind": "drag_beta_fit",
                "x": "beta",
                "y": "probability_1",
                "series": "amplification",
                "source_dataset": measurements.dataset_entry.id,
                "model_id": DRAG_BETA_FIT_MODEL_ID,
            },
            title="DRAG beta fit",
        )
    )
    proposal_id: str | None = None
    if assessment.eligible:
        proposal_id = DRAG_BETA_PROPOSAL_ID
        analysis = analysis.propose(
            proposal_id,
            sc.update_parameter_rows(
                QUBIT_PARAMETER_TABLE,
                key=q0_parameter_key(),
                values={DRAG_BETA_PARAMETER_COLUMN: fit.beta_hat},
            ),
            reason=(
                "Shared N^2 quadratic fit recommends the q0 DRAG beta used by "
                f"{POSITIVE_CANDIDATE_ID!r} and {NEGATIVE_CANDIDATE_ID!r}; "
                f"heuristic quality score={assessment.quality_score:.6f}."
            ),
            confidence=assessment.quality_score,
        )
    return DragBetaRunAnalysis(
        run_id=run.id,
        observations=selected,
        fit=fit,
        assessment=assessment,
        analysis=analysis,
        proposal_id=proposal_id,
    )


def _fit_summary(
    fit: DragBetaFit,
    assessment: DragBetaFitAssessment,
) -> dict[str, object]:
    return {
        "model_id": DRAG_BETA_FIT_MODEL_ID,
        "beta_hat": _beta_ns(fit.beta_hat),
        "beta_unit": "ns",
        "baseline": fit.baseline,
        "quadratic": fit.quadratic,
        "linear": fit.linear,
        "scaled_offset": fit.scaled_offset,
        "rmse": fit.rmse,
        "observed_beta_span": assessment.observed_beta_span,
        "fitted_beta_span": assessment.fitted_beta_span,
        "beta_signal_span": assessment.beta_signal_span,
        "beta_signal_to_rmse": assessment.beta_signal_to_rmse,
        "edge_margin_fraction": assessment.edge_margin_fraction,
        "quality_score": assessment.quality_score,
        "quality_score_kind": assessment.score_kind,
        "recommendation": assessment.recommendation,
        "failed_checks": list(assessment.failed_checks),
    }


def _require_positive_amplification(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        msg = "DRAG-beta amplification must be a positive integer"
        raise ValueError(msg)
    return value


def _beta_ns(value: object) -> float:
    if not isinstance(value, Quantity):
        msg = "DRAG beta must be a time Quantity"
        raise TypeError(msg)
    try:
        selected = float(value.to("ns").value)
    except ValueError as error:
        msg = "DRAG beta must be a time Quantity"
        raise ValueError(msg) from error
    if not math.isfinite(selected):
        msg = "DRAG beta must be finite"
        raise ValueError(msg)
    return selected


def _bounded_score(value: float) -> float:
    return max(0.0, min(1.0, value))


def _rectangular_beta_grid(
    observations: tuple[DragBetaObservation, ...],
) -> tuple[tuple[float, ...], dict[int, tuple[DragBetaObservation, ...]]]:
    by_amplification: dict[int, dict[float, DragBetaObservation]] = {}
    for observation in observations:
        beta_ns = _beta_ns(observation.beta)
        amplification_observations = by_amplification.setdefault(
            observation.amplification,
            {},
        )
        if beta_ns in amplification_observations:
            msg = "DRAG-beta assessment does not accept repeated scan coordinates"
            raise ValueError(msg)
        amplification_observations[beta_ns] = observation
    if len(by_amplification) < 2:
        msg = "DRAG-beta assessment requires at least two amplification counts"
        raise ValueError(msg)
    beta_grids = {tuple(sorted(values)) for values in by_amplification.values()}
    if len(beta_grids) != 1:
        msg = "DRAG-beta assessment requires one shared beta grid"
        raise ValueError(msg)
    [beta_grid] = beta_grids
    if len(beta_grid) < 3:
        msg = "DRAG-beta assessment requires at least three beta values"
        raise ValueError(msg)
    return beta_grid, {
        amplification: tuple(values[beta] for beta in beta_grid)
        for amplification, values in by_amplification.items()
    }


def _span(values: tuple[float, ...]) -> float:
    return max(values) - min(values)


__all__ = [
    "DRAG_BETA_ANALYSIS_KEY",
    "DRAG_BETA_FIT_MODEL_ID",
    "DRAG_BETA_PROPOSAL_ID",
    "DragBetaFit",
    "DragBetaFitAssessment",
    "DragBetaObservation",
    "DragBetaRunAnalysis",
    "analyze_drag_beta_run",
    "assess_drag_beta_fit",
    "fit_drag_beta",
]
