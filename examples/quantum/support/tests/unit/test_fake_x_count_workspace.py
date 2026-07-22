from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast, override

import pytest
import scopecat as sc
from scopecat import Quantity
from scopecat.adapters.filesystem.execution import (
    FilesystemExecutionJournal,
    FilesystemMeasurementDatasetRepository,
)
from scopecat.compiler.linking.linked import LinkedPointMaterializer
from scopecat.execution.observation import RuntimeEvent, RuntimeTransitionEvent
from scopecat.kernel.errors import CheckFailed, RunFailed, RunIndeterminate
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

from quantum_lab_demo import (
    QuantumLabCompiler,
    quantum_lab,
    quantum_lab_compiler,
)
from quantum_lab_demo.experiments import READOUT_TEMPLATE
from quantum_lab_demo.reference_experiments.cz_phase_calibration import (
    cz_conditional_phase,
)
from quantum_lab_demo.reference_experiments.cz_phase_experiment import (
    cz_phase_template,
)
from quantum_lab_demo.reference_experiments.drag_beta_experiment import (
    drag_beta_program,
    drag_beta_template,
)
from quantum_lab_demo.reference_experiments.fake_x_count_experiment import (
    X_COUNT,
    fake_x_count_capture,
    fake_x_count_scratch_experiment,
    fake_x_count_template,
    x_count_program,
)
from quantum_lab_demo.reference_experiments.production_drag_gate import (
    production_drag_program,
    production_drag_template,
)
from quantum_lab_demo.reference_experiments.ramsey_phase_experiment import (
    ramsey_phase_program,
    ramsey_phase_template,
)
from quantum_lab_demo.targets.fake_list_mode import (
    FakeListDomainRuntime,
    FakeListRun,
    SelectedFakeMeasurementRealization,
    default_fake_list_target,
)
from quantum_lab_demo.trace import QuantumLabTrace
from quantum_lab_demo.virtual_lab.calibrations import (
    quantum_lab_calibration_catalog,
)
from quantum_lab_demo.virtual_lab.quantum_responses import (
    quantum_lab_response_registry,
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
            calibration_catalog=quantum_lab_calibration_catalog(),
            response_registry=quantum_lab_response_registry(),
            trace=QuantumLabTrace(),
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


def test_one_quantum_lab_compiler_prepares_every_reference_program(
    tmp_path: Path,
) -> None:
    compiler = quantum_lab_compiler()
    lab = quantum_lab(workspace=tmp_path, compiler=compiler)

    runs = tuple(
        lab.prepare(template).run()
        for template in (
            fake_x_count_template,
            drag_beta_template,
            production_drag_template,
            ramsey_phase_template,
            cz_phase_template,
        )
    )

    assert all(run.manifest.status == "completed" for run in runs)
    assert tuple(
        evidence.program_id for evidence in compiler.trace.all_preparations
    ) == (
        x_count_program.id,
        drag_beta_program.id,
        production_drag_program.id,
        ramsey_phase_program.id,
        cz_conditional_phase.id,
    )
    assert tuple(
        len(evidence.points) for evidence in compiler.trace.all_preparations
    ) == (
        4,
        15,
        1,
        3,
        24,
    )
    [target_compiler_id] = {
        evidence.artifact.compiler_id.value
        for evidence in compiler.trace.all_preparations
    }
    assert target_compiler_id != compiler.compiler_id


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
        lab = quantum_lab(workspace=tmp_path / authoring, compiler=compiler)
        experiment = (
            lab.prepare(fake_x_count_template)
            if authoring == "template"
            else lab.prepare(
                fake_x_count_scratch_experiment(
                    x_counts=(0, 1, 2, 4),
                ),
            )
        )

        preview = experiment.preview()
        run = experiment.run()
        dataset = run.data().measurements().dataset
        journal = FilesystemExecutionJournal(lab.workspace, run_id=run.id)

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
    def reject_input_binding(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("finite affine point axes must not bind domain inputs")

    monkeypatch.setattr(
        LinkedPointMaterializer,
        "bind_domain_inputs",
        reject_input_binding,
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
    lab = quantum_lab(workspace=tmp_path)

    run = lab.prepare(affine_template, system=_domain_only(compiler)).run()
    records = run.data().measurements().dataset.records

    assert run.manifest.status == "completed"
    assert compiler.trace.physical_execution_count == 1
    assert [record.coordinates["x_count"] for record in records] == [0, 1, 2]


def test_fake_x_count_compiler_projects_zipped_axis_without_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_input_binding(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("finite zipped axes must not bind domain inputs")

    monkeypatch.setattr(
        LinkedPointMaterializer,
        "bind_domain_inputs",
        reject_input_binding,
    )
    auxiliary = sc.point("auxiliary", sc.ScalarType(sc.IntType()))
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
    lab = quantum_lab(workspace=tmp_path)

    run = lab.prepare(zipped_template, system=_domain_only(compiler)).run()

    assert run.manifest.status == "completed"
    assert compiler.trace.physical_execution_count == 1
    assert [
        (record.coordinates["x_count"], record.coordinates["auxiliary"])
        for record in run.data().measurements().dataset.records
    ] == [(0, 10), (1, 11), (2, 12)]


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
    lab = quantum_lab(workspace=tmp_path)

    run = lab.prepare(
        two_call_template,
        system=_domain_only(compiler),
    ).run()
    records = run.data().measurements().dataset.records
    journal = FilesystemExecutionJournal(lab.workspace, run_id=run.id)

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


def test_domain_only_system_reports_missing_local_provider(
    tmp_path: Path,
) -> None:
    lab = quantum_lab(workspace=tmp_path)
    experiment = lab.prepare(
        READOUT_TEMPLATE,
        system=_domain_only(quantum_lab_compiler()),
    )
    experiment = experiment.input("qubit", "q0")

    report = experiment.check()

    assert not report.ok
    assert report.problems[0].code == "local_instrument_provider_missing"
    with pytest.raises(CheckFailed):
        experiment.run()
    assert lab.runs() == ()


@pytest.mark.parametrize("compiler", [_RaisingCompiler(), _WrongResultCompiler()])
def test_compiler_boundary_normalizes_deferred_contract_defects_during_run(
    compiler: object,
    tmp_path: Path,
) -> None:
    lab = quantum_lab(workspace=tmp_path)
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
    lab = quantum_lab(workspace=tmp_path)
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
    journal = FilesystemExecutionJournal(lab.workspace, run_id=caught.value.run_id)
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
    lab = quantum_lab(workspace=tmp_path)
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
    lab = quantum_lab(workspace=tmp_path)
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
    journal = FilesystemExecutionJournal(lab.workspace, run_id=caught.value.run_id)
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
        FilesystemMeasurementDatasetRepository,
        "append",
        fail_record_write,
    )
    compiler = quantum_lab_compiler()
    lab = quantum_lab(workspace=tmp_path)
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
        FilesystemMeasurementDatasetRepository,
        "measurements",
        fail_measurement_reload,
    )
    compiler = quantum_lab_compiler()
    lab = quantum_lab(workspace=tmp_path)
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
