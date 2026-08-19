from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from pydantic import JsonValue, ValidationError
from scopecat_testkit.records import assert_model_round_trip

from scopecat.automation import (
    AnalysisPublicationOutputRef,
    ConfigActivationOutputRef,
    ConfigPublishOutputRef,
    ProcedureClosure,
    ProcedureDefinitionRef,
    ProcedureRun,
    ProcedureStepAttempt,
    ProcedureStepOperation,
    ProcedureStepOutputRef,
    RunOutputRef,
    procedure_intent_hash,
)
from scopecat.records.analysis import ProjectAnalysisSubject

_HASH = "sha256:" + "1" * 64
_OTHER_HASH = "sha256:" + "2" * 64
_START = datetime(2026, 8, 18, tzinfo=UTC)
_END = _START + timedelta(seconds=1)
_INTENT: dict[str, JsonValue] = {"target_ids": ["q0"]}


def _definition() -> ProcedureDefinitionRef:
    return ProcedureDefinitionRef(
        id="drag-calibration",
        version="1",
        fingerprint=_HASH,
    )


def test_procedure_run_round_trips_versioned_definition() -> None:
    run = ProcedureRun(
        procedure_run_id="procedure-1",
        request_key="drag-q0",
        definition=_definition(),
        intent=_INTENT,
        intent_hash=procedure_intent_hash(_definition(), _INTENT),
        revision=1,
        state="ready",
        created_at=_START,
        updated_at=_END,
    )

    restored = assert_model_round_trip(run)

    assert restored == run
    assert restored.definition.version == "1"


def test_procedure_run_rejects_waiting_and_requires_terminal_details() -> None:
    common = {
        "procedure_run_id": "procedure-1",
        "request_key": "drag-q0",
        "definition": _definition(),
        "intent": _INTENT,
        "intent_hash": procedure_intent_hash(_definition(), _INTENT),
        "revision": 1,
    }

    with pytest.raises(ValidationError, match="Input should be"):
        ProcedureRun.model_validate({**common, "state": "waiting"})
    with pytest.raises(ValidationError, match="requires a reason"):
        ProcedureRun.model_validate({**common, "state": "attention_required"})
    with pytest.raises(ValidationError, match="requires a closure"):
        ProcedureRun.model_validate({**common, "state": "closed"})


def test_closed_procedure_run_has_typed_terminal_result() -> None:
    run = ProcedureRun(
        procedure_run_id="procedure-1",
        request_key="drag-q0",
        definition=_definition(),
        intent=_INTENT,
        intent_hash=procedure_intent_hash(_definition(), _INTENT),
        revision=4,
        state="closed",
        created_at=_START,
        updated_at=_END,
        closure=ProcedureClosure(status="succeeded", closed_at=_END),
    )

    assert assert_model_round_trip(run) == run
    with pytest.raises(ValidationError, match="requires a reason"):
        ProcedureClosure(status="failed", closed_at=_END)


def test_procedure_run_rejects_intent_hash_not_covering_canonical_intent() -> None:
    with pytest.raises(ValidationError, match="must cover its definition"):
        ProcedureRun(
            procedure_run_id="procedure-1",
            request_key="drag-q0",
            definition=_definition(),
            intent=_INTENT,
            intent_hash=_OTHER_HASH,
            revision=1,
            state="ready",
        )


def test_procedure_intent_is_recursively_immutable_and_json_round_trips() -> None:
    intent: dict[str, JsonValue] = {
        "target": {"ids": ["q0"], "options": {"verify": True}}
    }
    run = ProcedureRun(
        procedure_run_id="procedure-1",
        request_key="drag-q0",
        definition=_definition(),
        intent=intent,
        intent_hash=procedure_intent_hash(_definition(), intent),
        revision=1,
        state="ready",
    )

    target = cast("dict[str, object]", run.intent["target"])
    ids = cast("list[object]", target["ids"])
    with pytest.raises(TypeError, match="immutable"):
        cast("dict[str, object]", run.intent)["new"] = True
    with pytest.raises(TypeError):
        target["new"] = True
    with pytest.raises(TypeError):
        ids[0] = "q1"

    assert assert_model_round_trip(run) == run
    assert run.intent_hash == procedure_intent_hash(run.definition, run.intent)


@pytest.mark.parametrize(
    "operation,output",
    [
        ("run", RunOutputRef(run_id="run-1")),
        (
            "analysis",
            AnalysisPublicationOutputRef(
                subject=ProjectAnalysisSubject(),
                analysis_record_id="analysis-verify-r1",
            ),
        ),
        (
            "config_activation",
            ConfigActivationOutputRef(
                generation=3,
                entry_id="config-3",
                entry_content_hash=_HASH,
            ),
        ),
        (
            "config_publish",
            ConfigPublishOutputRef(
                generation=4,
                entry_id="config-4",
                entry_content_hash=_HASH,
            ),
        ),
    ],
)
def test_successful_step_attempt_round_trips_typed_output(
    operation: ProcedureStepOperation,
    output: ProcedureStepOutputRef,
) -> None:
    attempt = ProcedureStepAttempt(
        procedure_run_id="procedure-1",
        step_key="verify",
        attempt=1,
        operation=operation,
        intent_hash=_OTHER_HASH,
        revision=2,
        state="succeeded",
        started_at=_START,
        updated_at=_END,
        finished_at=_END,
        output=output,
    )

    restored = assert_model_round_trip(attempt)

    assert restored == attempt
    assert type(restored.output) is type(output)


def test_step_attempt_rejects_output_from_another_operation() -> None:
    with pytest.raises(ValidationError, match="output kind must match"):
        ProcedureStepAttempt(
            procedure_run_id="procedure-1",
            step_key="baseline",
            attempt=1,
            operation="run",
            intent_hash=_OTHER_HASH,
            revision=1,
            state="succeeded",
            started_at=_START,
            updated_at=_END,
            finished_at=_END,
            output=AnalysisPublicationOutputRef(
                subject=ProjectAnalysisSubject(),
                analysis_record_id="analysis-fit-r1",
            ),
        )


def test_step_attempt_records_unique_exact_upstream_outputs() -> None:
    upstream = RunOutputRef(run_id="run-baseline")
    with pytest.raises(ValidationError, match="input references must be unique"):
        ProcedureStepAttempt(
            procedure_run_id="procedure-1",
            step_key="fit",
            attempt=1,
            operation="analysis",
            intent_hash=_OTHER_HASH,
            inputs=(upstream, upstream),
            revision=1,
            state="running",
            started_at=_START,
            updated_at=_START,
        )


def test_step_attempt_enforces_terminal_and_attention_details() -> None:
    common = {
        "procedure_run_id": "procedure-1",
        "step_key": "baseline",
        "attempt": 1,
        "operation": "run",
        "intent_hash": _OTHER_HASH,
        "revision": 1,
        "started_at": _START,
        "updated_at": _END,
    }

    with pytest.raises(ValidationError, match="requires output and finish time"):
        ProcedureStepAttempt.model_validate({**common, "state": "succeeded"})
    with pytest.raises(
        ValidationError,
        match="failed procedure step requires a reason",
    ):
        ProcedureStepAttempt.model_validate(
            {**common, "state": "failed", "finished_at": _END}
        )
    with pytest.raises(
        ValidationError,
        match=r"attention-required.*requires a reason",
    ):
        ProcedureStepAttempt.model_validate({**common, "state": "attention_required"})


def test_procedure_models_are_immutable_and_hashes_are_explicit() -> None:
    definition = _definition()

    with pytest.raises(ValidationError, match="frozen"):
        definition.version = "2"
    with pytest.raises(ValidationError):
        ProcedureDefinitionRef(
            id="drag-calibration",
            version="1",
            fingerprint="not-a-content-hash",
        )
