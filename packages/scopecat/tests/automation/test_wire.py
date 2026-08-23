from datetime import UTC, datetime, timedelta

import pytest
from pydantic import JsonValue, ValidationError
from scopecat_testkit.records import assert_model_round_trip

from scopecat.automation import (
    ProcedureCloseCommand,
    ProcedureCloseReceipt,
    ProcedureClosure,
    ProcedureDefinitionRef,
    ProcedureRun,
    ProcedureRunAttentionCommand,
    ProcedureRunAttentionReceipt,
    ProcedureRunListQuery,
    ProcedureRunPage,
    ProcedureRunState,
    ProcedureStepAttempt,
    ProcedureStepAttemptListQuery,
    ProcedureStepAttemptPage,
    ProcedureStepAttentionCommand,
    ProcedureStepAttentionReceipt,
    ProcedureStepAttentionRetryCommand,
    ProcedureStepAttentionRetryReceipt,
    ProcedureStepBeginCommand,
    ProcedureStepBeginReceipt,
    ProcedureStepCompleteCommand,
    ProcedureStepCompleteReceipt,
    ProcedureStepFailCommand,
    ProcedureStepFailReceipt,
    ProcedureSubmitCommand,
    ProcedureWorkerLease,
    ProcedureWorkerLeaseAcquireCommand,
    ProcedureWorkerLeaseAcquireReceipt,
    ProcedureWorkerLeaseHeartbeatCommand,
    ProcedureWorkerLeaseHeartbeatReceipt,
    ProcedureWorkerLeaseReleaseCommand,
    ProcedureWorkerLeaseReleaseReceipt,
    RunOutputRef,
    procedure_intent_hash,
    procedure_step_operation_id,
)

_DEFINITION_HASH = "sha256:" + "1" * 64
_STEP_HASH = "sha256:" + "2" * 64
_CONFIG_HASH = "sha256:" + "3" * 64
_START = datetime(2026, 8, 18, tzinfo=UTC)
_LATER = _START + timedelta(seconds=5)
_INTENT: dict[str, JsonValue] = {"target_ids": ["q0"]}
_FENCE = "fence-1"


def _definition() -> ProcedureDefinitionRef:
    return ProcedureDefinitionRef(
        id="drag-calibration",
        version="1",
        fingerprint=_DEFINITION_HASH,
    )


def _run(
    state: ProcedureRunState,
    *,
    revision: int = 1,
) -> ProcedureRun:
    details: dict[str, object] = {}
    if state == "attention_required":
        details["attention_reason"] = "worker cannot continue"
    elif state == "closed":
        details["closure"] = ProcedureClosure(
            status="succeeded",
            closed_at=_LATER,
        )
    return ProcedureRun.model_validate(
        {
            "procedure_run_id": "procedure-1",
            "request_key": "drag-q0",
            "definition": _definition(),
            "intent": _INTENT,
            "intent_hash": procedure_intent_hash(_definition(), _INTENT),
            "revision": revision,
            "state": state,
            "created_at": _START,
            "updated_at": _LATER,
            **details,
        }
    )


def _step(
    state: str,
    *,
    operation: str = "run",
) -> ProcedureStepAttempt:
    details: dict[str, object] = {}
    if state == "succeeded":
        details.update(
            finished_at=_LATER,
            output=RunOutputRef(run_id="run-child"),
        )
    elif state == "failed":
        details.update(
            finished_at=_LATER,
            failure_reason="worker cannot continue",
        )
    elif state == "attention_required":
        details["attention_reason"] = "worker cannot continue"
    return ProcedureStepAttempt.model_validate(
        {
            "procedure_run_id": "procedure-1",
            "step_key": "baseline",
            "attempt": 1,
            "operation": operation,
            "intent_hash": _STEP_HASH,
            "revision": 2,
            "state": state,
            "started_at": _START,
            "updated_at": _LATER,
            **details,
        }
    )


def _lease() -> ProcedureWorkerLease:
    return ProcedureWorkerLease(
        procedure_run_id="procedure-1",
        worker_id="worker-1",
        lease_token=_FENCE,
        issued_at=_START,
        renewed_at=_START,
        expires_at=_LATER,
        heartbeat_interval_seconds=1,
    )


def test_submit_command_hashes_and_round_trips_canonical_intent() -> None:
    command = ProcedureSubmitCommand(
        request_key="drag-q0",
        definition=_definition(),
        intent=_INTENT,
    )

    restored = assert_model_round_trip(command)

    assert restored == command
    assert command.intent_hash == procedure_intent_hash(_definition(), _INTENT)
    assert (
        assert_model_round_trip(
            ProcedureSubmitCommand.model_validate_json(command.model_dump_json())
        )
        == command
    )


def test_submit_command_rejects_non_json_intent_with_intent_path() -> None:
    with pytest.raises(ValidationError, match=r"intent\.nested\.value"):
        ProcedureSubmitCommand(
            request_key="drag-q0",
            definition=_definition(),
            intent={"nested": {"value": object()}},
        )


def test_procedure_run_page_is_bounded_and_has_unique_runs() -> None:
    run = _run("ready")

    assert (
        ProcedureRunListQuery(limit=200, state="attention_required").state
        == "attention_required"
    )
    assert assert_model_round_trip(ProcedureRunPage(items=(run,))) == (
        ProcedureRunPage(items=(run,))
    )
    with pytest.raises(ValidationError):
        ProcedureRunListQuery(limit=201)
    with pytest.raises(ValidationError, match="page ids must be unique"):
        ProcedureRunPage(items=(run, run))


def test_procedure_step_attempt_page_is_bounded_owned_and_unique() -> None:
    step = _step("running")
    page = ProcedureStepAttemptPage(
        procedure_run_id="procedure-1",
        items=(step,),
        next_cursor=4,
    )

    assert ProcedureStepAttemptListQuery(limit=200).limit == 200
    assert assert_model_round_trip(page) == page
    with pytest.raises(ValidationError):
        ProcedureStepAttemptListQuery(limit=201)
    with pytest.raises(ValidationError, match="identities must be unique"):
        ProcedureStepAttemptPage(
            procedure_run_id="procedure-1",
            items=(step, step),
        )
    with pytest.raises(ValidationError, match="must belong to its run"):
        ProcedureStepAttemptPage(
            procedure_run_id="procedure-other",
            items=(step,),
        )


def test_worker_lease_commands_and_receipts_are_fenced() -> None:
    leased = _run("leased", revision=2)
    lease = _lease()
    acquire = ProcedureWorkerLeaseAcquireCommand(
        procedure_run_id="procedure-1",
        worker_id="worker-1",
        expected_run_revision=1,
    )
    heartbeat = ProcedureWorkerLeaseHeartbeatCommand(
        procedure_run_id="procedure-1",
        lease_token=_FENCE,
    )
    release = ProcedureWorkerLeaseReleaseCommand(
        procedure_run_id="procedure-1",
        lease_token=_FENCE,
        expected_run_revision=2,
    )

    assert assert_model_round_trip(acquire) == acquire
    assert assert_model_round_trip(heartbeat) == heartbeat
    assert assert_model_round_trip(release) == release
    assert (
        assert_model_round_trip(
            ProcedureWorkerLeaseAcquireReceipt(run=leased, lease=lease)
        ).lease
        == lease
    )
    assert (
        assert_model_round_trip(
            ProcedureWorkerLeaseHeartbeatReceipt(run=leased, lease=lease)
        ).run
        == leased
    )
    release_receipt = ProcedureWorkerLeaseReleaseReceipt(run=_run("ready", revision=3))
    assert release_receipt.run.state == "ready"


def test_worker_lease_requires_aware_ordered_times_and_matching_run() -> None:
    with pytest.raises(ValidationError, match="UTC offset"):
        ProcedureWorkerLease(
            **_lease().model_dump(exclude={"issued_at"}),
            issued_at=_START.replace(tzinfo=None),
        )
    with pytest.raises(ValidationError, match="identities must match"):
        ProcedureWorkerLeaseAcquireReceipt(
            run=_run("leased").model_copy(
                update={"procedure_run_id": "procedure-other"}
            ),
            lease=_lease(),
        )


def test_step_begin_returns_deterministic_side_effect_operation_id() -> None:
    upstream = RunOutputRef(run_id="run-upstream")
    command = ProcedureStepBeginCommand(
        procedure_run_id="procedure-1",
        lease_token=_FENCE,
        expected_run_revision=2,
        step_key="baseline",
        operation="run",
        intent_hash=_STEP_HASH,
        inputs=(upstream,),
    )
    step = _step("running")
    operation_id = procedure_step_operation_id(
        step.procedure_run_id,
        step.step_key,
    )
    receipt = ProcedureStepBeginReceipt(
        run=_run("leased"),
        step=step,
        operation_id=operation_id,
    )

    assert assert_model_round_trip(command) == command
    assert assert_model_round_trip(receipt) == receipt
    with pytest.raises(ValidationError, match="must be deterministic"):
        ProcedureStepBeginReceipt(
            run=_run("leased"),
            step=step,
            operation_id="random-id",
        )
    with pytest.raises(ValidationError, match="input references must be unique"):
        ProcedureStepBeginCommand(
            **command.model_dump(exclude={"inputs"}),
            inputs=(upstream, upstream),
        )


def test_step_terminal_commands_carry_run_and_step_revisions() -> None:
    complete = ProcedureStepCompleteCommand(
        procedure_run_id="procedure-1",
        lease_token=_FENCE,
        expected_run_revision=2,
        step_key="baseline",
        attempt=1,
        expected_step_revision=1,
        output=RunOutputRef(run_id="run-child"),
    )
    fail = ProcedureStepFailCommand(
        procedure_run_id="procedure-1",
        lease_token=_FENCE,
        expected_run_revision=2,
        step_key="baseline",
        attempt=1,
        expected_step_revision=1,
        reason="worker cannot continue",
    )

    assert assert_model_round_trip(complete).expected_step_revision == 1
    assert assert_model_round_trip(fail).expected_run_revision == 2
    assert (
        ProcedureStepCompleteReceipt(
            run=_run("leased"),
            step=_step("succeeded"),
        ).step.state
        == "succeeded"
    )
    assert (
        ProcedureStepFailReceipt(
            run=_run("leased"),
            step=_step("failed"),
        ).run.state
        == "leased"
    )


def test_step_and_run_attention_are_distinct_fenced_mutations() -> None:
    step_command = ProcedureStepAttentionCommand(
        procedure_run_id="procedure-1",
        lease_token=_FENCE,
        expected_run_revision=2,
        step_key="baseline",
        attempt=1,
        expected_step_revision=2,
        reason="worker cannot continue",
    )
    run_command = ProcedureRunAttentionCommand(
        procedure_run_id="procedure-1",
        lease_token=_FENCE,
        expected_run_revision=2,
        reason="worker cannot continue",
    )

    assert assert_model_round_trip(step_command).expected_step_revision == 2
    assert assert_model_round_trip(run_command).expected_run_revision == 2
    assert (
        ProcedureStepAttentionReceipt(
            run=_run("attention_required"),
            step=_step("attention_required"),
        ).step.state
        == "attention_required"
    )
    assert ProcedureRunAttentionReceipt(run=_run("attention_required")).run.state == (
        "attention_required"
    )
    retry = ProcedureStepAttentionRetryCommand(
        procedure_run_id="procedure-1",
        expected_run_revision=3,
        step_key="baseline",
        attempt=1,
        expected_step_revision=3,
    )
    assert assert_model_round_trip(retry).step_key == "baseline"
    assert (
        ProcedureStepAttentionRetryReceipt(
            run=_run("ready"),
            step=_step("attention_required"),
        ).run.state
        == "ready"
    )


def test_close_is_fenced_and_returns_state_specific_receipt() -> None:
    close = ProcedureCloseCommand(
        procedure_run_id="procedure-1",
        lease_token=_FENCE,
        expected_run_revision=2,
        status="succeeded",
    )

    assert assert_model_round_trip(close).status == "succeeded"
    assert ProcedureCloseReceipt(run=_run("closed")).run.closure is not None
    with pytest.raises(ValidationError, match="requires a reason"):
        ProcedureCloseCommand(
            procedure_run_id="procedure-1",
            lease_token=_FENCE,
            expected_run_revision=2,
            status="failed",
        )
