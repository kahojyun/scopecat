from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import TypeAdapter, ValidationError

from scopecat.config.changes import parameter_change_proposal_from_updates
from scopecat.config.parameters import replace_scalar_parameter
from scopecat.config.registry.records import (
    ConfigRegistryActivationRecord,
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
    DirectConfigRegistrySource,
)
from scopecat.daemon.wire import (
    AnalysisJsonOutputPayload,
    AnalysisNoteOutputPayload,
    AnalysisParameterProposalOutputPayload,
    AnalysisSaveCommand,
    CandidateConfigActivationCommand,
    ConfigActivationReceipt,
    ConfigDefaultReceipt,
    ConfigEntryActivationCommand,
    ConfigImportReceipt,
    ConfigRollbackCommand,
    DelegatedPlanSummary,
    DelegatedRunSubmission,
    DirectConfigDefaultCommand,
    DirectConfigImportCommand,
    ExecutionTransitionBatch,
    ExecutionTransitionBatchReceipt,
    ExecutorLease,
    ExperimentCatalog,
    ManagedRunSubmission,
    MeasurementAppendCommand,
    ParameterProposalDecisionCommand,
    PayloadCommitCommand,
    RegisteredExperimentDescriptor,
    ResourceClaimDescriptor,
    RunSubmission,
    TerminalRunCommitCommand,
)
from scopecat.records.config import config_content_hash
from scopecat.records.execution_journal import ExecutionTransition, PayloadEvidence
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.measurement_recording import MeasurementDatasetAppend
from scopecat.records.parameter import Quantity
from scopecat.records.parameter_change import AutomaticPolicyDecisionAuthority
from scopecat.records.run import (
    ConfigRegistryRunConfigSource,
    RunManifest,
    RunOutcome,
)
from scopecat.records.run_request import RunRequest
from tests.testkit.workflow_fixtures import load_config


def _request() -> RunRequest:
    return RunRequest(
        id="scratch.request",
        template_id="scratch",
        template_inputs={"bias": 0.25},
        config_source="active",
    )


def _transition(
    *,
    run_id: str = "run-1",
    sequence: int | None = None,
) -> ExecutionTransition:
    return ExecutionTransition(
        sequence=sequence,
        run_id=run_id,
        operation_id="op-1",
        stage="action",
        effect="action",
        state="completed",
    )


def test_catalog_is_closed_versioned_json() -> None:
    catalog = ExperimentCatalog(
        revision="catalog-sha",
        experiments=(
            RegisteredExperimentDescriptor(
                id="rabi",
                version="2",
                experiment_kind="calibration",
                title="Rabi",
                input_schema={
                    "type": "object",
                    "properties": {"amplitude": {"type": "number"}},
                },
                tags=("qubit", "calibration"),
            ),
        ),
    )

    restored = ExperimentCatalog.model_validate_json(catalog.model_dump_json())

    assert restored == catalog
    with pytest.raises(ValidationError, match="unique"):
        ExperimentCatalog(
            revision="catalog-sha",
            experiments=(catalog.experiments[0], catalog.experiments[0]),
        )
    with pytest.raises(ValidationError, match="Extra inputs"):
        RegisteredExperimentDescriptor.model_validate(
            {
                **catalog.experiments[0].model_dump(),
                "factory": "module:function",
            }
        )


def test_config_registry_commands_are_closed_versioned_json() -> None:
    config = load_config()
    entry = ConfigRegistryEntry(
        id="baseline",
        config_ref="config-registry/entries/baseline/config.json",
        content_hash=config_content_hash(config),
        source=DirectConfigRegistrySource(),
        registered_by="notebook",
    )
    activation = ConfigRegistryActivationRecord(
        id="activation-1",
        generation=1,
        action="activation",
        entry_id=entry.id,
        entry_content_hash=entry.content_hash,
        operator="operator",
    )
    state = ConfigRegistryActiveState(
        generation=1,
        active_entry_id=entry.id,
        active_entry_content_hash=entry.content_hash,
        history=(activation,),
    )
    imported = ConfigImportReceipt(entry=entry)
    activated = ConfigActivationReceipt(
        active_state=state,
        activation=activation,
    )
    defaulted = ConfigDefaultReceipt(
        entry=entry,
        active_state=state,
        activation=activation,
    )
    import_command = DirectConfigImportCommand(
        entry_id=entry.id,
        config=config,
        registered_by="notebook",
    )
    activation_command = ConfigEntryActivationCommand(
        entry_id=entry.id,
        operator="operator",
        expected_generation=0,
    )
    rollback_command = ConfigRollbackCommand(
        operator="operator",
        expected_generation=1,
    )
    default_command = DirectConfigDefaultCommand(
        entry_id=entry.id,
        config=config,
        registered_by="notebook",
        operator="operator",
        expected_generation=0,
    )

    assert ConfigImportReceipt.model_validate_json(imported.model_dump_json()) == (
        imported
    )
    assert (
        ConfigActivationReceipt.model_validate_json(activated.model_dump_json())
        == activated
    )
    assert (
        ConfigDefaultReceipt.model_validate_json(defaulted.model_dump_json())
        == defaulted
    )
    assert (
        DirectConfigImportCommand.model_validate_json(import_command.model_dump_json())
        == import_command
    )
    assert (
        ConfigEntryActivationCommand.model_validate_json(
            activation_command.model_dump_json()
        )
        == activation_command
    )
    assert (
        ConfigRollbackCommand.model_validate_json(rollback_command.model_dump_json())
        == rollback_command
    )
    assert (
        DirectConfigDefaultCommand.model_validate_json(
            default_command.model_dump_json()
        )
        == default_command
    )
    with pytest.raises(ValidationError, match="history head"):
        ConfigActivationReceipt(
            active_state=state,
            activation=activation.model_copy(update={"operator": "other"}),
        )


def test_post_run_commands_are_closed_json_and_bind_proposals_to_runs() -> None:
    proposal = parameter_change_proposal_from_updates(
        source_run_id="run-1",
        source_config=load_config(),
        analysis_title="fit",
        analysis_record_id="analysis-fit",
        proposal_id="drive-frequency",
        updates=(
            replace_scalar_parameter(
                "drive_frequency",
                Quantity(value=5.1, unit="GHz"),
            ),
        ),
        reason="fit converged",
        confidence=0.9,
    )
    command = AnalysisSaveCommand(
        run_id="run-1",
        title="fit",
        analysis_key="fit",
        outputs=(
            AnalysisNoteOutputPayload(
                kind="note",
                title="summary",
                content="fit converged",
            ),
            AnalysisJsonOutputPayload(
                kind="figure",
                title="fit curve",
                content={"x": [1, 2], "y": [3, 4]},
            ),
            AnalysisParameterProposalOutputPayload(
                kind="parameter_change_proposal",
                title=proposal.id,
                content=proposal,
            ),
        ),
    )
    activation = CandidateConfigActivationCommand(
        run_id="run-1",
        proposal_ids=(proposal.id,),
        entry_id="candidate-fit",
        registered_by="notebook",
        operator="operator",
        expected_generation=1,
    )
    decision = ParameterProposalDecisionCommand(
        run_id="run-1",
        proposal_id=proposal.id,
        decision="approved",
        authority=AutomaticPolicyDecisionAuthority(
            actor="nightly-calibration",
            policy_id="fit-confidence",
            policy_version="2",
        ),
        note="fit passed policy",
    )

    assert AnalysisSaveCommand.model_validate_json(command.model_dump_json()) == command
    assert (
        CandidateConfigActivationCommand.model_validate_json(
            activation.model_dump_json()
        )
        == activation
    )
    assert (
        ParameterProposalDecisionCommand.model_validate_json(decision.model_dump_json())
        == decision
    )
    with pytest.raises(ValidationError, match="command run"):
        AnalysisSaveCommand(
            **command.model_dump(exclude={"run_id"}),
            run_id="other",
        )
    with pytest.raises(ValidationError, match="unique"):
        CandidateConfigActivationCommand(
            **activation.model_dump(exclude={"proposal_ids"}),
            proposal_ids=(proposal.id, proposal.id),
        )


def test_run_submissions_are_discriminated_without_executable_state() -> None:
    config = load_config()
    source = ConfigRegistryRunConfigSource(
        selector="active",
        entry_id="baseline",
        config_ref="config-registry/configs/baseline.json",
        content_hash=config_content_hash(config),
        registry_generation=2,
    )
    managed = ManagedRunSubmission(
        submission_id="submit-managed",
        registration_id="scratch",
        registration_version="3",
        request=_request(),
    )
    delegated = DelegatedRunSubmission(
        submission_id="submit-delegated",
        executor_id="notebook-kernel-1",
        config=config,
        config_source=source,
        request=_request(),
        plan=DelegatedPlanSummary(
            experiment_id="scratch",
            experiment_kind="scratch",
            point_count=2,
            coordinate_ids=("bias",),
            record_ids=("signal",),
            run_resource_claims=(
                ResourceClaimDescriptor(id="scope-1"),
                ResourceClaimDescriptor(id="drive-1", kind="channel"),
            ),
        ),
    )
    adapter: TypeAdapter[RunSubmission] = TypeAdapter(RunSubmission)

    assert isinstance(
        adapter.validate_json(managed.model_dump_json()),
        ManagedRunSubmission,
    )
    restored_delegated = adapter.validate_json(delegated.model_dump_json())
    assert isinstance(restored_delegated, DelegatedRunSubmission)
    assert restored_delegated.config_source == source
    with pytest.raises(ValidationError, match="unique"):
        DelegatedPlanSummary(
            experiment_id="scratch",
            experiment_kind="scratch",
            point_count=1,
            run_resource_claims=(
                ResourceClaimDescriptor(id="scope-1"),
                ResourceClaimDescriptor(id="scope-1"),
            ),
        )


def test_executor_lease_is_expiring_and_fenced() -> None:
    now = datetime.now(UTC)
    lease = ExecutorLease(
        lease_id="lease-1",
        generation=4,
        run_id="run-1",
        executor_id="notebook-kernel-1",
        issued_at=now,
        expires_at=now + timedelta(seconds=30),
        heartbeat_interval_seconds=10,
    )

    assert ExecutorLease.model_validate_json(lease.model_dump_json()) == lease
    with pytest.raises(ValidationError, match="expire after"):
        ExecutorLease(
            **lease.model_dump(exclude={"expires_at"}),
            expires_at=now,
        )
    with pytest.raises(ValidationError, match="UTC offset"):
        ExecutorLease(
            **lease.model_dump(exclude={"issued_at"}),
            issued_at=now.replace(tzinfo=None),
        )


def test_transition_batches_keep_sequences_daemon_owned() -> None:
    batch = ExecutionTransitionBatch(
        batch_id="batch-1",
        lease_id="lease-1",
        generation=2,
        run_id="run-1",
        transitions=(_transition(),),
    )
    receipt = ExecutionTransitionBatchReceipt(
        batch_id=batch.batch_id,
        committed=(
            _transition(sequence=7),
            _transition(sequence=8),
        ),
    )

    assert (
        ExecutionTransitionBatch.model_validate_json(batch.model_dump_json()) == batch
    )
    assert (
        ExecutionTransitionBatchReceipt.model_validate_json(receipt.model_dump_json())
        == receipt
    )
    with pytest.raises(ValidationError, match="daemon-assigned"):
        ExecutionTransitionBatch(
            **batch.model_dump(exclude={"transitions"}),
            transitions=(_transition(sequence=1),),
        )
    with pytest.raises(ValidationError, match="contiguous"):
        ExecutionTransitionBatchReceipt(
            batch_id="batch-2",
            committed=(
                _transition(sequence=7),
                _transition(sequence=9),
            ),
        )


def test_effect_command_ids_are_bound_to_durable_operation_identity() -> None:
    append = MeasurementDatasetAppend(
        run_id="run-1",
        dataset_id="raw-measurements",
        recording_contract_fingerprint="test.recording.v1",
        start_index=0,
        records=(
            MeasurementRecord(
                run_id="run-1",
                logical_point_id="point-0",
                point_index=0,
                coordinates={},
                observables={"signal": Quantity(value=1, unit="ratio")},
            ),
        ),
    )
    payload = PayloadEvidence(
        run_id="run-1",
        operation_id="payload-1",
        payload_id="payload",
        schema_id="schema",
        content_hash="sha256:payload",
        fingerprint={"kind": "test"},
    )
    outcome = RunOutcome(
        run_id="run-1",
        result="succeeded",
        certainty="known",
        termination_reason="completed",
    )
    terminal = RunManifest(
        run_id="run-1",
        lifecycle="terminal",
        config_content_hash=f"sha256:{'a' * 64}",
        outcome=outcome,
    )

    with pytest.raises(ValidationError, match="must match its operation"):
        MeasurementAppendCommand(
            command_id="unrelated",
            run_id="run-1",
            lease_id="lease-1",
            generation=1,
            append=append,
        )
    with pytest.raises(ValidationError, match="must match its operation"):
        PayloadCommitCommand(
            command_id="unrelated",
            run_id="run-1",
            lease_id="lease-1",
            generation=1,
            evidence=payload,
        )
    with pytest.raises(ValidationError, match="must match its run"):
        TerminalRunCommitCommand(
            command_id="unrelated",
            run_id="run-1",
            lease_id="lease-1",
            generation=1,
            manifest=terminal,
        )
