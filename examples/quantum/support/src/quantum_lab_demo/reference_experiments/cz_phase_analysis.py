"""Run analysis and candidate proposal for conditional-phase Ramsey."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import scopecat as sc
from scopecat import Quantity

CZ_PHASE_ANALYSIS_KEY = "cz-conditional-phase"
CZ_PHASE_FIT_MODEL_ID = "quantum_lab_demo.cz_phase.sinusoid.v1"
CZ_PHASE_PROPOSAL_ID = "q0-q1-cz-coupler-amplitude"
CZ_PARAMETER_TABLE = "two_qubit_gates"
CZ_AMPLITUDE_COLUMN = "coupler_amplitude"

_MAX_PHASE_ERROR = 0.20
_MIN_CONTRAST = 0.75
_MAX_RMSE = 0.03
_MAX_CONTROL_ERROR = 0.08


@dataclass(frozen=True, slots=True)
class CzPhaseObservation:
    """One measured conditional-phase Ramsey point."""

    amplitude: Quantity
    control_state: int
    analyzer_phase: Quantity
    control_p1: float
    target_p1: float

    def __post_init__(self) -> None:
        _amplitude(self.amplitude)
        _control_state(self.control_state)
        _phase(self.analyzer_phase)
        object.__setattr__(self, "control_p1", _probability(self.control_p1))
        object.__setattr__(self, "target_p1", _probability(self.target_p1))


@dataclass(frozen=True, slots=True)
class CzRamseyFringeFit:
    """One fitted target-qubit Ramsey fringe at a control state."""

    amplitude: Quantity
    control_state: int
    phase_offset: float
    contrast: float
    offset: float
    rmse: float
    control_error: float


@dataclass(frozen=True, slots=True)
class CzAmplitudeAssessment:
    """Conditional phase and quality metrics for one scanned amplitude."""

    amplitude: Quantity
    control_0: CzRamseyFringeFit
    control_1: CzRamseyFringeFit
    conditional_phase: float
    phase_error: float
    minimum_contrast: float
    maximum_rmse: float
    maximum_control_error: float


@dataclass(frozen=True, slots=True)
class CzPhaseFit:
    """All amplitude assessments and the selected conditional-phase optimum."""

    assessments: tuple[CzAmplitudeAssessment, ...]
    selected: CzAmplitudeAssessment
    failed_checks: tuple[str, ...]
    quality_score: float

    @property
    def eligible(self) -> bool:
        return not self.failed_checks


@dataclass(frozen=True, slots=True)
class CzPhaseRunAnalysis:
    """Typed fit plus its native, explicitly saveable Analysis object."""

    run_id: str
    observations: tuple[CzPhaseObservation, ...]
    fit: CzPhaseFit
    analysis: sc.Analysis
    proposal_id: str | None


def fit_cz_phase(observations: Sequence[CzPhaseObservation]) -> CzPhaseFit:
    """Fit both control-state fringes and select the point nearest pi."""

    selected = tuple(observations)
    if len(selected) < 8 or any(
        not isinstance(value, CzPhaseObservation) for value in selected
    ):
        msg = "CZ phase fitting requires typed observations for both control states"
        raise ValueError(msg)
    grouped: dict[float, dict[int, list[CzPhaseObservation]]] = {}
    amplitudes: dict[float, Quantity] = {}
    for observation in selected:
        amplitude = _amplitude(observation.amplitude)
        amplitudes.setdefault(amplitude, Quantity(amplitude, "arb"))
        by_state = grouped.setdefault(amplitude, {})
        by_state.setdefault(observation.control_state, []).append(observation)

    assessments: list[CzAmplitudeAssessment] = []
    for amplitude in sorted(grouped):
        by_state = grouped[amplitude]
        if set(by_state) != {0, 1}:
            msg = "CZ phase fitting requires control states 0 and 1 at every amplitude"
            raise ValueError(msg)
        control_0 = _fit_fringe(amplitudes[amplitude], 0, by_state[0])
        control_1 = _fit_fringe(amplitudes[amplitude], 1, by_state[1])
        conditional = (control_1.phase_offset - control_0.phase_offset) % (
            2.0 * math.pi
        )
        assessments.append(
            CzAmplitudeAssessment(
                amplitude=amplitudes[amplitude],
                control_0=control_0,
                control_1=control_1,
                conditional_phase=conditional,
                phase_error=_angular_distance(conditional, math.pi),
                minimum_contrast=min(control_0.contrast, control_1.contrast),
                maximum_rmse=max(control_0.rmse, control_1.rmse),
                maximum_control_error=max(
                    control_0.control_error,
                    control_1.control_error,
                ),
            )
        )
    selected_assessment = min(
        assessments,
        key=lambda value: (
            value.phase_error,
            -value.minimum_contrast,
            value.maximum_rmse,
            _amplitude(value.amplitude),
        ),
    )
    failed_checks: list[str] = []
    if selected_assessment.phase_error > _MAX_PHASE_ERROR:
        failed_checks.append("conditional_phase_error_above_limit")
    if selected_assessment.minimum_contrast < _MIN_CONTRAST:
        failed_checks.append("contrast_below_limit")
    if selected_assessment.maximum_rmse > _MAX_RMSE:
        failed_checks.append("rmse_above_limit")
    if selected_assessment.maximum_control_error > _MAX_CONTROL_ERROR:
        failed_checks.append("control_error_above_limit")
    quality_score = (
        sum(
            (
                _bounded(
                    1.0 - selected_assessment.phase_error / (2.0 * _MAX_PHASE_ERROR)
                ),
                _bounded(selected_assessment.minimum_contrast),
                _bounded(1.0 - selected_assessment.maximum_rmse / (2.0 * _MAX_RMSE)),
                _bounded(
                    1.0
                    - selected_assessment.maximum_control_error
                    / (2.0 * _MAX_CONTROL_ERROR)
                ),
            )
        )
        / 4.0
    )
    return CzPhaseFit(
        assessments=tuple(assessments),
        selected=selected_assessment,
        failed_checks=tuple(failed_checks),
        quality_score=quality_score,
    )


def analyze_cz_phase_run(run: sc.RunHandle) -> CzPhaseRunAnalysis:
    """Fit a completed run and author a guarded CZ amplitude proposal."""

    if not isinstance(run, sc.RunHandle):
        msg = "CZ phase analysis requires a RunHandle"
        raise TypeError(msg)
    if run.manifest.status != "completed":
        msg = "CZ phase analysis requires a completed run"
        raise ValueError(msg)
    measurements = run.data().measurements()
    observations: list[CzPhaseObservation] = []
    for record in measurements.dataset.records:
        try:
            amplitude = record.coordinates["coupler_amplitude"]
            control_state = record.coordinates["control_state"]
            analyzer_phase = record.coordinates["analyzer_phase"]
            control_probability = record.observables["control_probability_1"]
            target_probability = record.observables["target_probability_1"]
        except KeyError as error:
            msg = "run does not contain the CZ conditional-phase measurement schema"
            raise ValueError(msg) from error
        if not isinstance(amplitude, Quantity) or not isinstance(
            analyzer_phase, Quantity
        ):
            msg = "CZ phase scan coordinates must be quantities"
            raise TypeError(msg)
        if type(control_state) is not int:
            msg = "CZ phase control-state coordinates must be integers"
            raise TypeError(msg)
        observations.append(
            CzPhaseObservation(
                amplitude=amplitude,
                control_state=control_state,
                analyzer_phase=analyzer_phase,
                control_p1=_ratio(control_probability),
                target_p1=_ratio(target_probability),
            )
        )
    selected = tuple(observations)
    fit = fit_cz_phase(selected)
    analysis = (
        run.analysis("CZ conditional-phase Ramsey", key=CZ_PHASE_ANALYSIS_KEY)
        .input(
            measurements.dataset_entry.id,
            role="fit-input",
            title="CZ conditional-phase measurements",
            expected_kind="measurement_dataset",
        )
        .table(
            [
                {
                    "coupler_amplitude": _amplitude(value.amplitude),
                    "control_state": value.control_state,
                    "analyzer_phase": _phase(value.analyzer_phase),
                    "control_probability_1": value.control_p1,
                    "target_probability_1": value.target_p1,
                }
                for value in selected
            ],
            title="Conditional-phase observations",
        )
        .table(
            [_assessment_row(value) for value in fit.assessments],
            title="Conditional-phase fit assessment",
        )
        .figure(
            {
                "kind": "cz_conditional_phase_ramsey",
                "x": "analyzer_phase",
                "y": "target_probability_1",
                "series": ("coupler_amplitude", "control_state"),
                "source_dataset": measurements.dataset_entry.id,
                "model_id": CZ_PHASE_FIT_MODEL_ID,
            },
            title="CZ conditional-phase Ramsey fringes",
        )
    )
    proposal_id: str | None = None
    if fit.eligible:
        proposal_id = CZ_PHASE_PROPOSAL_ID
        analysis = analysis.propose(
            proposal_id,
            sc.update_parameter_rows(
                CZ_PARAMETER_TABLE,
                key={
                    "control_qubit": "q0",
                    "partner_qubit": "q1",
                    "gate": "cz",
                },
                values={CZ_AMPLITUDE_COLUMN: fit.selected.amplitude},
            ),
            reason=(
                "Conditional-phase Ramsey selected the q0-q1 coupler amplitude "
                f"nearest pi with quality score={fit.quality_score:.6f}."
            ),
            confidence=fit.quality_score,
        )
    return CzPhaseRunAnalysis(
        run_id=run.id,
        observations=selected,
        fit=fit,
        analysis=analysis,
        proposal_id=proposal_id,
    )


def _fit_fringe(
    amplitude: Quantity,
    control_state: int,
    observations: Sequence[CzPhaseObservation],
) -> CzRamseyFringeFit:
    selected = tuple(observations)
    phases = tuple(_phase(value.analyzer_phase) for value in selected)
    if len(selected) < 4 or len({round(value, 12) for value in phases}) < 4:
        msg = "CZ phase fitting requires at least four distinct analyzer phases"
        raise ValueError(msg)
    design = np.asarray(
        [(1.0, math.cos(phase), math.sin(phase)) for phase in phases],
        dtype=float,
    )
    values = np.asarray([value.target_p1 for value in selected], dtype=float)
    coefficients, _residuals, rank, _singular_values = np.linalg.lstsq(
        design,
        values,
        rcond=None,
    )
    if int(rank) != 3:
        msg = "CZ analyzer phases do not identify a sinusoidal fringe"
        raise ValueError(msg)
    offset, cosine, sine = (float(value) for value in coefficients)
    fitted = design @ coefficients
    rmse = float(np.sqrt(np.mean((fitted - values) ** 2)))
    control_errors = tuple(
        value.control_p1 if control_state == 0 else 1.0 - value.control_p1
        for value in selected
    )
    return CzRamseyFringeFit(
        amplitude=amplitude,
        control_state=_control_state(control_state),
        phase_offset=math.atan2(-sine, -cosine) % (2.0 * math.pi),
        contrast=2.0 * math.hypot(cosine, sine),
        offset=offset,
        rmse=rmse,
        control_error=max(control_errors),
    )


def _assessment_row(value: CzAmplitudeAssessment) -> dict[str, object]:
    return {
        "model_id": CZ_PHASE_FIT_MODEL_ID,
        "coupler_amplitude": _amplitude(value.amplitude),
        "conditional_phase": value.conditional_phase,
        "phase_error": value.phase_error,
        "minimum_contrast": value.minimum_contrast,
        "maximum_rmse": value.maximum_rmse,
        "maximum_control_error": value.maximum_control_error,
    }


def _ratio(value: object) -> float:
    if not isinstance(value, Quantity):
        msg = "CZ phase probability values must be quantities"
        raise TypeError(msg)
    try:
        return _probability(float(value.to("ratio").value))
    except ValueError as error:
        msg = "CZ phase probability values must use ratio units"
        raise ValueError(msg) from error


def _amplitude(value: object) -> float:
    if not isinstance(value, Quantity):
        msg = "CZ amplitudes must be quantities"
        raise TypeError(msg)
    try:
        selected = float(value.to("arb").value)
    except ValueError as error:
        msg = "CZ amplitudes must use amplitude units"
        raise ValueError(msg) from error
    if not math.isfinite(selected):
        msg = "CZ amplitudes must be finite"
        raise ValueError(msg)
    return selected


def _phase(value: object) -> float:
    if not isinstance(value, Quantity):
        msg = "CZ analyzer phases must be quantities"
        raise TypeError(msg)
    try:
        selected = float(value.to("rad").value)
    except ValueError as error:
        msg = "CZ analyzer phases must use phase units"
        raise ValueError(msg) from error
    if not math.isfinite(selected):
        msg = "CZ analyzer phases must be finite"
        raise ValueError(msg)
    return selected


def _control_state(value: object) -> int:
    if type(value) is not int or value not in (0, 1):
        msg = "CZ control states must be 0 or 1"
        raise ValueError(msg)
    return value


def _probability(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = "CZ probabilities must be finite numbers"
        raise TypeError(msg)
    selected = float(value)
    if not math.isfinite(selected) or not 0.0 <= selected <= 1.0:
        msg = "CZ probabilities must lie in [0, 1]"
        raise ValueError(msg)
    return selected


def _angular_distance(left: float, right: float) -> float:
    return abs((left - right + math.pi) % (2.0 * math.pi) - math.pi)


def _bounded(value: float) -> float:
    return min(1.0, max(0.0, value))


__all__ = [
    "CZ_AMPLITUDE_COLUMN",
    "CZ_PARAMETER_TABLE",
    "CZ_PHASE_ANALYSIS_KEY",
    "CZ_PHASE_FIT_MODEL_ID",
    "CZ_PHASE_PROPOSAL_ID",
    "CzAmplitudeAssessment",
    "CzPhaseFit",
    "CzPhaseObservation",
    "CzPhaseRunAnalysis",
    "CzRamseyFringeFit",
    "analyze_cz_phase_run",
    "fit_cz_phase",
]
