from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import cast, override

import pytest
from scopecat_testkit.instrument_host import TestRunInstrumentHost

from scopecat.execution.effect_interpreter import (
    RunEffectInterpreter,
    _CancellationAwareDomainInstruments,
)
from scopecat.execution.effects.domain import (
    DomainResidencyCache,
    _PreparedDomainJobRuntime,
    execute_domain_job_values,
)
from scopecat.execution.program import RunDomainJob
from scopecat.kernel.errors import DomainExecutionFailed, OperationFailure
from scopecat.kernel.point_identity import LogicalPointId, PointDomainId
from scopecat.kernel.points import AcceptedRunPoint
from scopecat.kernel.problems import ProblemPhase, problem
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.sdk.domain.execution import (
    DomainResidencyAddress,
    DomainResidencyRequirement,
    DomainStateAddress,
    DomainStateRequirement,
    DomainTransitionDurability,
    ErasedDomainInvocation,
    ErasedDomainJobRuntime,
    ErasedDomainRealizer,
    ErasedDomainSetup,
    PreparedDomainExecution,
)
from scopecat.sdk.domain.invocation import (
    DomainInvocationIntent,
    close_domain_invocation,
)
from scopecat.sdk.domain.result_mapping import DomainResultMapping
from scopecat.sdk.domain.runtime import (
    DomainExecutionCancellationRequested,
    DomainExecutionId,
    DomainExecutionReceipt,
    DomainExecutionResult,
    DomainJobCheckpoint,
)
from scopecat.sdk.instruments.execution import (
    RunHardwareBatch,
    RunHardwareBatchReceipt,
    RunHardwareInvoke,
    RunInstrumentHost,
)


def _failure():
    return problem(
        "injected_setup_failure",
        "the injected setup operation was rejected",
        phase=ProblemPhase.EXECUTION,
    )


@dataclass
class _Setup:
    failure: OperationFailure | None = None
    calls: int = 0

    def prepare(
        self,
        execution_key: str,
        payload: object,
        *,
        instruments: object,
    ) -> None:
        del execution_key, payload, instruments
        self.calls += 1
        if self.failure is not None:
            raise self.failure


@dataclass
class _Realtime:
    calls: int = 0

    def start(
        self,
        execution_key: str,
        payload: object,
        *,
        instruments: object,
    ) -> DomainExecutionReceipt:
        del execution_key, payload, instruments
        self.calls += 1
        raise AssertionError("realtime execution must not start after setup failure")


@dataclass
class _CompletingRealtime:
    calls: int = 0

    def start(
        self,
        execution_key: str,
        payload: object,
        *,
        instruments: object,
    ) -> DomainExecutionResult[object]:
        del payload, instruments
        self.calls += 1
        return DomainExecutionResult(
            DomainExecutionReceipt(
                execution_key=execution_key,
                status="completed",
                result_fingerprint=f"result-{self.calls}",
                result_count=0,
            ),
            object(),
        )


@dataclass
class _Executor:
    receipt: RunHardwareBatchReceipt
    batches: list[RunHardwareBatch] = field(default_factory=list)

    def execute(self, batch: RunHardwareBatch) -> RunHardwareBatchReceipt:
        self.batches.append(batch)
        return self.receipt


def _prepared(
    *,
    setup: _Setup,
    realtime: _Realtime | _CompletingRealtime,
    requirements: tuple[DomainStateRequirement, ...] = (),
    residency: tuple[DomainResidencyRequirement, ...] = (),
    setup_residency_invalidations: tuple[DomainResidencyAddress, ...] = (),
    realtime_residency_invalidations: tuple[DomainResidencyAddress, ...] = (),
) -> PreparedDomainExecution:
    def realize_into(
        _result: DomainExecutionResult[object],
        _accept: object,
    ) -> None:
        return None

    return PreparedDomainExecution(
        instrument_ids=("awg",),
        setup_write_footprint=(),
        setup_state_invalidations=(),
        state_requirements=requirements,
        realtime_write_footprint=(),
        realtime_state_invalidations=(),
        next_batch_max_points=1,
        invocation=cast("ErasedDomainInvocation", object()),
        setup=cast("ErasedDomainSetup", setup),
        job_runtime=cast("ErasedDomainJobRuntime", realtime),
        realize_into=cast("ErasedDomainRealizer", realize_into),
        setup_residency_requirements=residency,
        setup_residency_invalidations=setup_residency_invalidations,
        realtime_residency_invalidations=realtime_residency_invalidations,
    )


def _requirement(*, instrument_id: str = "awg") -> DomainStateRequirement:
    return DomainStateRequirement(
        address=DomainStateAddress(
            instrument_id=instrument_id,
            interface_id="test.output/v1",
            component_path=("outputs", "ch1"),
            property_id="offset",
        ),
        value=StateValue(Quantity(0.0, "V")),
    )


def _residency(
    fingerprint: str,
    *,
    instrument_id: str = "awg",
    slot_id: str = "program",
) -> DomainResidencyRequirement:
    return DomainResidencyRequirement(
        address=DomainResidencyAddress(
            instrument_id=instrument_id,
            slot_id=slot_id,
        ),
        content_fingerprint=fingerprint,
    )


def test_matching_residency_skips_repeated_setup() -> None:
    setup = _Setup()
    realtime = _CompletingRealtime()
    cache = DomainResidencyCache()
    prepared = _prepared(
        setup=setup,
        realtime=realtime,
        residency=(_residency("program-a"),),
    )
    runtime = _PreparedDomainJobRuntime(prepared, cache)
    instruments = _Executor(RunHardwareBatchReceipt(operation_id="unused"))

    first = runtime.start("first", object(), instruments=instruments)
    second = runtime.start("second", object(), instruments=instruments)

    assert isinstance(first, DomainExecutionResult)
    assert isinstance(second, DomainExecutionResult)
    assert setup.calls == 1
    assert realtime.calls == 2
    assert cache.contents == {DomainResidencyAddress("awg", "program"): "program-a"}


def test_changed_or_invalidated_residency_runs_setup_again() -> None:
    setup = _Setup()
    realtime = _CompletingRealtime()
    cache = DomainResidencyCache()
    instruments = _Executor(RunHardwareBatchReceipt(operation_id="unused"))

    _ = _PreparedDomainJobRuntime(
        _prepared(
            setup=setup,
            realtime=realtime,
            residency=(_residency("program-a"),),
        ),
        cache,
    ).start("first", object(), instruments=instruments)
    _ = _PreparedDomainJobRuntime(
        _prepared(
            setup=setup,
            realtime=realtime,
            residency=(_residency("program-b"),),
        ),
        cache,
    ).start("second", object(), instruments=instruments)
    cache.invalidate_instruments({"lo"})
    _ = _PreparedDomainJobRuntime(
        _prepared(
            setup=setup,
            realtime=realtime,
            residency=(_residency("program-b"),),
        ),
        cache,
    ).start("third", object(), instruments=instruments)
    cache.invalidate_instruments({"awg"})
    _ = _PreparedDomainJobRuntime(
        _prepared(
            setup=setup,
            realtime=realtime,
            residency=(_residency("program-b"),),
        ),
        cache,
    ).start("fourth", object(), instruments=instruments)

    assert setup.calls == 3
    assert realtime.calls == 4


def test_realtime_residency_invalidation_withdraws_setup_knowledge() -> None:
    setup = _Setup()
    realtime = _CompletingRealtime()
    cache = DomainResidencyCache()
    residency = _residency("program-a")
    prepared = _prepared(
        setup=setup,
        realtime=realtime,
        residency=(residency,),
        realtime_residency_invalidations=(residency.address,),
    )
    runtime = _PreparedDomainJobRuntime(prepared, cache)
    instruments = _Executor(RunHardwareBatchReceipt(operation_id="unused"))

    _ = runtime.start("first", object(), instruments=instruments)
    _ = runtime.start("second", object(), instruments=instruments)

    assert setup.calls == 2
    assert realtime.calls == 2
    assert cache.contents == {}


def test_external_host_requirement_preserves_target_residency() -> None:
    setup = _Setup()
    realtime = _CompletingRealtime()
    residency = _residency("program-a")
    cache = DomainResidencyCache(
        contents={residency.address: residency.content_fingerprint}
    )
    runtime = _PreparedDomainJobRuntime(
        _prepared(
            setup=setup,
            realtime=realtime,
            requirements=(_requirement(instrument_id="lo-source"),),
            residency=(residency,),
        ),
        cache,
    )
    operation_id = "domain:execution-key:reconcile-requirements"

    result = runtime.start(
        "execution-key",
        object(),
        instruments=_Executor(RunHardwareBatchReceipt(operation_id=operation_id)),
    )

    assert isinstance(result, DomainExecutionResult)
    assert setup.calls == 0
    assert cache.contents == {residency.address: residency.content_fingerprint}


def test_transition_flush_failure_marks_run_indeterminate() -> None:
    class FailingWriter:
        def invocation(
            self,
            *,
            logical_compute_node_id: str,
            point_ordinals: tuple[int, ...],
            execution_id: DomainExecutionId,
            intent: DomainInvocationIntent,
            durability: DomainTransitionDurability,
        ) -> None:
            del (
                logical_compute_node_id,
                point_ordinals,
                execution_id,
                intent,
                durability,
            )
            raise AssertionError("empty run has no invocation")

        def checkpoint(
            self,
            *,
            logical_compute_node_id: str,
            point_ordinals: tuple[int, ...],
            checkpoint: DomainJobCheckpoint,
        ) -> None:
            del logical_compute_node_id, point_ordinals, checkpoint
            raise AssertionError("empty run has no checkpoint")

        def terminal(
            self,
            *,
            logical_compute_node_id: str,
            point_ordinals: tuple[int, ...],
            receipt: DomainExecutionReceipt,
            durability: DomainTransitionDurability,
        ) -> None:
            del logical_compute_node_id, point_ordinals, receipt, durability
            raise AssertionError("empty run has no terminal")

        def flush(self) -> None:
            raise RuntimeError("transition storage unavailable")

    result = RunEffectInterpreter(
        run_id="transition-flush-run",
        coordinate_ids=(),
        instruments=TestRunInstrumentHost(),
        domain_job_transitions=FailingWriter(),
    ).run((), points=())

    assert result.indeterminate
    assert [item.code for item in result.problems] == [
        "domain_job_transition_flush_unknown"
    ]


def test_known_setup_rejection_returns_not_executed() -> None:
    setup = _Setup(OperationFailure((_failure(),)))
    realtime = _Realtime()
    runtime = _PreparedDomainJobRuntime(_prepared(setup=setup, realtime=realtime))

    receipt = runtime.start(
        "execution-key",
        object(),
        instruments=_Executor(RunHardwareBatchReceipt(operation_id="unused")),
    )

    assert isinstance(receipt, DomainExecutionReceipt)
    assert receipt.status == "not_executed"
    assert receipt.problems == (_failure(),)
    assert setup.calls == 1
    assert realtime.calls == 0


def test_attempt_is_observed_before_result_realization_or_failure() -> None:
    transition_events: list[tuple[str, int]] = []
    committed_intents: list[DomainInvocationIntent] = []
    committed_checkpoints: list[DomainJobCheckpoint] = []

    @dataclass(frozen=True, slots=True)
    class ResultContract:
        contract_fingerprint: str = "test-result-contract"

    class Runtime:
        def start(
            self,
            execution_key: str,
            payload: object,
            *,
            instruments: object,
        ) -> DomainExecutionResult[object]:
            del payload, instruments
            return DomainExecutionResult(
                DomainExecutionReceipt(
                    execution_key=execution_key,
                    status="completed",
                    result_fingerprint="result-fingerprint",
                    result_count=1,
                    execution_evidence={"selected_channel": "a"},
                ),
                object(),
            )

    class NegativeRuntime:
        def start(
            self,
            execution_key: str,
            payload: object,
            *,
            instruments: object,
        ) -> DomainExecutionReceipt:
            del payload, instruments
            return DomainExecutionReceipt(
                execution_key=execution_key,
                status="unknown",
                execution_evidence={"completed_entries": ["entry-0"]},
                problems=(_failure(),),
            )

    class CheckpointThenNegativeRuntime:
        def start(
            self,
            execution_key: str,
            payload: object,
            *,
            instruments: object,
        ) -> DomainJobCheckpoint:
            del payload, instruments
            transition_events.append(("start", 0))
            return DomainJobCheckpoint(
                execution_key=execution_key,
                job_id="provider-job",
                revision=1,
                resume_token={"provider_job_id": "provider-job"},
                progress={"status": "submitted"},
            )

        def resume(
            self,
            checkpoint: DomainJobCheckpoint,
            *,
            instruments: object,
        ) -> DomainJobCheckpoint | DomainExecutionReceipt:
            del instruments
            transition_events.append(("resume", checkpoint.revision))
            if checkpoint.revision == 1:
                return checkpoint.model_copy(
                    update={
                        "revision": 2,
                        "progress": {"status": "hardware_unknown"},
                    }
                )
            return DomainExecutionReceipt(
                execution_key=checkpoint.execution_key,
                status="unknown",
                problems=(_failure(),),
            )

    class CheckpointWriter:
        def invocation(
            self,
            *,
            logical_compute_node_id: str,
            point_ordinals: tuple[int, ...],
            execution_id: DomainExecutionId,
            intent: DomainInvocationIntent,
            durability: DomainTransitionDurability,
        ) -> None:
            assert logical_compute_node_id == "test-node"
            assert point_ordinals == (0,)
            assert execution_id.logical_compute_node_id == logical_compute_node_id
            assert execution_id.invocation_id == intent.invocation_id
            committed_intents.append(intent)
            assert durability == "write_ahead"
            transition_events.append(("invocation", 0))

        def checkpoint(
            self,
            *,
            logical_compute_node_id: str,
            point_ordinals: tuple[int, ...],
            checkpoint: DomainJobCheckpoint,
        ) -> None:
            assert logical_compute_node_id == "test-node"
            assert point_ordinals == (0,)
            committed_checkpoints.append(checkpoint)
            transition_events.append(("checkpoint", checkpoint.revision))

        def terminal(
            self,
            *,
            logical_compute_node_id: str,
            point_ordinals: tuple[int, ...],
            receipt: DomainExecutionReceipt,
            durability: DomainTransitionDurability,
        ) -> None:
            assert logical_compute_node_id == "test-node"
            assert point_ordinals == (0,)
            assert receipt.status == "unknown"
            assert durability == "write_ahead"
            transition_events.append(("terminal", 0))

        def flush(self) -> None:
            return None

    class RaisingRuntime:
        def start(
            self,
            execution_key: str,
            payload: object,
            *,
            instruments: object,
        ) -> DomainExecutionReceipt:
            del execution_key, payload, instruments
            raise RuntimeError("runtime lost its receipt")

    invocation = close_domain_invocation(
        cast(
            "DomainResultMapping[str]",
            cast("object", ResultContract()),
        ),
        invocation_id="test-invocation",
        target_id="test-target",
        compiler_id="test-compiler",
        capability_fingerprint="test-capability",
        artifact_id="test-artifact",
        artifact_fingerprint="test-artifact-fingerprint",
        execution_summary={},
        target_intent={},
        payload=object(),
    )

    def fail_realization(
        _result: DomainExecutionResult[object],
        _accept: object,
    ) -> None:
        raise RuntimeError("result realization failed")

    prepared = PreparedDomainExecution(
        instrument_ids=(),
        setup_write_footprint=(),
        setup_state_invalidations=(),
        state_requirements=(),
        realtime_write_footprint=(),
        realtime_state_invalidations=(),
        next_batch_max_points=1,
        invocation=cast("ErasedDomainInvocation", invocation),
        setup=None,
        job_runtime=cast("ErasedDomainJobRuntime", Runtime()),
        realize_into=cast("ErasedDomainRealizer", fail_realization),
    )
    observed: list[
        tuple[
            DomainExecutionId,
            tuple[DomainJobCheckpoint, ...],
            DomainExecutionReceipt | None,
        ]
    ] = []

    with pytest.raises(RuntimeError, match="result realization failed"):
        execute_domain_job_values(
            prepared,
            logical_compute_node_id="test-node",
            run_id="test-run",
            instruments=_Executor(RunHardwareBatchReceipt(operation_id="unused")),
            accept=lambda _candidate: None,
            observe_attempt=lambda execution_id, checkpoints, receipt: observed.append(
                (execution_id, checkpoints, receipt)
            ),
        )

    assert len(observed) == 1
    execution_id, checkpoints, receipt = observed[0]
    assert execution_id.logical_compute_node_id == "test-node"
    assert checkpoints == ()
    assert receipt is not None
    assert receipt.execution_evidence == {"selected_channel": "a"}

    negative_observed: list[
        tuple[
            DomainExecutionId,
            tuple[DomainJobCheckpoint, ...],
            DomainExecutionReceipt | None,
        ]
    ] = []
    with pytest.raises(DomainExecutionFailed):
        execute_domain_job_values(
            replace(
                prepared,
                job_runtime=cast("ErasedDomainJobRuntime", NegativeRuntime()),
            ),
            logical_compute_node_id="test-node",
            run_id="test-run",
            instruments=_Executor(RunHardwareBatchReceipt(operation_id="unused")),
            accept=lambda _candidate: None,
            observe_attempt=lambda execution_id, checkpoints, attempt_receipt: (
                negative_observed.append((execution_id, checkpoints, attempt_receipt))
            ),
        )
    [(_execution_id, negative_checkpoints, negative_receipt)] = negative_observed
    assert negative_checkpoints == ()
    assert negative_receipt is not None
    assert negative_receipt.status == "unknown"

    point = AcceptedRunPoint(
        LogicalPointId(PointDomainId("test-domain", "root"), 0),
        {},
    )
    effect_result = RunEffectInterpreter(
        run_id="test-run",
        coordinate_ids=(),
        instruments=TestRunInstrumentHost(),
        domain_job_transitions=CheckpointWriter(),
    ).run(
        (
            RunDomainJob(
                "test-node",
                (0,),
                replace(
                    prepared,
                    job_runtime=cast(
                        "ErasedDomainJobRuntime",
                        CheckpointThenNegativeRuntime(),
                    ),
                ),
            ),
        ),
        points=(point,),
    )
    evidence = effect_result.domain_execution
    assert evidence is not None
    assert evidence.attempt_count == 1
    assert evidence.checkpoint_count == 2
    assert evidence.receipt_count == 1
    assert evidence.unknown_count == 1
    assert evidence.target_ids == ("test-target",)
    assert committed_intents == [invocation.intent]
    assert [checkpoint.revision for checkpoint in committed_checkpoints] == [1, 2]
    assert [checkpoint.progress["status"] for checkpoint in committed_checkpoints] == [
        "submitted",
        "hardware_unknown",
    ]
    assert transition_events == [
        ("invocation", 0),
        ("start", 0),
        ("checkpoint", 1),
        ("resume", 1),
        ("checkpoint", 2),
        ("resume", 2),
        ("terminal", 0),
    ]

    transition_events.clear()
    invocation_failure_observed: list[
        tuple[
            DomainExecutionId,
            tuple[DomainJobCheckpoint, ...],
            DomainExecutionReceipt | None,
        ]
    ] = []

    def fail_invocation_commit(_execution_id: DomainExecutionId) -> None:
        raise RuntimeError("invocation storage unavailable")

    with pytest.raises(DomainExecutionFailed) as invocation_failure:
        execute_domain_job_values(
            replace(
                prepared,
                job_runtime=cast(
                    "ErasedDomainJobRuntime",
                    CheckpointThenNegativeRuntime(),
                ),
            ),
            logical_compute_node_id="test-node",
            run_id="test-run",
            instruments=_Executor(RunHardwareBatchReceipt(operation_id="unused")),
            accept=lambda _candidate: None,
            observe_attempt=lambda execution_id, checkpoints, attempt_receipt: (
                invocation_failure_observed.append(
                    (execution_id, checkpoints, attempt_receipt)
                )
            ),
            commit_invocation=fail_invocation_commit,
        )

    assert [item.code for item in invocation_failure.value.problems] == [
        "domain_job_invocation_commit_failed"
    ]
    assert invocation_failure.value.certainty == "known"
    assert transition_events == []
    [(_execution_id, invocation_checkpoints, invocation_receipt)] = (
        invocation_failure_observed
    )
    assert invocation_checkpoints == ()
    assert invocation_receipt is None

    transition_events.clear()
    commit_failure_observed: list[
        tuple[
            DomainExecutionId,
            tuple[DomainJobCheckpoint, ...],
            DomainExecutionReceipt | None,
        ]
    ] = []

    def fail_checkpoint_commit(
        _execution_id: DomainExecutionId,
        _checkpoint: DomainJobCheckpoint,
    ) -> None:
        raise RuntimeError("checkpoint storage unavailable")

    with pytest.raises(DomainExecutionFailed) as commit_failure:
        execute_domain_job_values(
            replace(
                prepared,
                job_runtime=cast(
                    "ErasedDomainJobRuntime",
                    CheckpointThenNegativeRuntime(),
                ),
            ),
            logical_compute_node_id="test-node",
            run_id="test-run",
            instruments=_Executor(RunHardwareBatchReceipt(operation_id="unused")),
            accept=lambda _candidate: None,
            observe_attempt=lambda execution_id, checkpoints, attempt_receipt: (
                commit_failure_observed.append(
                    (execution_id, checkpoints, attempt_receipt)
                )
            ),
            commit_checkpoint=fail_checkpoint_commit,
        )

    assert [item.code for item in commit_failure.value.problems] == [
        "domain_job_checkpoint_commit_failed"
    ]
    assert commit_failure.value.certainty == "indeterminate"
    assert transition_events == [("start", 0)]
    [(_execution_id, failed_checkpoints, failed_receipt)] = commit_failure_observed
    assert [checkpoint.revision for checkpoint in failed_checkpoints] == [1]
    assert failed_receipt is None

    terminal_failure_observed: list[
        tuple[
            DomainExecutionId,
            tuple[DomainJobCheckpoint, ...],
            DomainExecutionReceipt | None,
        ]
    ] = []

    def fail_terminal_commit(
        _execution_id: DomainExecutionId,
        _receipt: DomainExecutionReceipt,
    ) -> None:
        raise RuntimeError("terminal storage unavailable")

    with pytest.raises(DomainExecutionFailed) as terminal_failure:
        execute_domain_job_values(
            prepared,
            logical_compute_node_id="test-node",
            run_id="test-run",
            instruments=_Executor(RunHardwareBatchReceipt(operation_id="unused")),
            accept=lambda _candidate: None,
            observe_attempt=lambda execution_id, checkpoints, attempt_receipt: (
                terminal_failure_observed.append(
                    (execution_id, checkpoints, attempt_receipt)
                )
            ),
            commit_terminal=fail_terminal_commit,
        )

    assert [item.code for item in terminal_failure.value.problems] == [
        "domain_job_terminal_commit_failed"
    ]
    assert terminal_failure.value.certainty == "known"
    [(_execution_id, terminal_checkpoints, terminal_receipt)] = (
        terminal_failure_observed
    )
    assert terminal_checkpoints == ()
    assert terminal_receipt is not None
    assert terminal_receipt.status == "completed"

    transition_events.clear()
    invocation_cancellation_requested = False

    class CancellingInvocationWriter(CheckpointWriter):
        @override
        def invocation(
            self,
            *,
            logical_compute_node_id: str,
            point_ordinals: tuple[int, ...],
            execution_id: DomainExecutionId,
            intent: DomainInvocationIntent,
            durability: DomainTransitionDurability,
        ) -> None:
            nonlocal invocation_cancellation_requested
            super().invocation(
                logical_compute_node_id=logical_compute_node_id,
                point_ordinals=point_ordinals,
                execution_id=execution_id,
                intent=intent,
                durability=durability,
            )
            invocation_cancellation_requested = True

    invocation_cancelled = RunEffectInterpreter(
        run_id="test-run",
        coordinate_ids=(),
        instruments=TestRunInstrumentHost(),
        cancellation_requested=lambda: invocation_cancellation_requested,
        domain_job_transitions=CancellingInvocationWriter(),
    ).run(
        (
            RunDomainJob(
                "test-node",
                (0,),
                replace(
                    prepared,
                    job_runtime=cast(
                        "ErasedDomainJobRuntime",
                        CheckpointThenNegativeRuntime(),
                    ),
                ),
            ),
        ),
        points=(point,),
    )
    assert invocation_cancelled.cancelled
    assert transition_events == [("invocation", 0)]

    transition_events.clear()
    cancellation_requested = False

    class CancellingCheckpointWriter(CheckpointWriter):
        @override
        def checkpoint(
            self,
            *,
            logical_compute_node_id: str,
            point_ordinals: tuple[int, ...],
            checkpoint: DomainJobCheckpoint,
        ) -> None:
            nonlocal cancellation_requested
            super().checkpoint(
                logical_compute_node_id=logical_compute_node_id,
                point_ordinals=point_ordinals,
                checkpoint=checkpoint,
            )
            cancellation_requested = True

    cancelled_effect_result = RunEffectInterpreter(
        run_id="test-run",
        coordinate_ids=(),
        instruments=TestRunInstrumentHost(),
        cancellation_requested=lambda: cancellation_requested,
        domain_job_transitions=CancellingCheckpointWriter(),
    ).run(
        (
            RunDomainJob(
                "test-node",
                (0,),
                replace(
                    prepared,
                    job_runtime=cast(
                        "ErasedDomainJobRuntime",
                        CheckpointThenNegativeRuntime(),
                    ),
                ),
            ),
        ),
        points=(point,),
    )
    assert cancelled_effect_result.cancelled
    assert transition_events == [
        ("invocation", 0),
        ("start", 0),
        ("checkpoint", 1),
    ]
    cancelled_evidence = cancelled_effect_result.domain_execution
    assert cancelled_evidence is not None
    assert cancelled_evidence.attempt_count == 1
    assert cancelled_evidence.checkpoint_count == 1
    assert cancelled_evidence.receipt_count == 0

    missing_observed: list[
        tuple[
            DomainExecutionId,
            tuple[DomainJobCheckpoint, ...],
            DomainExecutionReceipt | None,
        ]
    ] = []
    with pytest.raises(DomainExecutionFailed):
        execute_domain_job_values(
            replace(
                prepared,
                job_runtime=cast("ErasedDomainJobRuntime", RaisingRuntime()),
            ),
            logical_compute_node_id="test-node",
            run_id="test-run",
            instruments=_Executor(RunHardwareBatchReceipt(operation_id="unused")),
            accept=lambda _candidate: None,
            observe_attempt=lambda execution_id, checkpoints, attempt_receipt: (
                missing_observed.append((execution_id, checkpoints, attempt_receipt))
            ),
        )
    [(_execution_id, missing_checkpoints, missing_receipt)] = missing_observed
    assert missing_checkpoints == ()
    assert missing_receipt is None


def test_dense_domain_sweep_keeps_terminal_evidence_bounded() -> None:
    @dataclass(frozen=True, slots=True)
    class ResultContract:
        contract_fingerprint: str = "test-result-contract"

    class Runtime:
        def start(
            self,
            execution_key: str,
            payload: object,
            *,
            instruments: object,
        ) -> DomainExecutionResult[object]:
            del payload, instruments
            return DomainExecutionResult(
                DomainExecutionReceipt(
                    execution_key=execution_key,
                    status="completed",
                    result_fingerprint="empty-result",
                    result_count=0,
                ),
                object(),
            )

    class CountingTransitionWriter:
        def __init__(self) -> None:
            self.invocation_count = 0
            self.terminal_count = 0

        def invocation(
            self,
            *,
            logical_compute_node_id: str,
            point_ordinals: tuple[int, ...],
            execution_id: DomainExecutionId,
            intent: DomainInvocationIntent,
            durability: DomainTransitionDurability,
        ) -> None:
            del point_ordinals, durability
            assert execution_id.logical_compute_node_id == logical_compute_node_id
            assert execution_id.intent_fingerprint == intent.intent_fingerprint
            self.invocation_count += 1

        def checkpoint(
            self,
            *,
            logical_compute_node_id: str,
            point_ordinals: tuple[int, ...],
            checkpoint: DomainJobCheckpoint,
        ) -> None:
            del logical_compute_node_id, point_ordinals, checkpoint
            raise AssertionError("synchronous sweep has no checkpoints")

        def terminal(
            self,
            *,
            logical_compute_node_id: str,
            point_ordinals: tuple[int, ...],
            receipt: DomainExecutionReceipt,
            durability: DomainTransitionDurability,
        ) -> None:
            del logical_compute_node_id, point_ordinals, durability
            assert receipt.status == "completed"
            self.terminal_count += 1

        def flush(self) -> None:
            return None

    invocation = close_domain_invocation(
        cast(
            "DomainResultMapping[str]",
            cast("object", ResultContract()),
        ),
        invocation_id="dense-sweep-invocation",
        target_id="dense-sweep-target",
        compiler_id="test-compiler",
        capability_fingerprint="test-capability",
        artifact_id="shared-program",
        artifact_fingerprint="shared-program-fingerprint",
        execution_summary={"program_reused": True},
        target_intent={"sweep_axis": "lo_frequency"},
        payload=object(),
    )

    def discard_result(
        _result: DomainExecutionResult[object],
        _accept: object,
    ) -> None:
        return None

    prepared = PreparedDomainExecution(
        instrument_ids=(),
        setup_write_footprint=(),
        setup_state_invalidations=(),
        state_requirements=(),
        realtime_write_footprint=(),
        realtime_state_invalidations=(),
        next_batch_max_points=1,
        invocation=cast("ErasedDomainInvocation", invocation),
        setup=None,
        job_runtime=cast("ErasedDomainJobRuntime", Runtime()),
        realize_into=cast("ErasedDomainRealizer", discard_result),
        transition_durability="batched",
    )
    point_count = 512
    points = tuple(
        AcceptedRunPoint(
            LogicalPointId(PointDomainId("dense-sweep", "root"), ordinal),
            {},
        )
        for ordinal in range(point_count)
    )
    jobs = tuple(
        RunDomainJob(f"dense-sweep-{ordinal}", (ordinal,), prepared)
        for ordinal in range(point_count)
    )
    transitions = CountingTransitionWriter()

    result = RunEffectInterpreter(
        run_id="dense-sweep-run",
        coordinate_ids=(),
        instruments=TestRunInstrumentHost(),
        domain_job_transitions=transitions,
    ).run(jobs, points=points)

    assert result.problems == ()
    assert result.domain_execution is not None
    assert result.domain_execution.attempt_count == point_count
    assert result.domain_execution.receipt_count == point_count
    assert result.domain_execution.completed_count == point_count
    assert result.domain_execution.target_ids == ("dense-sweep-target",)
    assert len(result.domain_execution.model_dump_json()) < 512
    assert transitions.invocation_count == point_count
    assert transitions.terminal_count == point_count

    class FailingFlushWriter(CountingTransitionWriter):
        @override
        def flush(self) -> None:
            raise RuntimeError("transition ledger unavailable")

    incomplete = RunEffectInterpreter(
        run_id="incomplete-detail-run",
        coordinate_ids=(),
        instruments=TestRunInstrumentHost(),
        domain_job_transitions=FailingFlushWriter(),
    ).run(jobs[:1], points=points[:1])
    assert incomplete.indeterminate
    assert incomplete.domain_execution is not None
    assert not incomplete.domain_execution.detail_complete


def test_domain_instrument_batches_stop_at_the_next_cancellation_boundary() -> None:
    inner = _Executor(RunHardwareBatchReceipt(operation_id="first"))
    instruments = _CancellationAwareDomainInstruments(
        cast("RunInstrumentHost", cast("object", inner)),
        cancellation_requested=lambda: bool(inner.batches),
    )

    def batch(operation_id: str) -> RunHardwareBatch:
        return RunHardwareBatch(
            operation_id=operation_id,
            actions=(
                RunHardwareInvoke(
                    effect_id=operation_id,
                    instrument_id="awg",
                    resource_id="awg",
                    interface_id="test.noop/v1",
                    operation_id="noop",
                ),
            ),
        )

    first = instruments.execute(batch("first"))
    with pytest.raises(DomainExecutionCancellationRequested):
        instruments.execute(batch("second"))

    assert first.operation_id == "first"
    assert [batch.operation_id for batch in inner.batches] == ["first"]


def test_setup_success_then_requirement_rejection_skips_realtime() -> None:
    setup = _Setup()
    realtime = _Realtime()
    operation_id = "domain:execution-key:reconcile-requirements"
    instruments = _Executor(
        RunHardwareBatchReceipt(
            operation_id=operation_id,
            problems=(_failure(),),
        )
    )
    runtime = _PreparedDomainJobRuntime(
        _prepared(
            setup=setup,
            realtime=realtime,
            requirements=(_requirement(),),
        )
    )

    receipt = runtime.start("execution-key", object(), instruments=instruments)

    assert isinstance(receipt, DomainExecutionReceipt)
    assert receipt.status == "not_executed"
    assert setup.calls == 1
    assert realtime.calls == 0
    assert [batch.operation_id for batch in instruments.batches] == [operation_id]


@pytest.mark.parametrize("receipt_kind", ["indeterminate", "mismatched"])
def test_uncertain_reconciliation_is_not_retried(
    receipt_kind: str,
) -> None:
    operation_id = "domain:execution-key:reconcile-requirements"
    receipt = RunHardwareBatchReceipt(
        operation_id=(
            "another-operation" if receipt_kind == "mismatched" else operation_id
        ),
        problems=(_failure(),) if receipt_kind == "indeterminate" else (),
        indeterminate=receipt_kind == "indeterminate",
    )
    setup = _Setup()
    realtime = _Realtime()
    instruments = _Executor(receipt)
    runtime = _PreparedDomainJobRuntime(
        _prepared(
            setup=setup,
            realtime=realtime,
            requirements=(_requirement(),),
        )
    )

    with pytest.raises(RuntimeError):
        runtime.start("execution-key", object(), instruments=instruments)

    assert setup.calls == 1
    assert realtime.calls == 0
    assert len(instruments.batches) == 1
