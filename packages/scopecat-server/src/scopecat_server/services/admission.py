"""Run admission application service."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.config.candidates import (
    CandidateConfig,
    resolve_candidate_config_snapshot,
)
from scopecat.config.changes import (
    load_parameter_change_proposal,
    parameter_change_proposal_record_ref,
)
from scopecat.config.registry import service as config_registry_service
from scopecat.control.models import (
    ControlRun,
    ResourceKey,
    RunAdmissionRecord,
    RunPlanSummary,
)
from scopecat.daemon.wire import (
    AttentionResolutionReceipt,
    RunAdmission,
    RunSubmission,
)
from scopecat.kernel.errors import ProblemFailure
from scopecat.kernel.problems import (
    ProblemPhase,
    problem,
)
from scopecat.kernel.run_outcome import RunOutcome
from scopecat.project_state import ProjectStateServices
from scopecat.records.analysis import (
    AnalysisParameterProposalRecordOutput,
    AnalysisRecord,
)
from scopecat.records.config import (
    ConfigProfileSnapshot,
    DomainTargetBinding,
    InstrumentConnection,
    config_content_hash,
)
from scopecat.records.run import (
    AnalysisCandidateRunConfigSource,
    ConfigRegistryRunConfigSource,
    RunConfigSource,
)
from scopecat.runs.admission import build_run_admission
from scopecat.runs.refs import record_content_ref
from scopecat.runs.repository import (
    TerminalRunCommit,
)

from scopecat_server.storage.sqlite import (
    ControlPlaneConflict,
    ControlPlaneNotFound,
    SQLiteControlPlane,
    SQLiteRunRepository,
)

from ..errors import BackendConflict, BackendNotFound


class AdmissionService:
    """Own idempotent admission and admitted snapshots."""

    def __init__(
        self,
        *,
        control: SQLiteControlPlane,
        runs: SQLiteRunRepository,
        services: ProjectStateServices,
    ) -> None:
        self._control = control
        self._runs = runs
        self._services = services

    def submit_run(self, submission: RunSubmission) -> RunAdmission:
        retry = self._replay_admission(submission)
        if retry is not None:
            return retry

        try:
            if (
                submission.config_source is not None
                and config_content_hash(submission.config)
                != submission.config_source.content_hash
            ):
                raise BackendConflict(
                    "submitted run config does not match its source content hash"
                )
            self._resolve_provenance_config(submission.config_source)
            active = self._resolve_active_config()
            active_config = active.config
            _require_authoritative_instrument_inventory(
                submitted=submission.config,
                authoritative=active_config,
            )
            if submission.plan.domain_target_requirement is not None:
                _require_authoritative_domain_target(
                    submitted=submission.config,
                    authoritative=active_config,
                )
            skeleton = build_run_admission(
                config=submission.config,
                request=submission.request,
                config_source=submission.config_source,
            )
            admission = RunAdmissionRecord(
                submission_id=submission.submission_id,
                submission_content_hash=submission.intent_content_hash,
                run_id=skeleton.manifest.run_id,
                plan=submission.plan,
                display_name=submission.request.display_name,
                tags=submission.request.tags,
                description=submission.request.description,
                resource_claims=_canonical_resource_claims(
                    submission.plan,
                    instrument_keys={
                        instrument.id: instrument.exclusivity_key
                        for instrument in active_config.instrument_registry.instruments
                    },
                    domain_target=active_config.domain_target,
                ),
                admitted_at=skeleton.manifest.created_at,
            )
        except BackendConflict:
            retry = self._replay_admission(submission)
            if retry is not None:
                return retry
            raise

        prepared = self._runs.prepare_run_skeleton(skeleton)
        try:
            with self._control.write_transaction() as connection:
                run = self._control.admit_run_in_transaction(
                    connection,
                    admission,
                    expected_config_generation=active.activation.generation,
                )
                if run.run_id == admission.run_id:
                    self._runs.commit_run_skeleton_in_transaction(
                        connection,
                        prepared,
                    )
        except ControlPlaneConflict as error:
            raise BackendConflict(str(error)) from error
        return self._wire_admission(run)

    def _replay_admission(
        self,
        submission: RunSubmission,
    ) -> RunAdmission | None:
        run = self._control.find_run_by_submission_id(submission.submission_id)
        if run is None:
            return None
        if run.admission.submission_content_hash != submission.intent_content_hash:
            raise BackendConflict(
                "submission id is already admitted with different content"
            )
        return self._wire_admission(run)

    def _resolve_active_config(
        self,
    ) -> config_registry_service.ActiveConfigRegistrySnapshot:
        try:
            return config_registry_service.load_active_config_registry_snapshot(
                unit_of_work=self._services.config_registry
            )
        except ProblemFailure as error:
            raise BackendConflict(
                "run instrument inventory requires an active configuration"
            ) from error

    def _resolve_provenance_config(
        self,
        source: RunConfigSource | None,
    ) -> ConfigProfileSnapshot | None:
        if source is None:
            return None
        if isinstance(source, ConfigRegistryRunConfigSource):
            return self._resolve_registry_source(source)
        return self._resolve_candidate_source(source)

    def _resolve_registry_source(
        self,
        source: ConfigRegistryRunConfigSource,
    ) -> ConfigProfileSnapshot:
        try:
            resolved = config_registry_service.load_config_registry_entry_snapshot(
                entry_id=source.entry_id,
                unit_of_work=self._services.config_registry,
            )
            entry = resolved.entry
            if (
                source.config_ref != entry.config_ref
                or source.content_hash != entry.content_hash
            ):
                raise BackendConflict(
                    "run config source does not match its registry entry"
                )
            if (
                source.selector
                == config_registry_service.ACTIVE_CONFIG_REGISTRY_ENTRY_SELECTOR
            ):
                generation = source.registry_generation
                activations = (
                    config_registry_service.load_config_registry_activation_history(
                        unit_of_work=self._services.config_registry
                    )
                )
                activation = next(
                    (item for item in activations if item.generation == generation),
                    None,
                )
                if (
                    generation is None
                    or activation is None
                    or activation.entry_id != entry.id
                    or activation.entry_content_hash != entry.content_hash
                ):
                    raise BackendConflict(
                        "run config source does not match registry activation history"
                    )
            elif source.selector != entry.id or source.registry_generation is not None:
                raise BackendConflict(
                    "run config source selector does not match its registry entry"
                )
            return resolved.config
        except BackendConflict:
            raise
        except ProblemFailure as error:
            raise BackendConflict("run config source cannot be resolved") from error

    def _resolve_candidate_source(
        self,
        source: AnalysisCandidateRunConfigSource,
    ) -> ConfigProfileSnapshot:
        try:
            proposal = load_parameter_change_proposal(
                run_id=source.source_run_id,
                selector=source.proposal_id,
                services=self._services,
            )
            if (
                proposal.id != source.proposal_id
                or proposal.analysis_record_id != source.analysis_record_id
                or proposal.base_config_content_hash != source.base_config_content_hash
            ):
                raise BackendConflict(
                    "analysis candidate source does not match its durable proposal"
                )
            analysis = self._runs.read_model(
                source.source_run_id,
                record_content_ref(
                    record_id=source.analysis_record_id,
                    kind="analysis",
                ),
                AnalysisRecord,
            )
            if (
                analysis.run_id != source.source_run_id
                or not _analysis_references_proposal(
                    analysis,
                    proposal_id=proposal.id,
                )
            ):
                raise BackendConflict(
                    "analysis candidate proposal does not belong to its analysis"
                )
            resolved = resolve_candidate_config_snapshot(
                CandidateConfig(parameter_proposal=proposal),
                services=self._services,
            )
            if config_content_hash(resolved) != source.content_hash:
                raise BackendConflict(
                    "analysis candidate source does not match its resolved "
                    "configuration"
                )
            return resolved
        except BackendConflict:
            raise
        except ProblemFailure as error:
            raise BackendConflict(
                "analysis candidate config source cannot be resolved"
            ) from error

    def resolve_attention(
        self,
        run_id: str,
    ) -> AttentionResolutionReceipt:
        run = self._control_run(run_id)
        if run.state != "attention_required":
            raise BackendConflict("run does not require operator attention")
        outcome = RunOutcome(
            run_id=run_id,
            result="failed",
            certainty="indeterminate",
            problems=(
                problem(
                    "daemon.executor_loss_reconciled",
                    "operator reconciled external state after executor loss",
                    phase=ProblemPhase.EXECUTION,
                ),
            ),
        )
        prepared = self._runs.prepare_terminal_commit(
            TerminalRunCommit(run_id=run_id, outcome=outcome)
        )
        try:
            with self._control.write_transaction() as connection:
                released = self._control.release_run_resources_in_transaction(
                    connection,
                    run_id,
                )
                self._runs.commit_prepared_terminal_in_transaction(
                    connection,
                    prepared,
                )
                self._control.close_run_in_transaction(
                    connection,
                    run_id,
                )
        except ControlPlaneConflict as error:
            raise BackendConflict(str(error)) from error
        return AttentionResolutionReceipt(
            run_id=run_id,
            state="closed",
            released_resource_count=released,
        )

    def _control_run(self, run_id: str) -> ControlRun:
        try:
            return self._control.get_run(run_id)
        except ControlPlaneNotFound as error:
            raise BackendNotFound(str(error)) from error

    def _wire_admission(self, run: ControlRun) -> RunAdmission:
        return RunAdmission(
            submission_id=run.admission.submission_id,
            manifest=self._runs.read_manifest(run.run_id),
        )


@dataclass(frozen=True, slots=True)
class _InstrumentInventoryEntry:
    exclusivity_key: str
    driver_id: str
    connection: InstrumentConnection


def _analysis_references_proposal(
    analysis: AnalysisRecord,
    *,
    proposal_id: str,
) -> bool:
    expected_ref = parameter_change_proposal_record_ref(proposal_id)
    for output in analysis.outputs:
        if not isinstance(output, AnalysisParameterProposalRecordOutput):
            continue
        if (
            output.content.proposal_id == proposal_id
            and output.content.record_ref == expected_ref
        ):
            return True
    return False


def _require_authoritative_instrument_inventory(
    *,
    submitted: ConfigProfileSnapshot,
    authoritative: ConfigProfileSnapshot,
) -> None:
    submitted_inventory = _instrument_inventory(submitted)
    authoritative_inventory = _instrument_inventory(authoritative)
    changed = sorted(
        instrument_id
        for instrument_id in submitted_inventory.keys() | authoritative_inventory.keys()
        if submitted_inventory.get(instrument_id)
        != authoritative_inventory.get(instrument_id)
    )
    if changed:
        raise BackendConflict(
            "run instrument inventory differs from daemon-owned configuration: "
            + ", ".join(changed)
        )


def _instrument_inventory(
    config: ConfigProfileSnapshot,
) -> dict[str, _InstrumentInventoryEntry]:
    return {
        instrument.id: _InstrumentInventoryEntry(
            exclusivity_key=instrument.exclusivity_key,
            driver_id=instrument.driver_id,
            connection=instrument.connection,
        )
        for instrument in config.instrument_registry.instruments
    }


def _require_authoritative_domain_target(
    *,
    submitted: ConfigProfileSnapshot,
    authoritative: ConfigProfileSnapshot,
) -> None:
    if submitted.domain_target != authoritative.domain_target:
        raise BackendConflict(
            "run domain target configuration differs from the active configuration"
        )


def _canonical_resource_claims(
    plan: RunPlanSummary,
    *,
    instrument_keys: dict[str, str],
    domain_target: DomainTargetBinding | None,
) -> tuple[ResourceKey, ...]:
    """Resolve logical requirements into canonical scheduler claims."""

    logical_instruments = {
        requirement.id
        for requirement in plan.run_resource_requirements
        if requirement.kind == "instrument"
    }
    unknown_instruments = sorted(logical_instruments - instrument_keys.keys())
    if unknown_instruments:
        raise BackendConflict(
            "run plan references unknown instruments: " + ", ".join(unknown_instruments)
        )

    target = plan.domain_target_requirement
    if target is not None:
        if (
            domain_target is None
            or target.id != domain_target.id
            or target.kind != domain_target.kind
        ):
            raise BackendConflict(
                "run domain target requirement differs from the active configuration"
            )
        unauthorized = set(target.instrument_ids) - set(domain_target.instrument_ids)
        if unauthorized:
            raise BackendConflict(
                "run domain target requirement exceeds the active target authority"
            )
    claims = tuple(
        ResourceKey(
            kind=requirement.kind,
            id=instrument_keys[requirement.id],
        )
        for requirement in plan.run_resource_requirements
    )
    return claims
