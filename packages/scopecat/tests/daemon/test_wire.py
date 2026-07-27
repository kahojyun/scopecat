from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from scopecat.config.changes import parameter_change_proposal_from_updates
from scopecat.config.parameters import replace_scalar_parameter
from scopecat.config.registry.records import (
    ConfigRegistryActivationRecord,
    ConfigRegistryEntry,
    DirectConfigRegistrySource,
)
from scopecat.control.models import ResourceKey, RunPlanSummary
from scopecat.daemon.wire import (
    AnalysisJsonOutputPayload,
    AnalysisParameterProposalOutputPayload,
    AnalysisSaveCommand,
    CandidateConfigRevisionSource,
    ConfigActivationReceipt,
    ConfigEntryActivationCommand,
    ConfigPublishCommand,
    ConfigPublishReceipt,
    ConfigUndoCommand,
    DirectConfigRevisionSource,
    ExecutionTransitionAppend,
    ExecutorLease,
    MeasurementAppendCommand,
    RunInstrumentApplyCommand,
    RunInstrumentLifecycleCommand,
    RunInstrumentProvisionCommand,
    RunInstrumentProvisionReceipt,
    RunSubmission,
    TerminalRunCommitCommand,
)
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.run_outcome import RunOutcome
from scopecat.records.config import config_content_hash
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.measurement_recording import MeasurementDatasetAppend
from scopecat.records.run import ConfigRegistryRunConfigSource
from scopecat.records.run_request import RunRequest
from scopecat.sdk.instruments.contracts import InstrumentStateCommand
from tests.testkit.workflow_fixtures import load_config


def _request() -> RunRequest:
    return RunRequest(
        experiment_id="scratch",
        inputs={"bias": 0.25},
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
        stage="apply_state",
        effect="state_write",
        state="completed",
    )


def test_config_registry_commands_are_closed_typed_json() -> None:
    config = load_config()
    entry = ConfigRegistryEntry(
        id="baseline",
        config_ref="config-registry/entries/baseline/config.json",
        content_hash=config_content_hash(config),
        source=DirectConfigRegistrySource(),
        actor="notebook",
    )
    activation = ConfigRegistryActivationRecord(
        generation=1,
        action="activation",
        entry_id=entry.id,
        entry_content_hash=entry.content_hash,
        actor="operator",
    )
    activated = ConfigActivationReceipt(
        activation=activation,
    )
    published = ConfigPublishReceipt(
        entry=entry,
        activation=activation,
    )
    publish_command = ConfigPublishCommand(
        source=DirectConfigRevisionSource(config=config),
        entry_id=entry.id,
        actor="notebook",
        expected_generation=0,
    )
    activation_command = ConfigEntryActivationCommand(
        entry_id=entry.id,
        actor="operator",
        expected_generation=0,
    )
    undo_command = ConfigUndoCommand(
        actor="operator",
        expected_generation=1,
    )

    assert (
        ConfigActivationReceipt.model_validate_json(activated.model_dump_json())
        == activated
    )
    assert (
        ConfigPublishReceipt.model_validate_json(published.model_dump_json())
        == published
    )
    assert (
        ConfigEntryActivationCommand.model_validate_json(
            activation_command.model_dump_json()
        )
        == activation_command
    )
    assert (
        ConfigUndoCommand.model_validate_json(undo_command.model_dump_json())
        == undo_command
    )
    assert (
        ConfigPublishCommand.model_validate_json(publish_command.model_dump_json())
        == publish_command
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
        title="fit",
        analysis_key="fit",
        outputs=(
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
    publish = ConfigPublishCommand(
        source=CandidateConfigRevisionSource(
            run_id="run-1",
            proposal_id=proposal.id,
        ),
        entry_id="candidate-fit",
        actor="operator",
        expected_generation=1,
        note="fit reviewed",
    )

    assert AnalysisSaveCommand.model_validate_json(command.model_dump_json()) == command
    assert (
        ConfigPublishCommand.model_validate_json(publish.model_dump_json()) == publish
    )
    with pytest.raises(ValidationError, match="identify the command analysis"):
        AnalysisSaveCommand(
            **command.model_dump(exclude={"outputs"}),
            outputs=(
                AnalysisParameterProposalOutputPayload(
                    kind="parameter_change_proposal",
                    title=proposal.id,
                    content=proposal.model_copy(
                        update={"analysis_record_id": "analysis-other"}
                    ),
                ),
            ),
        )


def test_run_submission_is_closed_typed_json_without_executable_state() -> None:
    config = load_config()
    source = ConfigRegistryRunConfigSource(
        selector="active",
        entry_id="baseline",
        config_ref="config-registry/configs/baseline.json",
        content_hash=config_content_hash(config),
        registry_generation=2,
    )
    submission = RunSubmission(
        submission_id="submit-1",
        config=config,
        config_source=source,
        request=_request(),
        plan=RunPlanSummary(
            experiment_id="scratch",
            experiment_kind="scratch",
            point_count=2,
            coordinate_ids=("bias",),
            record_ids=("signal",),
            host_instrument_order=("scope-1",),
            run_resource_claims=(
                ResourceKey(id="scope-1"),
                ResourceKey(id="controller-1", kind="target"),
            ),
        ),
    )
    restored = RunSubmission.model_validate_json(submission.model_dump_json())
    assert restored == submission
    assert restored.config_source == source
    with pytest.raises(ValidationError):
        ResourceKey.model_validate({"id": "drive-1", "kind": "channel"})
    with pytest.raises(ValidationError, match="unique"):
        RunPlanSummary(
            experiment_id="scratch",
            experiment_kind="scratch",
            point_count=1,
            run_resource_claims=(
                ResourceKey(id="scope-1"),
                ResourceKey(id="scope-1"),
            ),
        )
    RunPlanSummary(
        experiment_id="scratch",
        experiment_kind="scratch",
        point_count=1,
        run_resource_claims=(ResourceKey(id="scope-1"),),
    )
    with pytest.raises(ValidationError, match="host_instrument_order"):
        RunPlanSummary(
            experiment_id="scratch",
            experiment_kind="scratch",
            point_count=1,
            host_instrument_order=("scope-2",),
            run_resource_claims=(ResourceKey(id="scope-1"),),
        )


def test_executor_lease_is_expiring_and_fenced() -> None:
    now = datetime.now(UTC)
    lease = ExecutorLease(
        lease_id="lease-1",
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


def test_transition_append_keeps_sequence_daemon_owned() -> None:
    command = ExecutionTransitionAppend(
        lease_id="lease-1",
        transition=_transition(),
    )

    assert (
        ExecutionTransitionAppend.model_validate_json(command.model_dump_json())
        == command
    )
    with pytest.raises(ValidationError, match="daemon-assigned"):
        ExecutionTransitionAppend(
            lease_id="lease-1",
            transition=_transition(sequence=1),
        )


def test_run_instrument_commands_bind_fence_and_operation_identity() -> None:
    provision = RunInstrumentProvisionCommand(
        lease_id="lease-1",
        operation_id="lifecycle.provide-instruments",
    )
    receipt = RunInstrumentProvisionReceipt(
        run_id="run-1",
        operation_id=provision.operation_id,
        status="ready",
    )
    apply = RunInstrumentApplyCommand(
        lease_id="lease-1",
        operation_id="point-0.apply.source-0",
        command=InstrumentStateCommand(
            operation_id="point-0.apply.source-0",
            instrument_id="source-0",
        ),
    )
    lifecycle = RunInstrumentLifecycleCommand(
        lease_id="lease-1",
        operation_id="lifecycle.close.source-0",
        action="close",
    )

    assert (
        RunInstrumentProvisionCommand.model_validate_json(provision.model_dump_json())
        == provision
    )
    assert (
        RunInstrumentProvisionReceipt.model_validate_json(receipt.model_dump_json())
        == receipt
    )
    assert lifecycle.action == "close"
    with pytest.raises(ValidationError, match="operation ids must match"):
        RunInstrumentApplyCommand(
            lease_id="lease-1",
            operation_id="different-operation",
            command=apply.command,
        )


def test_effect_commands_do_not_repeat_durable_identity() -> None:
    append = MeasurementDatasetAppend(
        run_id="run-1",
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
    outcome = RunOutcome(
        run_id="run-1",
        result="succeeded",
        certainty="known",
    )
    append_command = MeasurementAppendCommand(
        lease_id="lease-1",
        append=append,
    )
    terminal_command = TerminalRunCommitCommand(
        lease_id="lease-1",
        outcome=outcome,
    )

    assert set(append_command.model_dump()) == {"lease_id", "append"}
    assert set(terminal_command.model_dump()) == {
        "lease_id",
        "outcome",
        "contents",
        "models",
    }
