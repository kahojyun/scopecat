from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
import scopecat as sc
from scopecat import Quantity
from scopecat.adapters.filesystem.execution import (
    FilesystemExecutionJournal,
    FilesystemMeasurementRecordCommitter,
)
from scopecat.kernel.errors import CheckFailed, RunIndeterminate
from scopecat.kernel.problems import (
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
)
from scopecat.planning import backend as execution_backends
from scopecat.records.run_plan import RunPlanDomainExecution, RunPlanRecord
from scopecat.sdk.domain.context import DomainBatchContext
from scopecat.sdk.domain.execution import (
    PreparedDomainExecution,
)
from scopecat.sdk.domain.invocation import DomainInvocationIntent
from scopecat.sdk.domain.runtime import (
    DomainFetchCandidate,
    DomainFetchReceipt,
    DomainFetchRequest,
    DomainSubmitReceipt,
    DomainSubmitRequest,
)

from quantum_lab_demo import quantum_lab
from quantum_lab_demo.experiments import READOUT_TEMPLATE
from quantum_lab_demo.reference_experiments import (
    FAKE_X_COUNT_ADAPTER_ID,
    FAKE_X_COUNT_CAPTURE_MODULE,
    FAKE_X_COUNT_TEMPLATE,
    FakeXCountDomainExecutionAdapter,
    fake_x_count_scratch_experiment,
)
from quantum_lab_demo.targets.fake_list_mode import (
    FakeListDomainRuntime,
    FakeListRun,
    SelectedFakeMeasurementRealization,
)


class _PendingFakeListDomainRuntime(FakeListDomainRuntime):
    def fetch(
        self,
        request: DomainFetchRequest,
    ) -> DomainFetchCandidate[FakeListRun]:
        return DomainFetchCandidate(
            receipt=DomainFetchReceipt(
                identity=request.identity,
                job_id=request.job_id,
                status="pending",
            )
        )


class _RaisingFetchFakeListDomainRuntime(FakeListDomainRuntime):
    def fetch(
        self,
        request: DomainFetchRequest,
    ) -> DomainFetchCandidate[FakeListRun]:
        _ = request
        raise RuntimeError("target result read failed")


class _UnknownFetchFakeListDomainRuntime(FakeListDomainRuntime):
    def fetch(
        self,
        request: DomainFetchRequest,
    ) -> DomainFetchCandidate[FakeListRun]:
        return DomainFetchCandidate(
            receipt=DomainFetchReceipt(
                identity=request.identity,
                job_id=request.job_id,
                status="unknown",
                problems=(
                    blocking_problem(
                        "fake_fetch_outcome_unknown",
                        "the fake target could not establish result availability",
                        category=ProblemCategory.OPERATION,
                        phase=ProblemPhase.EXECUTION,
                    ),
                ),
            )
        )


class _PendingFakeXCountAdapter(FakeXCountDomainExecutionAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.runtime = _PendingFakeListDomainRuntime()


class _IndeterminateFakeListDomainRuntime(FakeListDomainRuntime):
    def submit(
        self,
        request: DomainSubmitRequest[SelectedFakeMeasurementRealization],
    ) -> DomainSubmitReceipt:
        _ = request
        raise RuntimeError("target did not return submit evidence")


class _IndeterminateFakeXCountAdapter(FakeXCountDomainExecutionAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.runtime = _IndeterminateFakeListDomainRuntime()


class _RaisingAdapter(FakeXCountDomainExecutionAdapter):
    @property
    def adapter_id(self) -> str:
        return "tests.raising-domain-adapter"

    def prepare(self, context: DomainBatchContext) -> PreparedDomainExecution:
        del context
        raise RuntimeError("adapter implementation defect")


class _WrongResultAdapter(FakeXCountDomainExecutionAdapter):
    @property
    def adapter_id(self) -> str:
        return "tests.wrong-result-domain-adapter"

    def prepare(self, context: DomainBatchContext) -> PreparedDomainExecution:
        del context
        return cast("PreparedDomainExecution", object())


def test_fake_x_count_authors_direct_iq_and_derived_probabilities_separately() -> None:
    body = FAKE_X_COUNT_CAPTURE_MODULE.ir.body
    [program] = body.domain_programs
    [call] = body.domain_calls
    [transform] = body.measurement_transforms

    assert tuple(port.id for port in program.result_ports) == ("iq_shots",)
    assert tuple(result_id for result_id, _product in call.result_bindings) == (
        "iq_shots",
    )
    assert call.result_bindings[0][1].local_id == "integrated_iq_shots"
    assert [(role, product.local_id) for role, product in transform.input_bindings] == [
        ("iq_shots", "integrated_iq_shots")
    ]
    assert [
        (role, product.local_id) for role, product in transform.output_bindings
    ] == [
        ("probability_0", "probability_0"),
        ("probability_1", "probability_1"),
    ]
    assert transform.semantic.id == (
        "scopecat_quantum.readout.binary_iq_discrimination"
    )
    assert transform.semantic.portability == "host_only"
    assert transform.semantic.parameters["discriminator"] == {
        "schema_version": "scopecat_quantum.binary_iq_discriminator.v1",
        "state_0_centroid": {"real": -1.0, "imag": 0.0, "unit": "ratio"},
        "state_1_centroid": {"real": 1.0, "imag": 0.0, "unit": "ratio"},
        "tie_policy": "state_0",
    }


def test_fake_x_count_authoring_paths_share_one_standard_domain_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_local_lowering(_linked: object) -> object:
        raise AssertionError("domain execution must not construct a local BoundPlan")

    monkeypatch.setattr(
        execution_backends,
        "materialize_local_plan",
        reject_local_lowering,
    )
    semantics: dict[str, object] = {}
    for authoring in ("template", "scratch"):
        adapter = FakeXCountDomainExecutionAdapter()
        lab = quantum_lab(workspace=tmp_path / authoring)
        experiment = (
            lab.prepare(
                FAKE_X_COUNT_TEMPLATE,
                execution_backend=_domain_only(adapter),
            )
            if authoring == "template"
            else lab.prepare(
                fake_x_count_scratch_experiment(
                    lab,
                    x_counts=(0, 1, 2, 4),
                ),
                execution_backend=_domain_only(adapter),
            )
        )

        preview = experiment.preview()
        run = experiment.run()
        dataset = run.data().measurements().dataset
        plan = run.plan
        journal = FilesystemExecutionJournal(lab.workspace, run_id=run.id)

        assert run.manifest.status == "completed"
        assert adapter.runtime.physical_execution_count == 1
        assert preview.point_count == plan.point_count == len(dataset.records) == 4
        assert {record.id: record.producer_kind for record in preview.records} == {
            "probability_0": "host_transform",
            "probability_1": "host_transform",
        }
        assert all(
            record.kind != "instrument_state_evidence"
            for record in run.manifest.records
        )
        assert {entry.stage for entry in journal.entries()} >= {
            "domain_submit",
            "domain_fetch",
            "record_measurement",
        }
        for record in dataset.records:
            probability_0 = record.observables["probability_0"]
            probability_1 = record.observables["probability_1"]
            assert isinstance(probability_0, Quantity)
            assert isinstance(probability_1, Quantity)
            assert probability_0.value + probability_1.value == pytest.approx(1.0)
        semantics[authoring] = _standard_domain_semantics(plan, journal)

    assert semantics["template"] == semantics["scratch"]


def test_explicit_domain_adapter_rejection_does_not_fall_back_to_local_provider(
    tmp_path: Path,
) -> None:
    lab = quantum_lab(workspace=tmp_path)
    experiment = lab.prepare(
        READOUT_TEMPLATE,
        execution_backend=_domain_only(FakeXCountDomainExecutionAdapter()),
    )
    experiment = experiment.input("qubit", "q0")

    report = experiment.check()

    assert not report.ok
    assert report.problems[0].code == "execution_task_claim_missing"
    with pytest.raises(CheckFailed):
        experiment.run()
    assert lab.runs() == ()


@pytest.mark.parametrize("adapter", [_RaisingAdapter(), _WrongResultAdapter()])
def test_adapter_boundary_normalizes_ordinary_contract_defects_before_run(
    adapter: object,
    tmp_path: Path,
) -> None:
    lab = quantum_lab(workspace=tmp_path)
    experiment = lab.prepare(
        FAKE_X_COUNT_TEMPLATE,
        execution_backend=_domain_only(
            cast("sc.DomainExecutionAdapter", adapter),
        ),
    )

    report = experiment.check()

    assert not report.ok
    assert report.problems[0].code == "execution_backend_prepare_failed"
    with pytest.raises(CheckFailed):
        experiment.run()
    assert lab.runs() == ()


def test_synchronous_adapter_pending_result_terminalizes_as_indeterminate(
    tmp_path: Path,
) -> None:
    adapter = _PendingFakeXCountAdapter()
    lab = quantum_lab(workspace=tmp_path)
    experiment = lab.prepare(
        FAKE_X_COUNT_TEMPLATE,
        execution_backend=_domain_only(adapter),
    )

    with pytest.raises(RunIndeterminate) as caught:
        experiment.run()

    outcome = caught.value.outcome
    contract_problem = next(
        problem
        for problem in outcome.problems
        if problem.code == "domain_synchronous_completion_contract_violated"
    )
    assert outcome.certainty == "indeterminate"
    assert outcome.termination_reason == "effect_outcome_unknown"
    assert contract_problem.category.value == "provider_contract"
    assert contract_problem.details["automatic_resume"] is False
    assert "retry" not in contract_problem.details
    assert adapter.runtime.physical_execution_count == 1
    [persisted] = lab.runs()
    assert persisted.id == caught.value.run_id
    assert persisted.manifest.status == "unknown"


def test_indeterminate_submit_retains_durable_target_reconciliation_context(
    tmp_path: Path,
) -> None:
    adapter = _IndeterminateFakeXCountAdapter()
    lab = quantum_lab(workspace=tmp_path)
    experiment = lab.prepare(
        FAKE_X_COUNT_TEMPLATE,
        execution_backend=_domain_only(adapter),
    )

    with pytest.raises(RunIndeterminate) as caught:
        experiment.run()

    recovery = next(
        problem
        for problem in caught.value.outcome.problems
        if problem.code == "domain_runtime_terminalized"
    )
    assert recovery.details["phase"] == "submit"
    assert recovery.details["retry_contract"] == "after_reconciliation"
    assert recovery.details["automatic_resume"] is False
    assert recovery.details["submission_key"]
    plan = lab.get_run(caught.value.run_id).plan
    assert _domain_execution(plan).batches[0].target_id
    journal = FilesystemExecutionJournal(lab.workspace, run_id=caught.value.run_id)
    assert any(
        entry.stage == "domain_submit" and entry.state == "unknown"
        for entry in journal.entries()
    )


@pytest.mark.parametrize(
    "runtime_type",
    [_RaisingFetchFakeListDomainRuntime, _UnknownFetchFakeListDomainRuntime],
)
def test_unknown_fetch_terminalizes_as_indeterminate_with_known_job_context(
    runtime_type: type[FakeListDomainRuntime],
    tmp_path: Path,
) -> None:
    adapter = FakeXCountDomainExecutionAdapter()
    adapter.runtime = runtime_type()
    lab = quantum_lab(workspace=tmp_path)
    experiment = lab.prepare(
        FAKE_X_COUNT_TEMPLATE,
        execution_backend=_domain_only(adapter),
    )

    with pytest.raises(RunIndeterminate) as caught:
        experiment.run()

    recovery = next(
        problem
        for problem in caught.value.outcome.problems
        if problem.code == "domain_runtime_terminalized"
    )
    assert caught.value.outcome.certainty == "indeterminate"
    assert recovery.details["phase"] == "fetch"
    assert recovery.details["job_id"]
    assert recovery.details["automatic_resume"] is False
    assert adapter.runtime.physical_execution_count == 1
    journal = FilesystemExecutionJournal(lab.workspace, run_id=caught.value.run_id)
    assert any(
        entry.stage == "domain_fetch" and entry.state == "unknown"
        for entry in journal.entries()
    )


def test_uncertain_measurement_write_retains_reconciliation_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_record_write(_committer: object, _chunk: object) -> object:
        raise RuntimeError("record store returned no receipt")

    monkeypatch.setattr(
        FilesystemMeasurementRecordCommitter,
        "commit",
        fail_record_write,
    )
    adapter = FakeXCountDomainExecutionAdapter()
    lab = quantum_lab(workspace=tmp_path)
    experiment = lab.prepare(
        FAKE_X_COUNT_TEMPLATE,
        execution_backend=_domain_only(adapter),
    )

    with pytest.raises(RunIndeterminate) as caught:
        experiment.run()

    recovery = next(
        problem
        for problem in caught.value.outcome.problems
        if problem.code == "measurement_recording_terminalized"
    )
    assert recovery.details["write_may_have_completed"] is True
    assert recovery.details["retry_contract"] == "safe"
    assert recovery.details["automatic_resume"] is False
    assert recovery.details["point_index"] == 0
    assert adapter.runtime.physical_execution_count == 1
    [persisted] = lab.runs()
    assert persisted.manifest.status == "unknown"


def test_measurement_reload_failure_still_publishes_indeterminate_terminal_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_measurement_reload(_committer: object) -> object:
        raise OSError("measurement chunk could not be read")

    monkeypatch.setattr(
        FilesystemMeasurementRecordCommitter,
        "measurements",
        fail_measurement_reload,
    )
    adapter = FakeXCountDomainExecutionAdapter()
    lab = quantum_lab(workspace=tmp_path)
    experiment = lab.prepare(
        FAKE_X_COUNT_TEMPLATE,
        execution_backend=_domain_only(adapter),
    )

    with pytest.raises(RunIndeterminate) as caught:
        experiment.run()

    recovery = next(
        problem
        for problem in caught.value.outcome.problems
        if problem.code == "execution_plan_measurement_reload_terminalized"
    )
    assert recovery.details["storage_ref"] == "execution-measurements"
    assert recovery.details["automatic_resume"] is False
    assert adapter.runtime.physical_execution_count == 1
    [persisted] = lab.runs()
    assert persisted.id == caught.value.run_id
    assert persisted.manifest.status == "unknown"


def _standard_domain_semantics(
    plan: RunPlanRecord,
    journal: FilesystemExecutionJournal,
) -> object:
    submit_intent = next(
        entry
        for entry in journal.entries()
        if entry.stage == "domain_submit" and entry.state == "started"
    )
    intent = DomainInvocationIntent.model_validate(
        submit_intent.evidence["invocation_intent"]
    )
    execution = _domain_execution(plan)
    [batch] = execution.batches
    assert execution.adapter_id == FAKE_X_COUNT_ADAPTER_ID
    assert batch.semantic_operation_id == "capture/execute"
    assert batch.completion_contract == "synchronous"
    assert batch.invocation_id == intent.invocation_id
    assert batch.intent_fingerprint == intent.intent_fingerprint
    assert batch.target_id == intent.target_id
    assert batch.compiler_id == intent.compiler_id
    assert batch.capability_fingerprint == intent.capability_fingerprint
    assert batch.artifact_id == intent.artifact_id
    assert batch.artifact_fingerprint == intent.artifact_fingerprint
    assert set(batch.model_dump(mode="json")).isdisjoint(
        {"payload", "entry_address", "result_address", "target_address"}
    )
    return (
        intent.target_id,
        intent.compiler_id,
        intent.capability_fingerprint,
        intent.artifact_fingerprint,
        tuple(point.coordinates["x_count"] for point in plan.points),
        tuple((record.id, record.producer_kind) for record in plan.records),
    )


def _domain_execution(plan: RunPlanRecord) -> RunPlanDomainExecution:
    executions = [
        unit
        for unit in plan.execution_units
        if isinstance(unit, RunPlanDomainExecution)
    ]
    assert len(executions) == 1
    return executions[0]


def _domain_only(adapter: sc.DomainExecutionAdapter) -> sc.ExecutionBackend:
    return sc.ExecutionBackend(domain_adapters=(adapter,))
