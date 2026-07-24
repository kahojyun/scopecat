from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import cast, override

import pytest
import scopecat as sc
from scopecat import Quantity
from scopecat.adapters.sqlite import SQLiteMeasurementDatasetRepository
from scopecat.compiler.linking.linked import LinkedPointMaterializer
from scopecat.execution.observation import RuntimeEvent, RuntimeTransitionEvent
from scopecat.execution.services import ExecutionJournalStore
from scopecat.kernel.errors import RunFailed, RunIndeterminate
from scopecat.kernel.problems import (
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
)
from scopecat.planning import system as systems
from scopecat.sdk.domain.compiler import DomainCompiledJob, DomainCompiler
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
from scopecat.testing import sqlite_execution_services

from quantum_lab_demo import (
    QuantumLabCompiler,
    quantum_lab_compiler,
)
from quantum_lab_demo.targets.fake_list_mode import (
    FakeListDomainRuntime,
    FakeListRun,
    SelectedFakeMeasurementRealization,
    default_fake_list_target,
)
from quantum_lab_demo.trace import QuantumLabTrace
from quantum_lab_demo.virtual_lab.parameters import (
    QUBIT_PARAMETER_TABLE,
    q0_parameter_key,
)
from quantum_lab_demo.virtual_lab.pulse_profile import QUANTUM_PULSE_PROFILE
from quantum_lab_demo.virtual_lab.quantum_responses import (
    quantum_lab_response_registry,
)
from quantum_lab_demo.workflows.fake_x_count_experiment import (
    X_COUNT,
    fake_x_count_capture,
    fake_x_count_scratch,
    fake_x_count_template,
    x_count_program,
)

from .demo_lab_experiment_testkit import (
    in_process_quantum_lab,
    reject_program_input_binding,
)


class _UnknownFetchFakeListDomainRuntime(FakeListDomainRuntime):
    @override
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


class _IndeterminateFakeListDomainRuntime(FakeListDomainRuntime):
    @override
    def submit(
        self,
        request: DomainSubmitRequest[SelectedFakeMeasurementRealization],
    ) -> DomainSubmitReceipt:
        _ = request
        raise RuntimeError("target did not return submit evidence")


class _SecondSubmitIndeterminateFakeListDomainRuntime(FakeListDomainRuntime):
    @override
    def submit(
        self,
        request: DomainSubmitRequest[SelectedFakeMeasurementRealization],
    ) -> DomainSubmitReceipt:
        if self.submit_calls == 1:
            raise RuntimeError("second target submission returned no evidence")
        return super().submit(request)


class _ConfiguredTestCompiler(QuantumLabCompiler):
    def __init__(self) -> None:
        super().__init__(
            target=default_fake_list_target(),
            runtime=FakeListDomainRuntime(),
            response_registry=quantum_lab_response_registry(),
            trace=QuantumLabTrace(),
            pulse_profile=QUANTUM_PULSE_PROFILE,
        )


class _RaisingCompiler(_ConfiguredTestCompiler):
    @property
    @override
    def compiler_id(self) -> str:
        return "tests.raising-domain-compiler"

    @override
    def prepare(
        self,
        job: DomainCompiledJob,
        context: DomainBatchContext,
    ) -> PreparedDomainExecution:
        del job, context
        raise RuntimeError("compiler implementation defect")


class _WrongResultCompiler(_ConfiguredTestCompiler):
    @property
    @override
    def compiler_id(self) -> str:
        return "tests.wrong-result-domain-compiler"

    @override
    def prepare(
        self,
        job: DomainCompiledJob,
        context: DomainBatchContext,
    ) -> PreparedDomainExecution:
        del job, context
        return cast("PreparedDomainExecution", object())


def test_fake_x_count_authors_direct_iq_and_derived_probabilities_separately() -> None:
    body = fake_x_count_capture.ir.body
    [program_call] = body.instances
    [execution] = program_call.module.body.domain_executions
    program = execution.program
    [transform] = body.measurement_transforms

    assert tuple(port.id for port in program.result_ports) == ("iq_shots",)
    assert tuple(result_id for result_id, _product in execution.result_bindings) == (
        "iq_shots",
    )
    assert execution.result_bindings[0][1].local_id == "iq_shots"
    assert [(role, product.local_id) for role, product in transform.input_bindings] == [
        ("iq_shots", "iq_shots")
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
        raise AssertionError(
            "domain execution must not construct materialized local semantics"
        )

    monkeypatch.setattr(
        systems,
        "materialize_local_execution",
        reject_local_lowering,
    )
    semantics: dict[str, object] = {}
    for authoring in ("template", "scratch"):
        compiler = quantum_lab_compiler()
        lab = in_process_quantum_lab(
            project_root=tmp_path / authoring, compiler=compiler
        )
        experiment = (
            lab.prepare(fake_x_count_template)
            if authoring == "template"
            else lab.prepare(
                fake_x_count_scratch(
                    x_counts=(0, 1, 2, 4),
                ),
            )
        )

        preview = experiment.preview()
        run = experiment.run()
        dataset = run.data().measurements().dataset
        journal = sqlite_execution_services(lab.project_root).journal_for(run.id)

        assert run.manifest.status == "completed"
        assert compiler.trace.physical_execution_count == 1
        [evidence] = compiler.trace.preparations(x_count_program.id)
        assert tuple(point.value("x_count") for point in evidence.points) == (
            0,
            1,
            2,
            4,
        )
        assert len(evidence.entries) == 4
        assert evidence.artifact_fingerprint.startswith("sha256:")
        assert preview.point_count == len(dataset.records) == 4
        assert [record.id for record in preview.records] == [
            "probability_0",
            "probability_1",
        ]
        assert all(
            record.kind != "instrument_state_evidence"
            for record in run.manifest.records
        )
        assert {entry.stage for entry in journal.entries()} >= {
            "domain_submit",
            "domain_fetch",
            "append_measurement",
            "seal_measurement",
        }
        for record in dataset.records:
            probability_0 = record.observables["probability_0"]
            probability_1 = record.observables["probability_1"]
            assert isinstance(probability_0, Quantity)
            assert isinstance(probability_1, Quantity)
            assert probability_0.value + probability_1.value == pytest.approx(1.0)
        semantics[authoring] = _standard_domain_semantics(preview, journal)

    assert semantics["template"] == semantics["scratch"]


def test_fake_x_count_compiler_absorbs_affine_point_input_without_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        LinkedPointMaterializer,
        "bind_domain_inputs",
        reject_program_input_binding,
    )
    capture = fake_x_count_capture.instantiate(
        "capture",
        x_count=2 * X_COUNT + 1,
    )

    @sc.template(id="test.fake-x-count.affine", kind="fake_x_count")
    def affine_template() -> sc.ExperimentBody:
        return (
            sc.experiment(capture)
            .scan(X_COUNT, (0, 1, 2))
            .record_product(capture.products.probability_1, record_id="probability_1")
        )

    compiler = quantum_lab_compiler()
    lab = in_process_quantum_lab(project_root=tmp_path)

    run = lab.prepare(affine_template, system=_domain_only(compiler)).run()
    records = run.data().measurements().dataset.records

    assert run.manifest.status == "completed"
    assert compiler.trace.physical_execution_count == 1
    assert [record.coordinates["x_count"] for record in records] == [0, 1, 2]


def test_fake_x_count_compiler_projects_zipped_axis_without_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        LinkedPointMaterializer,
        "bind_domain_inputs",
        reject_program_input_binding,
    )
    auxiliary = sc.coordinate("auxiliary", sc.ScalarType(sc.IntType()))
    capture = fake_x_count_capture.instantiate("capture", x_count=X_COUNT)

    @sc.template(id="test.fake-x-count.zip", kind="fake_x_count")
    def zipped_template() -> sc.ExperimentBody:
        return (
            sc.experiment(capture)
            .scan(
                sc.zip(
                    sc.axis(X_COUNT, (0, 1, 2)),
                    sc.axis(auxiliary, (10, 11, 12)),
                )
            )
            .record_product(
                capture.products.probability_1,
                record_id="probability_1",
            )
        )

    compiler = quantum_lab_compiler()
    lab = in_process_quantum_lab(project_root=tmp_path)

    run = lab.prepare(zipped_template, system=_domain_only(compiler)).run()

    assert run.manifest.status == "completed"
    assert compiler.trace.physical_execution_count == 1
    assert [
        (record.coordinates["x_count"], record.coordinates["auxiliary"])
        for record in run.data().measurements().dataset.records
    ] == [(0, 10), (1, 11), (2, 12)]


def test_fake_x_count_scans_compiler_qubit_collection(tmp_path: Path) -> None:
    duration = sc.coordinate(
        "x_duration",
        sc.ScalarType(sc.QuantityType(unit="ns")),
    )
    capture = fake_x_count_capture(x_count=1)

    @sc.scratch(id="test.fake-x-count.compiler-scan", kind="fake_x_count")
    def compiler_scan() -> sc.ExperimentBody:
        return (
            sc.experiment(capture)
            .scan(
                sc.param_axis(
                    duration,
                    sc.param_row(QUBIT_PARAMETER_TABLE, **q0_parameter_key()),
                    "x_duration",
                    (Quantity(4, "ns"), Quantity(6, "ns")),
                )
            )
            .record_product(capture.products.probability_1)
        )

    compiler = quantum_lab_compiler()
    run = (
        in_process_quantum_lab(project_root=tmp_path, compiler=compiler)
        .prepare(compiler_scan())
        .run()
    )
    [preparation] = compiler.trace.preparations(x_count_program.id)

    assert run.manifest.status == "completed"
    assert tuple(entry.scheduled.duration_seconds for entry in preparation.entries) == (
        Decimal("12e-9"),
        Decimal("14e-9"),
    )


def test_two_ordered_domain_calls_share_target_and_produce_canonical_results(
    tmp_path: Path,
) -> None:
    first = fake_x_count_capture.instantiate("first", x_count=X_COUNT)
    second = fake_x_count_capture.instantiate("second", x_count=X_COUNT)

    @sc.template(id="test.fake-x-count.two-calls", kind="fake_x_count")
    def two_call_template() -> sc.ExperimentBody:
        return (
            sc.experiment(first, second)
            .scan(X_COUNT, (0, 1, 2))
            .record_product(first.products.probability_0, record_id="first-p0")
            .record_product(second.products.probability_1, record_id="second-p1")
        )

    compiler = quantum_lab_compiler()
    lab = in_process_quantum_lab(project_root=tmp_path)

    run = lab.prepare(
        two_call_template,
        system=_domain_only(compiler),
    ).run()
    records = run.data().measurements().dataset.records
    journal = sqlite_execution_services(lab.project_root).journal_for(run.id)

    assert run.manifest.status == "completed"
    assert compiler.trace.physical_execution_count == 2
    assert len(records) == 3
    assert all(
        set(record.observables) == {"first-p0", "second-p1"} for record in records
    )
    submission_operations = [
        entry.operation_id
        for entry in journal.entries()
        if entry.stage == "domain_submit" and entry.state == "started"
    ]
    assert len(submission_operations) == 2
    assert len(set(submission_operations)) == 2


@pytest.mark.parametrize("compiler", [_RaisingCompiler(), _WrongResultCompiler()])
def test_compiler_boundary_normalizes_deferred_contract_defects_during_run(
    compiler: object,
    tmp_path: Path,
) -> None:
    lab = in_process_quantum_lab(project_root=tmp_path)
    experiment = lab.prepare(
        fake_x_count_template,
        system=_domain_only(
            cast("DomainCompiler", compiler),
        ),
    )

    report = experiment.check()

    assert report.ok
    with pytest.raises(RunFailed) as caught:
        experiment.run()
    assert any(
        problem.code == "domain_execution_failed"
        for problem in caught.value.outcome.problems
    )
    [run] = lab.runs()
    assert run.manifest.status == "failed"


def test_indeterminate_submit_retains_durable_target_correlation_context(
    tmp_path: Path,
) -> None:
    compiler = quantum_lab_compiler(runtime=_IndeterminateFakeListDomainRuntime())
    lab = in_process_quantum_lab(project_root=tmp_path)
    experiment = lab.prepare(
        fake_x_count_template,
        system=_domain_only(compiler),
    )

    events: list[RuntimeEvent] = []
    with pytest.raises(RunIndeterminate) as caught:
        experiment.run(event_sink=events.append)

    recovery = next(
        problem
        for problem in caught.value.outcome.problems
        if problem.code == "domain_runtime_terminalized"
    )
    assert recovery.details["phase"] == "submit"
    assert recovery.details["retry_contract"] == "not_retryable"
    assert recovery.details["automatic_resume"] is False
    assert recovery.details["submission_key"]
    journal = sqlite_execution_services(lab.project_root).journal_for(
        caught.value.run_id
    )
    started = next(
        entry
        for entry in journal.entries()
        if entry.stage == "domain_submit" and entry.state == "started"
    )
    intent = DomainInvocationIntent.model_validate(
        started.evidence["invocation_intent"]
    )
    assert intent.target_id
    assert any(
        entry.stage == "domain_submit" and entry.state == "unknown"
        for entry in journal.entries()
    )
    failed_points = [
        event
        for event in events
        if isinstance(event, RuntimeTransitionEvent)
        and event.stage == "point"
        and event.state == "failed"
        and event.point_indices
    ]
    assert [event.point_indices for event in failed_points] == [(0, 1, 2, 3)]
    assert not any(
        isinstance(event, RuntimeTransitionEvent)
        and event.stage == "point"
        and event.state == "started"
        for event in events
    )


def test_later_domain_job_failure_preserves_points_from_earlier_jobs(
    tmp_path: Path,
) -> None:
    target = replace(default_fake_list_target(), max_list_entries=2)
    runtime = _SecondSubmitIndeterminateFakeListDomainRuntime()
    compiler = quantum_lab_compiler(
        target=target,
        runtime=runtime,
    )
    lab = in_process_quantum_lab(project_root=tmp_path)
    events: list[RuntimeEvent] = []

    with pytest.raises(RunIndeterminate):
        lab.prepare(
            fake_x_count_template,
            system=_domain_only(compiler),
        ).run(event_sink=events.append)

    failed_points = [
        event.point_indices
        for event in events
        if isinstance(event, RuntimeTransitionEvent)
        and event.stage == "point"
        and event.state == "failed"
        and event.point_indices
    ]
    completed_points = [
        event.point_indices
        for event in events
        if isinstance(event, RuntimeTransitionEvent)
        and event.stage == "point"
        and event.state == "completed"
        and event.point_indices
    ]
    assert compiler.trace.physical_execution_count == 1
    assert runtime.submit_calls == 1
    assert completed_points == [(0,), (1,)]
    assert failed_points == [(2, 3)]


def test_unknown_fetch_terminalizes_as_indeterminate_with_known_job_context(
    tmp_path: Path,
) -> None:
    compiler = quantum_lab_compiler(runtime=_UnknownFetchFakeListDomainRuntime())
    lab = in_process_quantum_lab(project_root=tmp_path)
    experiment = lab.prepare(
        fake_x_count_template,
        system=_domain_only(compiler),
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
    assert compiler.trace.physical_execution_count == 1
    journal = sqlite_execution_services(lab.project_root).journal_for(
        caught.value.run_id
    )
    assert any(
        entry.stage == "domain_fetch" and entry.state == "unknown"
        for entry in journal.entries()
    )


def test_uncertain_measurement_write_retains_durable_correlation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_record_write(_committer: object, _chunk: object) -> object:
        raise RuntimeError("record store returned no receipt")

    monkeypatch.setattr(
        SQLiteMeasurementDatasetRepository,
        "append",
        fail_record_write,
    )
    compiler = quantum_lab_compiler()
    lab = in_process_quantum_lab(project_root=tmp_path)
    experiment = lab.prepare(
        fake_x_count_template,
        system=_domain_only(compiler),
    )

    with pytest.raises(RunIndeterminate) as caught:
        experiment.run()

    recovery = next(
        problem
        for problem in caught.value.outcome.problems
        if problem.code == "measurement_recording_terminalized"
    )
    assert recovery.details["write_may_have_completed"] is True
    assert recovery.details["dataset_id"] == "raw-measurements"
    assert "retry_contract" not in recovery.details
    assert "reconciliation" not in recovery.details
    assert compiler.trace.physical_execution_count == 1
    [persisted] = lab.runs()
    assert persisted.manifest.status == "unknown"


def test_successful_recording_does_not_reload_committed_measurements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_measurement_reload(_committer: object) -> object:
        raise OSError("measurement chunk could not be read")

    monkeypatch.setattr(
        SQLiteMeasurementDatasetRepository,
        "measurements",
        fail_measurement_reload,
    )
    compiler = quantum_lab_compiler()
    lab = in_process_quantum_lab(project_root=tmp_path)
    experiment = lab.prepare(
        fake_x_count_template,
        system=_domain_only(compiler),
    )

    run = experiment.run()

    assert compiler.trace.physical_execution_count == 1
    [persisted] = lab.runs()
    assert persisted.id == run.id
    assert persisted.manifest.status == "completed"


def _standard_domain_semantics(
    preview: sc.ExperimentPreview,
    journal: ExecutionJournalStore,
) -> object:
    submit_intent = next(
        entry
        for entry in journal.entries()
        if entry.stage == "domain_submit" and entry.state == "started"
    )
    intent = DomainInvocationIntent.model_validate(
        submit_intent.evidence["invocation_intent"]
    )
    return (
        intent.target_id,
        intent.compiler_id,
        intent.capability_fingerprint,
        intent.artifact_fingerprint,
        tuple(point.coordinates["x_count"] for point in preview.points),
        tuple(record.id for record in preview.records),
    )


def _domain_only(compiler: DomainCompiler) -> sc.ExperimentSystem:
    return sc.ExperimentSystem(domain_compiler=compiler)
