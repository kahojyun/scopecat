from __future__ import annotations

from datetime import UTC, datetime

import pytest
from scopecat.api.calibration_planner import CalibrationPlanningContext
from scopecat.automation import (
    CalibrationConfigSourceRef,
    CalibrationDependencyEvidence,
    CalibrationTargetRef,
)
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash

from reference_lab.configuration import bootstrap_config
from reference_lab.workflows.drag_beta_freshness import (
    DRAG_BETA_CALIBRATION_TARGETS,
    DragBetaFreshnessInputs,
    drag_beta_freshness_calibration,
)


def test_drag_beta_freshness_ignores_registry_only_provenance_changes() -> None:
    config = bootstrap_config()
    first = _planning_context(
        config,
        entry_id="active-entry-1",
        generation=1,
    )
    reactivated = _planning_context(
        config,
        entry_id="active-entry-2",
        generation=2,
    )
    target = DRAG_BETA_CALIBRATION_TARGETS[0]

    first_observation = drag_beta_freshness_calibration.observe(first, target)
    reactivated_observation = drag_beta_freshness_calibration.observe(
        reactivated,
        target,
    )

    assert first_observation.inputs == DragBetaFreshnessInputs(
        qubit="q0",
        config_content_hash=config_content_hash(config),
    )
    assert reactivated_observation.inputs == first_observation.inputs
    assert drag_beta_freshness_calibration.input_fingerprint(
        reactivated_observation.inputs
    ) == drag_beta_freshness_calibration.input_fingerprint(first_observation.inputs)

    intent = drag_beta_freshness_calibration.build_intent(
        reactivated,
        target,
        reactivated_observation.inputs,
        (),
    )

    assert intent.qubit == "q0"
    assert intent.initial_config == config
    assert intent.initial_config_source.entry_id == "active-entry-2"
    assert intent.initial_config_source.config_ref == "active@2"
    assert intent.initial_config_source.registry_generation == 2


def test_drag_beta_freshness_tracks_active_config_content() -> None:
    initial = bootstrap_config()
    changed = initial.model_copy(update={"id": "reference-lab-profile-changed"})
    target = DRAG_BETA_CALIBRATION_TARGETS[1]
    initial_observation = drag_beta_freshness_calibration.observe(
        _planning_context(initial, entry_id="initial", generation=1),
        target,
    )
    changed_observation = drag_beta_freshness_calibration.observe(
        _planning_context(changed, entry_id="changed", generation=2),
        target,
    )
    initial_inputs = DragBetaFreshnessInputs.model_validate(initial_observation.inputs)
    changed_inputs = DragBetaFreshnessInputs.model_validate(changed_observation.inputs)

    assert initial_inputs.config_content_hash != changed_inputs.config_content_hash
    assert drag_beta_freshness_calibration.input_fingerprint(
        initial_observation.inputs
    ) != drag_beta_freshness_calibration.input_fingerprint(changed_observation.inputs)


def test_drag_beta_freshness_has_two_bounded_independent_targets() -> None:
    context = _planning_context(
        bootstrap_config(),
        entry_id="active-entry",
        generation=1,
    )

    assert drag_beta_freshness_calibration.select_targets(context) == (
        CalibrationTargetRef(kind="logical_qubit", id="q0"),
        CalibrationTargetRef(kind="logical_qubit", id="q1"),
    )
    assert drag_beta_freshness_calibration.max_in_flight == 2

    observation = drag_beta_freshness_calibration.observe(
        context,
        DRAG_BETA_CALIBRATION_TARGETS[0],
    )
    dependency = CalibrationDependencyEvidence(
        calibration_key="other-calibration",
        cohort_id="prior-cohort",
        member_id="prior-member",
        procedure_run_id="prior-procedure-run",
        succeeded_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="has no dependencies"):
        drag_beta_freshness_calibration.build_intent(
            context,
            DRAG_BETA_CALIBRATION_TARGETS[0],
            observation.inputs,
            (dependency,),
        )


def _planning_context(
    config: ConfigProfileSnapshot,
    *,
    entry_id: str,
    generation: int,
) -> CalibrationPlanningContext:
    content_hash = config_content_hash(config)
    return CalibrationPlanningContext(
        config=config,
        config_source=CalibrationConfigSourceRef(
            entry_id=entry_id,
            config_ref=f"active@{generation}",
            content_hash=content_hash,
            registry_generation=generation,
        ),
    )
