"""Project-owned q0/q1 DRAG freshness policy and bounded registry."""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel, ConfigDict, Field
from scopecat.api.calibration_planner import CalibrationPlanningContext
from scopecat.automation import (
    CalibrationDependencyEvidence,
    CalibrationObservation,
    CalibrationRegistry,
    CalibrationTargetRef,
    calibration,
)
from scopecat.records.config import ConfigContentHash, config_content_hash
from scopecat.records.run import ConfigRegistryRunConfigSource

from reference_lab.workflows.drag_beta_experiment import DragBetaQubit
from reference_lab.workflows.drag_beta_procedure import (
    DragBetaVerificationIntent,
    drag_beta_verification_procedure,
)
from reference_lab.workflows.drag_beta_verification import (
    DRAG_BETA_MINIMUM_IMPROVEMENT,
)

DRAG_BETA_CALIBRATION_ID = "reference-lab.drag-beta-freshness"
DRAG_BETA_CALIBRATION_VERSION = "1"
DRAG_BETA_CALIBRATION_FANOUT_SCOPE = "reference-lab.quantum-chip"
DRAG_BETA_CALIBRATION_TARGETS = tuple(
    CalibrationTargetRef(kind="logical_qubit", id=qubit) for qubit in ("q0", "q1")
)


class DragBetaFreshnessInputs(BaseModel):
    """Scientific inputs whose changes make one target stale.

    Registry entry identity and generation are intentionally absent: they are
    invocation provenance, while the exact active config contents are the
    freshness basis for this reference policy.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    qubit: DragBetaQubit
    config_content_hash: ConfigContentHash
    minimum_improvement: float = Field(
        default=DRAG_BETA_MINIMUM_IMPROVEMENT,
        ge=0.0,
    )


def _select_drag_beta_targets(
    _context: CalibrationPlanningContext,
) -> tuple[CalibrationTargetRef, ...]:
    return DRAG_BETA_CALIBRATION_TARGETS


def _observe_drag_beta_target(
    context: CalibrationPlanningContext,
    target: CalibrationTargetRef,
) -> CalibrationObservation[DragBetaFreshnessInputs]:
    if target not in DRAG_BETA_CALIBRATION_TARGETS:
        raise ValueError(f"unsupported reference-lab DRAG target: {target}")
    content_hash = config_content_hash(context.config)
    if context.config_source.content_hash != content_hash:
        raise ValueError("calibration planning config does not match its source hash")
    return CalibrationObservation(
        inputs=DragBetaFreshnessInputs(
            qubit=cast("DragBetaQubit", target.id),
            config_content_hash=content_hash,
        )
    )


@calibration(
    id=DRAG_BETA_CALIBRATION_ID,
    version=DRAG_BETA_CALIBRATION_VERSION,
    inputs=DragBetaFreshnessInputs,
    procedure=drag_beta_verification_procedure,
    fanout_scope=DRAG_BETA_CALIBRATION_FANOUT_SCOPE,
    max_in_flight=2,
    select=_select_drag_beta_targets,
    observe=_observe_drag_beta_target,
)
def drag_beta_freshness_calibration(
    context: CalibrationPlanningContext,
    target: CalibrationTargetRef,
    inputs: DragBetaFreshnessInputs,
    dependencies: tuple[CalibrationDependencyEvidence, ...],
) -> DragBetaVerificationIntent:
    """Build the exact verify-only intent after status/dependency evaluation."""

    if dependencies:
        raise ValueError("reference-lab DRAG calibration has no dependencies")
    if target.id != inputs.qubit:
        raise ValueError("DRAG calibration target does not match its observed input")
    content_hash = config_content_hash(context.config)
    if inputs.config_content_hash != content_hash:
        raise ValueError("DRAG freshness input does not match the planning config")
    source = context.config_source
    if source.content_hash != content_hash:
        raise ValueError("calibration planning config does not match its source hash")
    return DragBetaVerificationIntent(
        qubit=inputs.qubit,
        initial_config=context.config,
        initial_config_source=ConfigRegistryRunConfigSource(
            selector=source.selector,
            entry_id=source.entry_id,
            config_ref=source.config_ref,
            content_hash=source.content_hash,
            registry_generation=source.registry_generation,
        ),
        minimum_improvement=inputs.minimum_improvement,
    )


DRAG_BETA_CALIBRATION_REGISTRY = CalibrationRegistry[CalibrationPlanningContext](
    (drag_beta_freshness_calibration,)
)


__all__ = [
    "DRAG_BETA_CALIBRATION_FANOUT_SCOPE",
    "DRAG_BETA_CALIBRATION_ID",
    "DRAG_BETA_CALIBRATION_REGISTRY",
    "DRAG_BETA_CALIBRATION_TARGETS",
    "DRAG_BETA_CALIBRATION_VERSION",
    "DragBetaFreshnessInputs",
    "drag_beta_freshness_calibration",
]
