from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import httpx2
import pytest
from pydantic import ValidationError
from scopecat_testkit.workflow_fixtures import load_config, load_invocation

import scopecat.api.procedures as procedures_module
from scopecat.api._config import LabConfigOperations
from scopecat.api._runner import _DaemonRunner
from scopecat.api.analysis import Analysis, AnalysisContext, AnalysisStep
from scopecat.api.procedures import (
    LabProcedureContext,
    ProcedureLabSession,
    _validate_run_analysis,
)
from scopecat.api.published_analysis import PublishedAnalysis
from scopecat.api.run import RunHandle
from scopecat.automation import (
    ConfigActivationOutputRef,
    ProcedureContext,
    ProcedureStepOperation,
    ProcedureStepOutputRef,
    RunOutputRef,
)
from scopecat.automation.worker import ProcedureNeedsAttention
from scopecat.config.candidates import CandidateConfig
from scopecat.config.registry import (
    ConfigActivationOperation,
    ConfigRegistryActivationRecord,
    config_activation_intent_hash,
)
from scopecat.daemon.client import (
    DaemonConflictError,
    DaemonNotFoundError,
    DaemonUnavailableError,
)
from scopecat.daemon.views import RunAnalysisView
from scopecat.daemon.wire import ConfigActivationReceipt
from scopecat.records.analysis import (
    AnalysisRecord,
    MeasurementAnalysisRecordInput,
    RunAnalysisSubject,
    analysis_record_id,
)
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.content import ContentEntry, Sha256ContentHash
from scopecat.records.run import RunConfigSource, RunSnapshot
from scopecat.runs.selectors import RunSelector


class _ImmediateProcedureContext:
    procedure_run_id = "procedure-test"

    def step(
        self,
        step_key: str,
        *,
        operation: ProcedureStepOperation,
        intent_hash: Sha256ContentHash,
        effect: Callable[[str], ProcedureStepOutputRef],
        inputs: tuple[ProcedureStepOutputRef, ...] = (),
    ) -> ProcedureStepOutputRef:
        del step_key, operation, intent_hash, inputs
        return effect("operation-test")


@dataclass(frozen=True, slots=True)
class _StepCall:
    step_key: str
    operation: ProcedureStepOperation
    intent_hash: Sha256ContentHash
    inputs: tuple[ProcedureStepOutputRef, ...]


class _RecordingProcedureContext:
    procedure_run_id = "procedure-test"

    def __init__(self) -> None:
        self.calls: list[_StepCall] = []

    def step(
        self,
        step_key: str,
        *,
        operation: ProcedureStepOperation,
        intent_hash: Sha256ContentHash,
        effect: Callable[[str], ProcedureStepOutputRef],
        inputs: tuple[ProcedureStepOutputRef, ...] = (),
    ) -> ProcedureStepOutputRef:
        self.calls.append(
            _StepCall(
                step_key=step_key,
                operation=operation,
                intent_hash=intent_hash,
                inputs=inputs,
            )
        )
        return effect("operation-test")


class _ExistingStepProcedureContext:
    procedure_run_id = "procedure-test"

    def __init__(self, existing: _StepCall) -> None:
        self.existing = existing

    def step(
        self,
        step_key: str,
        *,
        operation: ProcedureStepOperation,
        intent_hash: Sha256ContentHash,
        effect: Callable[[str], ProcedureStepOutputRef],
        inputs: tuple[ProcedureStepOutputRef, ...] = (),
    ) -> ProcedureStepOutputRef:
        del effect
        requested = _StepCall(step_key, operation, intent_hash, inputs)
        if requested != self.existing:
            raise RuntimeError("procedure step key already has different intent")
        raise AssertionError("test requires a changed step identity")


class _ActivationConfig:
    operator = "lab-operator"

    def __init__(
        self,
        receipt: ConfigActivationReceipt,
        *,
        lookup_receipt: ConfigActivationReceipt | None = None,
        activate_error: Exception | None = None,
        lookup_error: Exception | None = None,
    ) -> None:
        self.receipt = receipt
        self.lookup_receipt = lookup_receipt
        self.activate_error = activate_error
        self.lookup_error = lookup_error
        self.activate_calls: list[tuple[str, str, int, str | None, str]] = []
        self.lookup_calls: list[str] = []

    def activate_entry(
        self,
        entry_id: str,
        *,
        operation_id: str,
        expected_generation: int,
        actor: str | None = None,
        note: str = "",
    ) -> ConfigActivationReceipt:
        self.activate_calls.append(
            (entry_id, operation_id, expected_generation, actor, note)
        )
        if self.activate_error is not None:
            raise self.activate_error
        return self.receipt

    def activation_operation(self, operation_id: str) -> ConfigActivationReceipt:
        self.lookup_calls.append(operation_id)
        if self.lookup_error is not None:
            raise self.lookup_error
        return self.lookup_receipt or self.receipt


@dataclass(frozen=True, slots=True)
class _DirectConfig:
    def resolve_with_source(
        self,
        config: ConfigProfileSnapshot | CandidateConfig,
    ) -> tuple[ConfigProfileSnapshot, RunConfigSource | None]:
        if isinstance(config, CandidateConfig):
            raise AssertionError("test expects a direct config snapshot")
        return config, None


@dataclass(frozen=True, slots=True)
class _TransportFailingRunner:
    planned: object

    def _plan(self, _experiment: object, **_kwargs: object) -> object:
        return self.planned

    def execute(
        self,
        _planned: object,
        *,
        executor_id: str = "notebook",
        submission_id: str | None = None,
    ) -> RunSnapshot:
        del executor_id, submission_id
        raise httpx2.ReadError("child run response was lost")


def _stub_prepare_run_submission(
    _planned: object,
    *,
    submission_id: str,
) -> tuple[object, str]:
    del submission_id
    return object(), "sha256:" + "a" * 64


@dataclass(frozen=True, slots=True)
class _TestAnalysisStep:
    id: str = "test-analysis"

    def run(self, context: AnalysisContext) -> Analysis:
        del context
        raise AssertionError("analysis execution is outside this transport test")


class _UnknownProjectAnalysisSession:
    def get_run(self, run: RunSelector | RunHandle) -> RunHandle:
        del run
        raise AssertionError("run lookup is outside this project-analysis test")

    def analyze(
        self,
        step: AnalysisStep,
        *,
        key: str | None = None,
    ) -> PublishedAnalysis:
        del step, key
        raise httpx2.ReadError("analysis response was lost")

    def published_analysis(self, selector: str) -> PublishedAnalysis:
        del selector
        response = httpx2.Response(
            404,
            request=httpx2.Request("GET", "http://daemon.local/analysis"),
        )
        raise DaemonNotFoundError("analysis does not exist", response=response)


def test_child_run_transport_error_requires_procedure_attention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config()
    monkeypatch.setattr(
        procedures_module,
        "_prepare_run_submission",
        _stub_prepare_run_submission,
    )
    context = LabProcedureContext(
        cast("ProcedureContext", cast("object", _ImmediateProcedureContext())),
        runner=cast(
            "_DaemonRunner",
            cast("object", _TransportFailingRunner(object())),
        ),
        config=cast("LabConfigOperations", cast("object", _DirectConfig())),
        session=cast("ProcedureLabSession", object()),
    )

    with pytest.raises(ProcedureNeedsAttention, match="transport outcome"):
        context.run("child", load_invocation(), config=config)


def test_analysis_transport_with_no_confirmed_r1_requires_attention() -> None:
    context = LabProcedureContext(
        cast("ProcedureContext", cast("object", _ImmediateProcedureContext())),
        runner=cast("_DaemonRunner", object()),
        config=cast("LabConfigOperations", object()),
        session=_UnknownProjectAnalysisSession(),
    )

    with pytest.raises(ProcedureNeedsAttention, match="unknown outcome"):
        context.analyze_project(
            "fit",
            _TestAnalysisStep(),
            inputs=(),
        )


def test_run_analysis_rejects_durable_upstream_mismatch() -> None:
    run_id = "run-subject"
    step_id = "fit-step"
    key = "procedure-fit-key"
    record_id = analysis_record_id(key, 1)
    published = PublishedAnalysis(
        source=object(),  # pyright: ignore[reportArgumentType]
        view=RunAnalysisView(
            run_id=run_id,
            entry=ContentEntry(
                role="record",
                id=record_id,
                kind="analysis",
                content_hash="sha256:analysis-record",
            ),
            analysis=AnalysisRecord(
                subject=RunAnalysisSubject(run_id=run_id),
                title="Fit",
                key=key,
                revision=1,
                publication_hash="sha256:publication",
                step_id=step_id,
                inputs=[
                    MeasurementAnalysisRecordInput(
                        id="measurement-input",
                        target="measurement-dataset",
                        content_hash="sha256:measurements",
                        codec="scopecat.measurement-dataset.v1",
                        role="dataset",
                        run_id=run_id,
                    )
                ],
                outputs=[],
            ),
            published_at=datetime(2026, 8, 18, tzinfo=UTC),
        ),
    )

    with pytest.raises(ValueError, match="upstreams"):
        _validate_run_analysis(
            published,
            run_id=run_id,
            step_id=step_id,
            key=key,
            inputs=(
                RunOutputRef(run_id=run_id),
                RunOutputRef(run_id="run-unpublished-upstream"),
            ),
        )


def test_config_activation_uses_exact_step_intent_and_operation_id() -> None:
    entry_id = "candidate-entry"
    expected_generation = 4
    note = "activate a reviewed entry"
    receipt = _activation_receipt(
        operation_id="operation-test",
        entry_id=entry_id,
        expected_generation=expected_generation,
        actor="lab-operator",
        note=note,
    )
    durable = _RecordingProcedureContext()
    config = _ActivationConfig(receipt)
    context = _activation_context(durable, config)
    verification = RunOutputRef(run_id="verification-run")

    output = context.activate_config_entry(
        "activate",
        entry_id,
        expected_generation=expected_generation,
        actor="lab-operator",
        note=note,
        inputs=(verification,),
    )

    assert output == ConfigActivationOutputRef(
        generation=receipt.activation.generation,
        entry_id=entry_id,
        entry_content_hash=receipt.activation.entry_content_hash,
    )
    assert durable.calls == [
        _StepCall(
            step_key="activate",
            operation="config_activation",
            intent_hash=config_activation_intent_hash(
                entry_id=entry_id,
                expected_generation=expected_generation,
                actor="lab-operator",
                note=note,
            ),
            inputs=(verification,),
        )
    ]
    assert config.activate_calls == [
        (
            entry_id,
            "operation-test",
            expected_generation,
            "lab-operator",
            note,
        )
    ]
    assert config.lookup_calls == []


def test_config_activation_recovers_transport_loss_by_exact_operation() -> None:
    receipt = _activation_receipt(
        operation_id="operation-test",
        entry_id="candidate-entry",
        expected_generation=2,
        actor="automation",
    )
    config = _ActivationConfig(
        receipt,
        activate_error=httpx2.ReadError("activation response was lost"),
    )
    context = _activation_context(_RecordingProcedureContext(), config)

    output = context.activate_config_entry(
        "activate",
        "candidate-entry",
        expected_generation=2,
        actor="automation",
    )

    assert output.generation == receipt.activation.generation
    assert config.lookup_calls == ["operation-test"]


@pytest.mark.parametrize(
    "failure",
    ["unavailable", "http-500", "invalid-receipt"],
)
def test_config_activation_recovers_ambiguous_post_failure(
    failure: str,
) -> None:
    receipt = _activation_receipt(
        operation_id="operation-test",
        entry_id="candidate-entry",
        expected_generation=2,
        actor="automation",
    )
    config = _ActivationConfig(
        receipt,
        activate_error=_ambiguous_activation_error(failure, method="POST"),
    )
    context = _activation_context(_RecordingProcedureContext(), config)

    output = context.activate_config_entry(
        "activate",
        "candidate-entry",
        expected_generation=2,
        actor="automation",
    )

    assert output.generation == receipt.activation.generation
    assert config.lookup_calls == ["operation-test"]


def test_config_activation_unknown_after_exact_lookup_requires_attention() -> None:
    receipt = _activation_receipt(
        operation_id="operation-test",
        entry_id="candidate-entry",
        expected_generation=2,
        actor="automation",
    )
    response = httpx2.Response(
        404,
        request=httpx2.Request(
            "GET",
            "http://daemon.local/config-registry/activation-operations/operation-test",
        ),
    )
    config = _ActivationConfig(
        receipt,
        activate_error=httpx2.ReadError("activation response was lost"),
        lookup_error=DaemonNotFoundError(
            "activation operation does not exist",
            response=response,
        ),
    )
    context = _activation_context(_RecordingProcedureContext(), config)

    with pytest.raises(ProcedureNeedsAttention, match=r"outcome.*unknown"):
        context.activate_config_entry(
            "activate",
            "candidate-entry",
            expected_generation=2,
            actor="automation",
        )


def test_config_activation_failed_exact_lookup_requires_attention() -> None:
    receipt = _activation_receipt(
        operation_id="operation-test",
        entry_id="candidate-entry",
        expected_generation=2,
        actor="automation",
    )
    config = _ActivationConfig(
        receipt,
        activate_error=httpx2.ReadError("activation response was lost"),
        lookup_error=httpx2.ReadError("activation lookup response was lost"),
    )
    context = _activation_context(_RecordingProcedureContext(), config)

    with pytest.raises(ProcedureNeedsAttention, match=r"outcome.*unknown"):
        context.activate_config_entry(
            "activate",
            "candidate-entry",
            expected_generation=2,
            actor="automation",
        )


@pytest.mark.parametrize("failure", ["unavailable", "http-500", "invalid-receipt"])
def test_config_activation_ambiguous_exact_lookup_requires_attention(
    failure: str,
) -> None:
    receipt = _activation_receipt(
        operation_id="operation-test",
        entry_id="candidate-entry",
        expected_generation=2,
        actor="automation",
    )
    config = _ActivationConfig(
        receipt,
        activate_error=httpx2.ReadError("activation response was lost"),
        lookup_error=_ambiguous_activation_error(failure, method="GET"),
    )
    context = _activation_context(_RecordingProcedureContext(), config)

    with pytest.raises(ProcedureNeedsAttention, match=r"outcome.*unknown"):
        context.activate_config_entry(
            "activate",
            "candidate-entry",
            expected_generation=2,
            actor="automation",
        )


def test_config_activation_known_conflict_does_not_enter_recovery() -> None:
    receipt = _activation_receipt(
        operation_id="operation-test",
        entry_id="candidate-entry",
        expected_generation=2,
        actor="automation",
    )
    response = httpx2.Response(
        409,
        request=httpx2.Request(
            "POST",
            "http://daemon.local/config-registry/activation-operations",
        ),
    )
    conflict = DaemonConflictError("stale generation", response=response)
    config = _ActivationConfig(receipt, activate_error=conflict)
    context = _activation_context(_RecordingProcedureContext(), config)

    with pytest.raises(DaemonConflictError, match="stale generation"):
        context.activate_config_entry(
            "activate",
            "candidate-entry",
            expected_generation=2,
            actor="automation",
        )

    assert config.lookup_calls == []


def test_config_activation_recovers_a_mismatched_post_receipt_by_exact_lookup() -> None:
    mismatched = _activation_receipt(
        operation_id="different-operation",
        entry_id="candidate-entry",
        expected_generation=2,
        actor="automation",
    )
    exact = _activation_receipt(
        operation_id="operation-test",
        entry_id="candidate-entry",
        expected_generation=2,
        actor="automation",
    )
    config = _ActivationConfig(mismatched, lookup_receipt=exact)
    context = _activation_context(_RecordingProcedureContext(), config)

    output = context.activate_config_entry(
        "activate",
        "candidate-entry",
        expected_generation=2,
        actor="automation",
    )

    assert output.generation == exact.activation.generation
    assert config.lookup_calls == ["operation-test"]


def test_config_activation_rejects_a_mismatched_exact_receipt() -> None:
    receipt = _activation_receipt(
        operation_id="different-operation",
        entry_id="candidate-entry",
        expected_generation=2,
        actor="automation",
    )
    config = _ActivationConfig(receipt)
    context = _activation_context(_RecordingProcedureContext(), config)

    with pytest.raises(ProcedureNeedsAttention, match=r"outcome.*unknown"):
        context.activate_config_entry(
            "activate",
            "candidate-entry",
            expected_generation=2,
            actor="automation",
        )

    assert config.lookup_calls == ["operation-test"]


@pytest.mark.parametrize("changed", ["intent", "inputs"])
def test_config_activation_step_conflict_does_not_execute_effect(
    changed: str,
) -> None:
    existing_input = RunOutputRef(run_id="verification-1")
    requested_input = (
        RunOutputRef(run_id="verification-2") if changed == "inputs" else existing_input
    )
    existing_generation = 2
    requested_generation = 3 if changed == "intent" else existing_generation
    durable = _ExistingStepProcedureContext(
        _StepCall(
            step_key="activate",
            operation="config_activation",
            intent_hash=config_activation_intent_hash(
                entry_id="candidate-entry",
                expected_generation=existing_generation,
                actor="automation",
            ),
            inputs=(existing_input,),
        )
    )
    receipt = _activation_receipt(
        operation_id="operation-test",
        entry_id="candidate-entry",
        expected_generation=requested_generation,
        actor="automation",
    )
    config = _ActivationConfig(receipt)
    context = _activation_context(durable, config)

    with pytest.raises(RuntimeError, match="different intent"):
        context.activate_config_entry(
            "activate",
            "candidate-entry",
            expected_generation=requested_generation,
            actor="automation",
            inputs=(requested_input,),
        )

    assert config.activate_calls == []


def _activation_context(
    durable: _RecordingProcedureContext | _ExistingStepProcedureContext,
    config: _ActivationConfig,
) -> LabProcedureContext:
    return LabProcedureContext(
        cast("ProcedureContext", cast("object", durable)),
        runner=cast("_DaemonRunner", object()),
        config=cast("LabConfigOperations", cast("object", config)),
        session=cast("ProcedureLabSession", object()),
    )


def _activation_receipt(
    *,
    operation_id: str,
    entry_id: str,
    expected_generation: int,
    actor: str,
    note: str = "",
) -> ConfigActivationReceipt:
    activation = ConfigRegistryActivationRecord(
        generation=expected_generation + 1,
        action="activation",
        entry_id=entry_id,
        entry_content_hash=config_content_hash(load_config()),
        actor=actor,
        note=note,
    )
    return ConfigActivationReceipt(
        operation=ConfigActivationOperation(
            operation_id=operation_id,
            intent_hash=config_activation_intent_hash(
                entry_id=entry_id,
                expected_generation=expected_generation,
                actor=actor,
                note=note,
            ),
            entry_id=entry_id,
            expected_generation=expected_generation,
            actor=actor,
            note=note,
            activation_generation=activation.generation,
        ),
        activation=activation,
    )


def _ambiguous_activation_error(failure: str, *, method: str) -> Exception:
    request = httpx2.Request(
        method,
        "http://daemon.local/config-registry/activation-operations/operation-test",
    )
    if failure == "unavailable":
        return DaemonUnavailableError(
            "daemon unavailable",
            response=httpx2.Response(503, request=request),
        )
    if failure == "http-500":
        response = httpx2.Response(500, request=request)
        return httpx2.HTTPStatusError(
            "internal server error",
            request=request,
            response=response,
        )
    if failure == "invalid-receipt":
        try:
            ConfigActivationReceipt.model_validate({})
        except ValidationError as error:
            return error
    raise AssertionError(f"unsupported activation failure fixture: {failure}")
