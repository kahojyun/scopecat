"""Resident automatic-publication policy for verified DRAG cohorts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from scopecat.api.calibration_finalizer import (
    CalibrationPublicationCandidate,
    CalibrationPublicationPlanningContext,
    CalibrationPublicationPolicyRegistry,
    CalibrationPublicationProcedureView,
    CalibrationPublicationRunView,
    calibration_publication_policy,
)
from scopecat.api.calibration_publication import (
    CalibrationCohortMergeSteps,
    CalibrationCohortPublicationPlan,
)
from scopecat.automation.calibration_wire import CalibrationCohortMemberPage
from scopecat.automation.calibrations import (
    CalibrationCohort,
    CalibrationCohortMember,
)
from scopecat.config.registry.records import (
    CalibrationCohortMergeContribution,
    ConfigCompositionPolicyRef,
)
from scopecat.daemon.views import ConfigEntryView
from scopecat.daemon.wire import CalibrationCohortMergeRevisionSource
from scopecat.records.config import ConfigContentHash
from scopecat.records.content import Sha256ContentHash

from reference_lab.workflows.drag_beta_freshness import (
    drag_beta_freshness_calibration,
)
from reference_lab.workflows.drag_beta_publication import (
    DRAG_BETA_COMPOSITION_POLICY_REF,
    DRAG_BETA_PUBLICATION_ACTOR,
    DRAG_BETA_PUBLICATION_NOTE,
    prepare_drag_beta_cohort_publication,
)

if TYPE_CHECKING:
    from scopecat.api.lab import LabClient
    from scopecat.api.published_analysis import PublishedAnalysis

DRAG_BETA_PUBLICATION_POLICY_ID = "reference-lab.drag-beta-automatic-publication"
DRAG_BETA_PUBLICATION_POLICY_VERSION = "1"


@dataclass(frozen=True, slots=True)
class _CandidateCalibrationOperations:
    context: CalibrationPublicationPlanningContext
    candidate: CalibrationPublicationCandidate

    def get(self, cohort_id: str) -> CalibrationCohort:
        self._require_cohort(cohort_id)
        return self.candidate.cohort

    def members(
        self,
        cohort_id: str,
        *,
        limit: int = 50,
        after: int | None = None,
    ) -> CalibrationCohortMemberPage:
        self._require_cohort(cohort_id)
        if after is not None:
            raise ValueError(
                "automatic DRAG publication requires the complete member page"
            )
        if limit < len(self.candidate.member_page.items):
            raise ValueError(
                "automatic DRAG publication member limit truncates its cohort"
            )
        return self.candidate.member_page

    def build_merge_contribution(
        self,
        *,
        cohort: CalibrationCohort,
        member: CalibrationCohortMember,
        procedure: CalibrationPublicationProcedureView,
        steps: CalibrationCohortMergeSteps,
        proposal_id: str,
        decision_output_id: str,
        result_input_fingerprint: Sha256ContentHash,
    ) -> CalibrationCohortMergeContribution:
        return self.context.build_merge_contribution(
            cohort=cohort,
            member=member,
            procedure=procedure,
            steps=steps,
            proposal_id=proposal_id,
            decision_output_id=decision_output_id,
            result_input_fingerprint=result_input_fingerprint,
        )

    def merge_source(
        self,
        *,
        cohort: CalibrationCohort,
        member_page: CalibrationCohortMemberPage,
        composition_policy_ref: ConfigCompositionPolicyRef,
        candidate_id: str,
        contributions: tuple[CalibrationCohortMergeContribution, ...],
        expected_result_content_hash: ConfigContentHash,
    ) -> CalibrationCohortMergeRevisionSource:
        return self.context.merge_source(
            cohort=cohort,
            member_page=member_page,
            composition_policy_ref=composition_policy_ref,
            candidate_id=candidate_id,
            contributions=contributions,
            expected_result_content_hash=expected_result_content_hash,
        )

    def publication_plan(
        self,
        source: CalibrationCohortMergeRevisionSource,
        *,
        actor: str,
        note: str = "",
    ) -> CalibrationCohortPublicationPlan:
        return self.context.publication_plan(
            source,
            actor=actor,
            note=note,
            expected_calibration_finalization_revision=(
                self.candidate.finalization.revision
            ),
        )

    def _require_cohort(self, cohort_id: str) -> None:
        if cohort_id != self.candidate.cohort.cohort_id:
            raise ValueError("automatic DRAG publication requested another cohort")


@dataclass(frozen=True, slots=True)
class _PlanningConfigOperations:
    context: CalibrationPublicationPlanningContext

    def entry(self, entry_id: str) -> ConfigEntryView:
        return self.context.config_entry(entry_id)


@dataclass(frozen=True, slots=True)
class _PlanningProcedureOperations:
    context: CalibrationPublicationPlanningContext

    def get(self, procedure_run_id: str) -> CalibrationPublicationProcedureView:
        return self.context.procedure(procedure_run_id)


@dataclass(frozen=True, slots=True)
class _DragBetaPlanningLab:
    """LabClient-shaped read adapter with no publication mutation method."""

    context: CalibrationPublicationPlanningContext
    candidate: CalibrationPublicationCandidate

    @property
    def calibrations(self) -> _CandidateCalibrationOperations:
        return _CandidateCalibrationOperations(self.context, self.candidate)

    @property
    def config(self) -> _PlanningConfigOperations:
        return _PlanningConfigOperations(self.context)

    @property
    def procedures(self) -> _PlanningProcedureOperations:
        return _PlanningProcedureOperations(self.context)

    def get_run(self, run_id: str) -> CalibrationPublicationRunView:
        return self.context.run(run_id)

    def published_analysis(self, selector: str) -> PublishedAnalysis:
        return self.context.published_analysis(selector)


@calibration_publication_policy(
    id=DRAG_BETA_PUBLICATION_POLICY_ID,
    version=DRAG_BETA_PUBLICATION_POLICY_VERSION,
    calibration=drag_beta_freshness_calibration.ref,
    composition_policy=DRAG_BETA_COMPOSITION_POLICY_REF,
    actor=DRAG_BETA_PUBLICATION_ACTOR,
    note=DRAG_BETA_PUBLICATION_NOTE,
)
def prepare_drag_beta_automatic_publication(
    context: CalibrationPublicationPlanningContext,
    candidate: CalibrationPublicationCandidate,
) -> CalibrationCohortPublicationPlan:
    """Reuse the exact Phase 7 proof and return its deterministic plan."""

    planning_lab = _DragBetaPlanningLab(context, candidate)
    prepared = prepare_drag_beta_cohort_publication(
        cast("LabClient", cast("object", planning_lab)),
        candidate.cohort.cohort_id,
        actor=DRAG_BETA_PUBLICATION_ACTOR,
        note=DRAG_BETA_PUBLICATION_NOTE,
    )
    return prepared.plan


DRAG_BETA_PUBLICATION_POLICY_REF = prepare_drag_beta_automatic_publication.ref
DRAG_BETA_PUBLICATION_POLICY_FINGERPRINT = DRAG_BETA_PUBLICATION_POLICY_REF.fingerprint
DRAG_BETA_PUBLICATION_POLICY_REGISTRY = CalibrationPublicationPolicyRegistry(
    (prepare_drag_beta_automatic_publication,)
)


__all__ = [
    "DRAG_BETA_PUBLICATION_POLICY_FINGERPRINT",
    "DRAG_BETA_PUBLICATION_POLICY_ID",
    "DRAG_BETA_PUBLICATION_POLICY_REF",
    "DRAG_BETA_PUBLICATION_POLICY_REGISTRY",
    "DRAG_BETA_PUBLICATION_POLICY_VERSION",
    "prepare_drag_beta_automatic_publication",
]
