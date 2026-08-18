from __future__ import annotations

import pytest
from pydantic import ValidationError

from scopecat.automation.calibrations import (
    CalibrationDefinitionRef,
    CalibrationPublicationPolicyRef,
)
from scopecat.config.registry.records import (
    CalibrationCohortMergeContribution,
    CalibrationCohortMergeRegistrySource,
    ConfigCompositionPolicyRef,
    ConfigCompositionStepRef,
    ResolvedCalibrationCohortMergeContribution,
)
from scopecat.daemon.wire import (
    CalibrationCohortMergeRevisionSource,
    CalibrationPublicationCommand,
    ConfigPublishCommand,
)
from scopecat.records.analysis import ProjectAnalysisDecisionReference

_CONFIG_HASH = f"sha256:{'a' * 64}"
_RESULT_HASH = f"sha256:{'b' * 64}"
_SPEC_HASH = f"sha256:{'c' * 64}"
_POLICY_HASH = f"sha256:{'d' * 64}"
_DECISION_HASH = f"sha256:{'e' * 64}"
_PUBLICATION_POLICY_HASH = f"sha256:{'f' * 64}"


def test_calibration_merge_source_is_canonical_and_hashes_exact_proof() -> None:
    q0 = _contribution("q0")
    q1 = _contribution("q1")
    forward = _command((q0, q1))
    reverse = _command((q1, q0))

    assert forward == reverse
    assert forward.source_intent_hash == reverse.source_intent_hash
    assert isinstance(forward.source, CalibrationCohortMergeRevisionSource)
    assert tuple(item.member_id for item in forward.source.contributions) == (
        "member-q0",
        "member-q1",
    )
    assert (
        CalibrationPublicationCommand.model_validate_json(forward.model_dump_json())
        == forward
    )

    changed = _command(
        (
            q0,
            q1.model_copy(update={"result_input_fingerprint": f"sha256:{'f' * 64}"}),
        )
    )
    assert changed.source_intent_hash != forward.source_intent_hash


def test_calibration_merge_accepts_one_contribution_but_not_zero() -> None:
    contribution = _contribution("q0")
    command = _command((contribution,))
    assert (
        CalibrationPublicationCommand.model_validate_json(command.model_dump_json())
        == command
    )

    resolved = _registry_source((_resolved_contribution("q0"),))
    assert (
        CalibrationCohortMergeRegistrySource.model_validate_json(
            resolved.model_dump_json()
        )
        == resolved
    )

    with pytest.raises(ValidationError):
        _source(())
    with pytest.raises(ValidationError):
        _registry_source(())


def test_calibration_merge_command_requires_base_generation_cas() -> None:
    source = _source((_contribution("q0"), _contribution("q1")))

    with pytest.raises(ValidationError):
        ConfigPublishCommand.model_validate(
            {
                "operation_id": "merge-op",
                "source": source.model_dump(mode="json"),
                "actor": "automation",
                "expected_generation": 7,
                "entry_id": "merged-entry",
            }
        )

    with pytest.raises(ValidationError, match="must equal its base_generation"):
        CalibrationPublicationCommand(
            operation_id="merge-op",
            source=source,
            actor="automation",
            expected_generation=6,
            entry_id="merged-entry",
        )


def test_automatic_merge_requires_revision_fence_outside_publish_intent() -> None:
    source = _automatic_source((_contribution("q0"), _contribution("q1")))

    with pytest.raises(ValidationError, match="requires an expected finalization"):
        CalibrationPublicationCommand(
            operation_id="merge-op",
            source=source,
            actor="automation",
            expected_generation=7,
            entry_id="merged-entry",
        )

    first = CalibrationPublicationCommand(
        operation_id="merge-op",
        source=source,
        actor="automation",
        expected_generation=7,
        expected_finalization_revision=2,
        entry_id="merged-entry",
    )
    rebased = first.model_copy(update={"expected_finalization_revision": 3})
    assert first.source_intent_hash == rebased.source_intent_hash
    assert first.intent_hash == rebased.intent_hash

    with pytest.raises(ValidationError, match="only valid for automatic"):
        CalibrationPublicationCommand(
            operation_id="manual-merge-op",
            source=_source((_contribution("q0"),)),
            actor="automation",
            expected_generation=7,
            expected_finalization_revision=2,
            entry_id="manual-merged-entry",
        )


def test_calibration_merge_source_rejects_duplicate_contribution_identity() -> None:
    q0 = _contribution("q0")
    duplicate = _contribution("q1").model_copy(update={"member_id": q0.member_id})

    with pytest.raises(ValidationError, match="member identities must be unique"):
        _source((q0, duplicate))


def test_calibration_merge_contribution_requires_distinct_step_attempts() -> None:
    q0 = _contribution("q0")

    with pytest.raises(ValidationError, match="step attempts must be distinct"):
        CalibrationCohortMergeContribution(
            **q0.model_dump(exclude={"fit_step"}),
            fit_step=q0.baseline_step,
        )


def test_resolved_calibration_merge_registry_source_preserves_exact_outputs() -> None:
    q0 = _resolved_contribution("q0")
    q1 = _resolved_contribution("q1")
    source = _registry_source((q1, q0))

    assert tuple(item.member_id for item in source.contributions) == (
        "member-q0",
        "member-q1",
    )
    assert source.contributions[0].baseline_run_id == "baseline-q0"
    assert source.contributions[0].fit_analysis_record_id == "fit-analysis-q0"
    assert source.contributions[0].candidate_run_id == "candidate-q0"
    assert (
        CalibrationCohortMergeRegistrySource.model_validate_json(
            source.model_dump_json()
        )
        == source
    )


def _registry_source(
    contributions: tuple[ResolvedCalibrationCohortMergeContribution, ...],
) -> CalibrationCohortMergeRegistrySource:
    return CalibrationCohortMergeRegistrySource(
        cohort_id="cohort-1",
        spec_hash=_SPEC_HASH,
        composition_policy_ref=_policy(),
        base_entry_id="base-entry",
        base_config_content_hash=_CONFIG_HASH,
        base_registry_generation=7,
        candidate_id="merged-candidate",
        contributions=contributions,
    )


def _command(
    contributions: tuple[CalibrationCohortMergeContribution, ...],
) -> CalibrationPublicationCommand:
    return CalibrationPublicationCommand(
        operation_id="merge-op",
        source=_source(contributions),
        actor="automation",
        expected_generation=7,
        entry_id="merged-entry",
    )


def _source(
    contributions: tuple[CalibrationCohortMergeContribution, ...],
) -> CalibrationCohortMergeRevisionSource:
    return CalibrationCohortMergeRevisionSource(
        cohort_id="cohort-1",
        spec_hash=_SPEC_HASH,
        composition_policy_ref=_policy(),
        base_entry_id="base-entry",
        base_content_hash=_CONFIG_HASH,
        base_generation=7,
        candidate_id="merged-candidate",
        contributions=contributions,
        expected_result_content_hash=_RESULT_HASH,
    )


def _automatic_source(
    contributions: tuple[CalibrationCohortMergeContribution, ...],
) -> CalibrationCohortMergeRevisionSource:
    payload = _source(contributions).model_dump(mode="python")
    payload["automatic_publication"] = CalibrationPublicationPolicyRef(
        id="reference-lab.drag-automatic-publication",
        version="1",
        fingerprint=_PUBLICATION_POLICY_HASH,
        calibration=CalibrationDefinitionRef(
            id="reference-lab.drag-calibration",
            version="1",
            fingerprint=_PUBLICATION_POLICY_HASH,
            success_policy="published_result",
        ),
        composition_policy=_policy(),
    )
    return CalibrationCohortMergeRevisionSource.model_validate(payload)


def _policy() -> ConfigCompositionPolicyRef:
    return ConfigCompositionPolicyRef(
        id="reference-lab.drag-composition",
        version="1",
        fingerprint=_POLICY_HASH,
    )


def _contribution(target: str) -> CalibrationCohortMergeContribution:
    return CalibrationCohortMergeContribution(
        member_id=f"member-{target}",
        procedure_run_id=f"procedure-{target}",
        baseline_step=ConfigCompositionStepRef(step_key="baseline", attempt=1),
        fit_step=ConfigCompositionStepRef(step_key="fit", attempt=1),
        candidate_step=ConfigCompositionStepRef(step_key="candidate", attempt=1),
        verification_step=ConfigCompositionStepRef(
            step_key="verification",
            attempt=1,
        ),
        proposal_id=f"proposal-{target}",
        decision=_decision(target),
        result_input_fingerprint=_RESULT_HASH,
    )


def _resolved_contribution(
    target: str,
) -> ResolvedCalibrationCohortMergeContribution:
    contribution = _contribution(target)
    return ResolvedCalibrationCohortMergeContribution(
        member_id=contribution.member_id,
        procedure_run_id=contribution.procedure_run_id,
        baseline_step=contribution.baseline_step,
        baseline_run_id=f"baseline-{target}",
        fit_step=contribution.fit_step,
        fit_analysis_record_id=f"fit-analysis-{target}",
        candidate_step=contribution.candidate_step,
        candidate_run_id=f"candidate-{target}",
        verification_step=contribution.verification_step,
        proposal_id=contribution.proposal_id,
        decision=contribution.decision,
        result_input_fingerprint=contribution.result_input_fingerprint,
    )


def _decision(target: str) -> ProjectAnalysisDecisionReference:
    return ProjectAnalysisDecisionReference(
        analysis_record_id=f"verification-analysis-{target}",
        output_id="decision",
        schema_id="reference-lab.drag-verification.v1",
        schema_hash=_DECISION_HASH,
    )
