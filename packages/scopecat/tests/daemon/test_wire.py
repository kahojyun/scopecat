from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

import pyarrow as pa
import pytest
from pydantic import ValidationError

from scopecat.analysis.datasets import DerivedDataset
from scopecat.config.changes import parameter_change_proposal_from_updates
from scopecat.config.inventory import (
    InstrumentInventoryRekey,
    InstrumentInventoryRemoval,
    InstrumentInventoryRenameRekey,
)
from scopecat.config.parameters import replace_scalar_parameter
from scopecat.config.registry.records import (
    ConfigRegistryActivationRecord,
    ConfigRegistryEntry,
    DirectConfigRegistrySource,
)
from scopecat.control.models import (
    ResourceKey,
    RunDomainTargetRequirement,
    RunPlanSummary,
    RunResourceRequirement,
)
from scopecat.daemon.wire import (
    AnalysisDatasetOutputPayload,
    AnalysisFigureOutputPayload,
    AnalysisParameterProposalOutputPayload,
    AnalysisSaveCommand,
    AnalysisTableOutputPayload,
    CandidateConfigRevisionSource,
    ConfigActivationReceipt,
    ConfigEntryActivationCommand,
    ConfigPublishCommand,
    ConfigPublishReceipt,
    ConfigUndoCommand,
    DirectConfigRevisionSource,
    ExecutionTransitionAppend,
    ExecutionTransitionClaim,
    ExecutorLease,
    InstrumentConfiguredDefaultsApplyCommand,
    InstrumentConfiguredDefaultsApplyReceipt,
    InstrumentInventoryMigrationCommand,
    InstrumentInventoryMigrationReceipt,
    InstrumentSessionLeaseReceipt,
    InstrumentSessionOpenReceipt,
    RunHardwareBatchCommand,
    RunHardwareFinishCommand,
    RunInstrumentProvisionCommand,
    RunInstrumentProvisionReceipt,
    RunSubmission,
)
from scopecat.kernel.problems import Problem, ProblemPhase
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.records.analysis import (
    MAX_ANALYSIS_OUTPUTS,
    MAX_ANALYSIS_TABLE_COLUMNS,
    MAX_ANALYSIS_TABLE_ROWS,
    AnalysisFigure,
    AnalysisFigureAxis,
    AnalysisFigureSeries,
    AnalysisTable,
    AnalysisTableColumn,
    AnalysisTableRow,
)
from scopecat.records.config import config_content_hash
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.records.run import ConfigRegistryRunConfigSource
from scopecat.records.run_request import RunRequest
from scopecat.sdk.instruments import InstrumentDescription
from scopecat.sdk.instruments.commands import InstrumentStateAssignment
from scopecat.sdk.instruments.execution import RunHardwareApply, RunHardwareBatch
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
        stage="domain_execute",
        effect="read",
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


def test_instrument_inventory_migration_is_discriminated_closed_json() -> None:
    config = load_config()
    changes = (
        InstrumentInventoryRemoval(
            instrument_id="retired-source",
            exclusivity_key="retired-source",
        ),
        InstrumentInventoryRekey(
            instrument_id="source-0",
            from_exclusivity_key="source-0",
            to_exclusivity_key="rack-a/source",
        ),
        InstrumentInventoryRenameRekey(
            from_instrument_id="old-meter",
            to_instrument_id="meter-0",
            from_exclusivity_key="old-meter",
            to_exclusivity_key="rack-a/meter",
        ),
    )
    command = InstrumentInventoryMigrationCommand(
        config=config,
        entry_id="inventory-v2",
        changes=changes,
        actor="operator",
        expected_generation=1,
    )
    entry = ConfigRegistryEntry(
        id=command.entry_id,
        config_ref="config-registry/entries/inventory-v2/config.json",
        content_hash=config_content_hash(config),
        source=DirectConfigRegistrySource(),
        actor=command.actor,
    )
    receipt = InstrumentInventoryMigrationReceipt(
        entry=entry,
        activation=ConfigRegistryActivationRecord(
            generation=2,
            action="inventory_migration",
            entry_id=entry.id,
            entry_content_hash=entry.content_hash,
            actor=command.actor,
        ),
        changes=changes,
    )

    restored = InstrumentInventoryMigrationCommand.model_validate_json(
        command.model_dump_json()
    )

    assert restored == command
    assert isinstance(restored.changes[0], InstrumentInventoryRemoval)
    assert isinstance(restored.changes[1], InstrumentInventoryRekey)
    assert isinstance(restored.changes[2], InstrumentInventoryRenameRekey)
    assert (
        InstrumentInventoryMigrationReceipt.model_validate_json(
            receipt.model_dump_json()
        )
        == receipt
    )


def test_instrument_inventory_rekey_rejects_a_noop() -> None:
    with pytest.raises(ValidationError, match="must change"):
        InstrumentInventoryRekey(
            instrument_id="source-0",
            from_exclusivity_key="source-0",
            to_exclusivity_key="source-0",
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
            AnalysisDatasetOutputPayload(
                kind="dataset",
                id="fits",
                title="fit data",
                content=DerivedDataset.from_arrow(
                    pa.table({"bias": [1.0, 2.0], "signal": [3.0, 4.0]}),
                    coordinates=("bias",),
                ).to_payload(),
            ),
            AnalysisFigureOutputPayload(
                kind="figure",
                title="fit curve",
                content=AnalysisFigure(
                    kind="line",
                    x_axis=AnalysisFigureAxis(label="Bias", unit="V"),
                    y_axis=AnalysisFigureAxis(label="Signal", unit="ratio"),
                    series=[
                        AnalysisFigureSeries(
                            id="fit",
                            x=[1.0, 2.0],
                            y=[3.0, 4.0],
                        )
                    ],
                ),
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


def test_analysis_save_command_bounds_embedded_output_group() -> None:
    table = AnalysisTable(
        columns=[
            AnalysisTableColumn(id=f"column-{index}")
            for index in range(MAX_ANALYSIS_TABLE_COLUMNS)
        ],
        rows=[
            AnalysisTableRow(cells=[index] * MAX_ANALYSIS_TABLE_COLUMNS)
            for index in range(MAX_ANALYSIS_TABLE_ROWS)
        ],
    )
    output = AnalysisTableOutputPayload(
        kind="table",
        title="large table",
        content=table,
    )

    with pytest.raises(ValidationError, match="total table cell count"):
        AnalysisSaveCommand(
            title="large tables",
            analysis_key="large-tables",
            outputs=(output,) * 5,
        )
    with pytest.raises(ValidationError, match=f"at most {MAX_ANALYSIS_OUTPUTS} items"):
        AnalysisSaveCommand(
            title="too many outputs",
            analysis_key="too-many-outputs",
            outputs=(output,) * (MAX_ANALYSIS_OUTPUTS + 1),
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
            host_provider_id="tests.provider",
            host_contract_fingerprint="0" * 64,
            domain_target_requirement=RunDomainTargetRequirement(
                id="controller-1",
                kind="tests.controller",
                instrument_ids=(),
            ),
            run_resource_requirements=(RunResourceRequirement(id="scope-1"),),
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
            run_resource_requirements=(
                RunResourceRequirement(id="scope-1"),
                RunResourceRequirement(id="scope-1"),
            ),
        )
    RunPlanSummary(
        experiment_id="scratch",
        experiment_kind="scratch",
        point_count=1,
        run_resource_requirements=(RunResourceRequirement(id="scope-1"),),
    )
    with pytest.raises(ValidationError, match="host instrument order"):
        RunPlanSummary(
            experiment_id="scratch",
            experiment_kind="scratch",
            point_count=1,
            host_instrument_order=("scope-2",),
            run_resource_requirements=(RunResourceRequirement(id="scope-1"),),
        )


def test_domain_target_summary_uses_only_its_instrument_footprint() -> None:
    summary = RunPlanSummary(
        experiment_id="domain",
        experiment_kind="domain",
        point_count=1,
        domain_target_requirement=RunDomainTargetRequirement(
            id="tests.domain.target",
            kind="tests.domain",
            instrument_ids=("source-0",),
        ),
        run_resource_requirements=(RunResourceRequirement(id="source-0"),),
    )

    assert summary.run_resource_requirements == (RunResourceRequirement(id="source-0"),)


def test_domain_target_summary_requires_its_complete_instrument_footprint() -> None:
    with pytest.raises(ValidationError, match="omits domain target instruments"):
        RunPlanSummary(
            experiment_id="domain",
            experiment_kind="domain",
            point_count=1,
            domain_target_requirement=RunDomainTargetRequirement(
                id="tests.domain.target",
                kind="tests.domain",
                instrument_ids=("source-0",),
            ),
            run_resource_requirements=(),
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


@pytest.mark.parametrize(
    "command_type",
    [ExecutionTransitionAppend, ExecutionTransitionClaim],
)
def test_transition_commands_keep_sequence_daemon_owned(
    command_type: type[ExecutionTransitionAppend | ExecutionTransitionClaim],
) -> None:
    command = command_type(lease_id="lease-1", transition=_transition())

    assert command_type.model_validate_json(command.model_dump_json()) == command
    with pytest.raises(ValidationError, match="daemon-assigned"):
        command_type(
            lease_id="lease-1",
            transition=_transition(sequence=1),
        )


def test_run_hardware_commands_bind_fence_and_batch_identity() -> None:
    provision = RunInstrumentProvisionCommand(
        lease_id="lease-1",
        operation_id="lifecycle.provide-instruments",
    )
    receipt = RunInstrumentProvisionReceipt(
        run_id="run-1",
        operation_id=provision.operation_id,
        status="ready",
    )
    batch = RunHardwareBatch(
        operation_id="hardware.batch-1",
        actions=(
            RunHardwareApply(
                effect_id="point-0.apply.source-0",
                point_index=0,
                instrument_id="source-0",
                assignments=(
                    InstrumentStateAssignment(
                        resource_id="source-0",
                        interface_id="test.set_frequency/v1",
                        property_id="frequency",
                        value=StateValue(Quantity(5.0, "GHz")),
                    ),
                ),
            ),
        ),
    )
    execute = RunHardwareBatchCommand(
        lease_id="lease-1",
        batch=batch,
    )
    finish = RunHardwareFinishCommand(
        lease_id="lease-1",
        operation_id="hardware.finish",
        failed=False,
    )

    assert (
        RunInstrumentProvisionCommand.model_validate_json(provision.model_dump_json())
        == provision
    )
    assert (
        RunInstrumentProvisionReceipt.model_validate_json(receipt.model_dump_json())
        == receipt
    )
    assert (
        RunHardwareBatchCommand.model_validate_json(execute.model_dump_json())
        == execute
    )
    assert (
        RunHardwareFinishCommand.model_validate_json(finish.model_dump_json()) == finish
    )
    with pytest.raises(ValidationError, match="effect ids must be unique"):
        RunHardwareBatch(
            operation_id="hardware.duplicate",
            actions=(batch.actions[0], batch.actions[0]),
        )


def test_run_hardware_apply_rejects_duplicate_physical_targets() -> None:
    assignment = InstrumentStateAssignment(
        resource_id="source-0",
        interface_id="test.set_frequency/v1",
        property_id="frequency",
        value=StateValue(Quantity(5.0, "GHz")),
        entity_ids=["q0"],
    )

    with pytest.raises(ValidationError, match="property targets must be unique"):
        RunHardwareApply(
            effect_id="point-0.apply.source-0",
            point_index=0,
            instrument_id="source-0",
            assignments=(
                assignment,
                assignment.model_copy(update={"entity_ids": ["q1"]}),
            ),
        )


def test_run_instrument_provision_state_evidence_matches_instrument_order() -> None:
    source_a = InstrumentStateSnapshot(instrument_id="source-a")
    source_b = InstrumentStateSnapshot(instrument_id="source-b")

    receipt = RunInstrumentProvisionReceipt(
        run_id="run-1",
        operation_id="lifecycle.provide-instruments",
        status="ready",
        instrument_ids=("source-a", "source-b"),
        observed_state=(source_a, source_b),
        baseline_state=(source_a, source_b),
    )

    assert (
        RunInstrumentProvisionReceipt.model_validate_json(receipt.model_dump_json())
        == receipt
    )
    with pytest.raises(ValidationError, match="observed state must match"):
        RunInstrumentProvisionReceipt(
            run_id="run-1",
            operation_id="lifecycle.provide-instruments",
            status="ready",
            instrument_ids=("source-a", "source-b"),
            observed_state=(source_b, source_a),
            baseline_state=(source_a, source_b),
        )
    with pytest.raises(ValidationError, match="baseline state must match"):
        RunInstrumentProvisionReceipt(
            run_id="run-1",
            operation_id="lifecycle.provide-instruments",
            status="ready",
            instrument_ids=("source-a", "source-b"),
            observed_state=(source_a, source_b),
            baseline_state=(source_b, source_a),
        )


def test_rejected_run_instrument_provision_has_no_state_evidence() -> None:
    source = InstrumentStateSnapshot(instrument_id="source-a")
    problem = Problem(
        code="instrument_unavailable",
        phase=ProblemPhase.EXECUTION,
        message="instrument unavailable",
    )

    receipt = RunInstrumentProvisionReceipt(
        run_id="run-1",
        operation_id="lifecycle.provide-instruments",
        status="rejected",
        instrument_ids=("source-a",),
        problems=(problem,),
    )

    assert receipt.observed_state == ()
    assert receipt.baseline_state == ()
    with pytest.raises(ValidationError, match="cannot expose state evidence"):
        RunInstrumentProvisionReceipt(
            run_id="run-1",
            operation_id="lifecycle.provide-instruments",
            status="rejected",
            instrument_ids=("source-a",),
            problems=(problem,),
            observed_state=(source,),
        )


def test_instrument_session_open_requires_ordered_observed_state() -> None:
    instrument_ids = ("source-a", "source-b")
    descriptions = tuple(
        InstrumentDescription(
            instrument_id=instrument_id,
            implementation_id="tests.source",
            implementation_version="1",
        )
        for instrument_id in instrument_ids
    )
    observed_state = tuple(
        InstrumentStateSnapshot(instrument_id=instrument_id)
        for instrument_id in instrument_ids
    )
    receipt = InstrumentSessionOpenReceipt(
        session_id="session-1",
        actor="alice",
        config_entry_id="baseline",
        config_content_hash=f"sha256:{'0' * 64}",
        instrument_ids=instrument_ids,
        configured_default_instrument_ids=("source-b",),
        descriptions=descriptions,
        observed_state=observed_state,
        opened_at=datetime(2026, 7, 29, tzinfo=UTC),
        renewed_at=datetime(2026, 7, 29, tzinfo=UTC),
        expires_at=datetime(2026, 7, 29, 0, 1, tzinfo=UTC),
    )

    assert (
        InstrumentSessionOpenReceipt.model_validate_json(receipt.model_dump_json())
        == receipt
    )
    for invalid_state in (
        observed_state[:1],
        tuple(reversed(observed_state)),
    ):
        with pytest.raises(
            ValidationError,
            match="observed state must match instrument_ids in order",
        ):
            InstrumentSessionOpenReceipt(
                **receipt.model_dump(exclude={"observed_state"}),
                observed_state=invalid_state,
            )
    with pytest.raises(ValidationError, match="must follow renewed_at"):
        InstrumentSessionOpenReceipt(
            **receipt.model_dump(exclude={"expires_at"}),
            expires_at=receipt.renewed_at,
        )


def test_instrument_session_lease_requires_an_aware_ordered_window() -> None:
    renewed_at = datetime(2026, 7, 29, tzinfo=UTC)
    receipt = InstrumentSessionLeaseReceipt(
        session_id="session-1",
        renewed_at=renewed_at,
        expires_at=renewed_at + timedelta(minutes=1),
    )

    assert (
        InstrumentSessionLeaseReceipt.model_validate_json(receipt.model_dump_json())
        == receipt
    )
    with pytest.raises(ValidationError, match="renewed_at must include a UTC offset"):
        InstrumentSessionLeaseReceipt(
            session_id="session-1",
            renewed_at=renewed_at.replace(tzinfo=None),
            expires_at=receipt.expires_at,
        )
    with pytest.raises(ValidationError, match="expires_at must include a UTC offset"):
        InstrumentSessionLeaseReceipt(
            session_id="session-1",
            renewed_at=renewed_at,
            expires_at=receipt.expires_at.replace(tzinfo=None),
        )
    with pytest.raises(ValidationError, match="must follow renewed_at"):
        InstrumentSessionLeaseReceipt(
            session_id="session-1",
            renewed_at=renewed_at,
            expires_at=renewed_at,
        )


def test_configured_defaults_apply_command_requires_operation_identity() -> None:
    command = InstrumentConfiguredDefaultsApplyCommand(operation_id="defaults.apply-1")

    assert (
        InstrumentConfiguredDefaultsApplyCommand.model_validate_json(
            command.model_dump_json()
        )
        == command
    )
    with pytest.raises(ValidationError):
        InstrumentConfiguredDefaultsApplyCommand(operation_id="")


@pytest.mark.parametrize("status", ["applied", "unchanged"])
def test_successful_configured_defaults_apply_requires_synchronized_state(
    status: Literal["applied", "unchanged"],
) -> None:
    state = InstrumentStateSnapshot(instrument_id="source-a")
    receipt = InstrumentConfiguredDefaultsApplyReceipt(
        session_id="session-1",
        operation_id="defaults.apply-1",
        instrument_id="source-a",
        config_entry_id="baseline",
        status=status,
        state=state,
    )

    assert (
        InstrumentConfiguredDefaultsApplyReceipt.model_validate_json(
            receipt.model_dump_json()
        )
        == receipt
    )
    with pytest.raises(ValidationError, match="requires synchronized state"):
        InstrumentConfiguredDefaultsApplyReceipt(
            **receipt.model_dump(exclude={"state"})
        )
    with pytest.raises(ValidationError, match="cannot contain problems"):
        InstrumentConfiguredDefaultsApplyReceipt(
            **receipt.model_dump(exclude={"problems"}),
            problems=(_configured_defaults_problem(),),
        )
    with pytest.raises(ValidationError, match="must match instrument_id"):
        InstrumentConfiguredDefaultsApplyReceipt(
            **receipt.model_dump(exclude={"state"}),
            state=state.model_copy(update={"instrument_id": "source-b"}),
        )


def test_rejected_configured_defaults_apply_has_problem_without_state() -> None:
    receipt = InstrumentConfiguredDefaultsApplyReceipt(
        session_id="session-1",
        operation_id="defaults.apply-1",
        instrument_id="source-a",
        config_entry_id="baseline",
        status="rejected",
        problems=(_configured_defaults_problem(),),
    )

    assert (
        InstrumentConfiguredDefaultsApplyReceipt.model_validate_json(
            receipt.model_dump_json()
        )
        == receipt
    )
    with pytest.raises(ValidationError, match="requires a problem"):
        InstrumentConfiguredDefaultsApplyReceipt(
            **receipt.model_dump(exclude={"problems"})
        )
    with pytest.raises(ValidationError, match="cannot report state"):
        InstrumentConfiguredDefaultsApplyReceipt(
            **receipt.model_dump(exclude={"state"}),
            state=InstrumentStateSnapshot(instrument_id="source-a"),
        )


def _configured_defaults_problem() -> Problem:
    return Problem(
        code="configured_defaults_rejected",
        phase=ProblemPhase.EXECUTION,
        message="configured defaults were rejected",
    )
