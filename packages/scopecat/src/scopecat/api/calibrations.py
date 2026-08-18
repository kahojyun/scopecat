"""High-level project calibration cohort operations."""

from __future__ import annotations

from scopecat.api._config import LabConfigOperations
from scopecat.api.calibration_finalizer import (
    CalibrationPublicationPlanningContext,
    ProjectCalibrationPublicationFinalizer,
)
from scopecat.api.calibration_planner import (
    CalibrationPlanningContext,
    ProjectCalibrationEvaluator,
)
from scopecat.api.calibration_policy import CalibrationPublicationPolicyRegistry
from scopecat.api.calibration_publication import (
    CalibrationCohortMergeSteps,
    CalibrationCohortPublicationPlan,
    CalibrationPublicationReadSession,
    build_calibration_cohort_merge_contribution,
    calibration_cohort_merge_revision_source,
    publish_calibration_cohort,
    reopen_calibration_cohort_publication,
)
from scopecat.api.procedures import LabProcedureOperations, ProcedureHandle
from scopecat.automation.calibration_definition import CalibrationRegistry
from scopecat.automation.calibration_wire import (
    CalibrationCohortCreateCommand,
    CalibrationCohortCreateReceipt,
    CalibrationCohortListQuery,
    CalibrationCohortMemberListQuery,
    CalibrationCohortMemberPage,
    CalibrationCohortPage,
    CalibrationPublicationAttentionCommand,
    CalibrationPublicationDeferCommand,
    CalibrationPublicationReadyPage,
    CalibrationPublicationReadyQuery,
    CalibrationPublicationRetryCommand,
    CalibrationStatusQuery,
)
from scopecat.automation.calibrations import (
    CalibrationCohort,
    CalibrationCohortFinalization,
    CalibrationCohortMember,
    CalibrationCohortSpec,
    CalibrationConfigSourceRef,
    CalibrationStatusSnapshot,
)
from scopecat.config.registry.records import (
    CalibrationCohortMergeContribution,
    ConfigCompositionPolicyRef,
)
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.wire import (
    CalibrationCohortMergeRevisionSource,
    ConfigPublishReceipt,
)
from scopecat.records.config import ConfigContentHash
from scopecat.records.content import Sha256ContentHash
from scopecat.records.run import ConfigRegistryRunConfigSource


class LabCalibrationOperations:
    """Evaluate, admit, and inspect project-owned calibration cohorts."""

    __slots__ = (
        "_client",
        "_config",
        "_procedures",
        "_publication_registry",
        "_publication_session",
        "_registry",
    )

    def __init__(
        self,
        *,
        client: DaemonClient,
        config: LabConfigOperations,
        procedures: LabProcedureOperations,
        publication_session: CalibrationPublicationReadSession,
        registry: CalibrationRegistry[CalibrationPlanningContext],
        publication_registry: CalibrationPublicationPolicyRegistry,
    ) -> None:
        for definition in registry.values():
            procedures.registry.resolve(definition.procedure.ref)
        self._client = client
        self._config = config
        self._procedures = procedures
        self._publication_session = publication_session
        self._registry = registry
        self._publication_registry = publication_registry

    @property
    def registry(self) -> CalibrationRegistry[CalibrationPlanningContext]:
        return self._registry

    @property
    def publication_registry(self) -> CalibrationPublicationPolicyRegistry:
        return self._publication_registry

    def planning_context(self) -> CalibrationPlanningContext:
        config, source = self._config.resolve_with_source("active")
        if not isinstance(source, ConfigRegistryRunConfigSource):
            raise RuntimeError(
                "calibration planning requires exact active registry provenance"
            )
        if source.registry_generation is None:
            raise RuntimeError(
                "calibration planning requires an active registry generation"
            )
        return CalibrationPlanningContext(
            config=config,
            config_source=CalibrationConfigSourceRef.from_run_config_source(source),
        )

    def evaluator(self) -> ProjectCalibrationEvaluator:
        """Build a project evaluator over this exact application registry."""

        return ProjectCalibrationEvaluator(
            self,
            self._registry,
            self.planning_context,
            publication_policies=self._publication_registry,
        )

    def publication_planning_context(
        self,
    ) -> CalibrationPublicationPlanningContext:
        """Build the read-only project facade given to publication policies."""

        return CalibrationPublicationPlanningContext(
            self._client,
            self._config,
            self._procedures,
            self._publication_session,
        )

    def publication_finalizer(
        self,
        *,
        page_limit: int = 50,
        actor: str = "calibration-publication-finalizer",
    ) -> ProjectCalibrationPublicationFinalizer:
        """Build one stateful finite-traversal automatic finalizer."""

        return ProjectCalibrationPublicationFinalizer(
            self,
            self._publication_registry,
            page_limit=page_limit,
            actor=actor,
        )

    def status(
        self,
        calibration_keys: tuple[str, ...],
        *,
        fanout_scope: str,
    ) -> CalibrationStatusSnapshot:
        receipt = self._client.query_calibration_status(
            CalibrationStatusQuery(
                calibration_keys=calibration_keys,
                fanout_scope=fanout_scope,
            )
        )
        return receipt.snapshot

    def create(
        self,
        cohort_id: str,
        spec: CalibrationCohortSpec,
    ) -> CalibrationCohortCreateReceipt:
        return self._client.create_calibration_cohort(
            CalibrationCohortCreateCommand(cohort_id=cohort_id, spec=spec)
        )

    def get(self, cohort_id: str) -> CalibrationCohort:
        return self._client.get_calibration_cohort(cohort_id).cohort

    def list(
        self,
        *,
        limit: int = 50,
        before: int | None = None,
        fanout_scope: str | None = None,
    ) -> CalibrationCohortPage:
        return self._client.list_calibration_cohorts(
            CalibrationCohortListQuery(
                cursor=before,
                limit=limit,
                fanout_scope=fanout_scope,
            )
        )

    def members(
        self,
        cohort_id: str,
        *,
        limit: int = 50,
        after: int | None = None,
    ) -> CalibrationCohortMemberPage:
        return self._client.list_calibration_cohort_members(
            CalibrationCohortMemberListQuery(
                cohort_id=cohort_id,
                cursor=after,
                limit=limit,
            )
        )

    def ready_publications(
        self,
        query: CalibrationPublicationReadyQuery,
    ) -> CalibrationPublicationReadyPage:
        """Discover one finite page of exact supported publication work."""

        return self._client.list_ready_calibration_publications(query)

    def publication_finalization(
        self,
        cohort_id: str,
    ) -> CalibrationCohortFinalization:
        """Read exact durable automatic-publication state for one cohort."""

        return self._client.get_calibration_publication(cohort_id).finalization

    def require_publication_attention(
        self,
        command: CalibrationPublicationAttentionCommand,
    ) -> CalibrationCohortFinalization:
        """Move one exact ready finalization to durable operator attention."""

        receipt = self._client.require_calibration_publication_attention(command)
        return receipt.finalization

    def retry_publication(
        self,
        command: CalibrationPublicationRetryCommand,
    ) -> CalibrationCohortFinalization:
        """Return one exact attention state to the durable ready queue."""

        receipt = self._client.retry_calibration_publication(command)
        return receipt.finalization

    def defer_publication(
        self,
        command: CalibrationPublicationDeferCommand,
    ) -> CalibrationCohortFinalization:
        """Delay one exact ready occurrence using the server clock."""

        receipt = self._client.defer_calibration_publication(command)
        return receipt.finalization

    def build_merge_contribution(
        self,
        *,
        cohort: CalibrationCohort,
        member: CalibrationCohortMember,
        procedure: ProcedureHandle,
        steps: CalibrationCohortMergeSteps,
        proposal_id: str,
        decision_output_id: str,
        result_input_fingerprint: Sha256ContentHash,
    ) -> CalibrationCohortMergeContribution:
        """Freeze one exact successful member into merge evidence."""

        if procedure.operations is not self._procedures:
            raise ValueError(
                "calibration contribution procedure belongs to another lab client"
            )
        return build_calibration_cohort_merge_contribution(
            cohort=cohort,
            member=member,
            procedure=procedure,
            steps=steps,
            proposal_id=proposal_id,
            decision_output_id=decision_output_id,
            result_input_fingerprint=result_input_fingerprint,
            session=self._publication_session,
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
        """Build a merge source that exactly covers one complete cohort."""

        return calibration_cohort_merge_revision_source(
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
        """Freeze deterministic config entry and operation identities."""

        expected_finalization_revision: int | None = None
        if source.automatic_publication is not None:
            finalization = self.publication_finalization(source.cohort_id)
            if (
                finalization.cohort_id != source.cohort_id
                or finalization.spec_hash != source.spec_hash
                or finalization.policy != source.automatic_publication
                or finalization.base_config_source.entry_id != source.base_entry_id
                or finalization.base_config_source.content_hash
                != source.base_content_hash
                or finalization.base_config_source.registry_generation
                != source.base_generation
            ):
                raise ValueError(
                    "automatic publication finalization does not match merge source"
                )
            expected_finalization_revision = finalization.revision
        return CalibrationCohortPublicationPlan.create(
            source,
            actor=actor,
            note=note,
            expected_calibration_finalization_revision=(expected_finalization_revision),
        )

    def publish(
        self,
        plan: CalibrationCohortPublicationPlan,
    ) -> ConfigPublishReceipt:
        """Publish an exact cohort plan with unknown-outcome reconciliation."""

        return publish_calibration_cohort(self._config, plan)

    def reopen_publication(
        self,
        plan: CalibrationCohortPublicationPlan,
    ) -> ConfigPublishReceipt:
        """Reopen a deterministic publication without issuing a mutation."""

        return reopen_calibration_cohort_publication(self._config, plan)


__all__ = ["LabCalibrationOperations"]
