from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast, override

import pytest
import scopecat as sc
from scopecat import Quantity
from scopecat.adapters.sqlite import (
    SQLiteMeasurementDatasetRepository,
)
from scopecat.execution.observation import RuntimeEvent, RuntimeTransitionEvent
from scopecat.kernel.errors import RunIndeterminate
from scopecat.kernel.problems import (
    ProblemPhase,
    problem,
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
from tests.testkit.runtime import (
    SQLiteTestExecutionJournal,
    sqlite_execution_session,
)

from quantum_lab_demo import (
    QuantumLabCompiler,
    quantum_lab_compiler,
)
from quantum_lab_demo.targets.fake_list_mode import (
    FakeListDomainRuntime,
    FakeListRun,
    SelectedFakeMeasurementRealization,
    configured_fake_list_target,
)
from quantum_lab_demo.virtual_lab.parameters import (
    QUBIT_PARAMETER_TABLE,
    q0_parameter_key,
)
from quantum_lab_demo.virtual_lab.pulse_profile import QUANTUM_PULSE_PROFILE
from quantum_lab_demo.virtual_lab.quantum_responses import (
    quantum_lab_response_registry,
)
from quantum_lab_demo.virtual_lab.wiring import quantum_wiring_config_profile
from quantum_lab_demo.workflows.fake_x_count_experiment import (
    X_COUNT,
    fake_x_count_capture,
    fake_x_count_scratch,
    fake_x_count_template,
)

from .demo_lab_experiment_testkit import (
    in_process_quantum_lab,
)


class _UnknownFetchFakeListDomainRuntime(FakeListDomainRuntime):
    @override
    def fetch(
        self,
        request: DomainFetchRequest,
    ) -> DomainFetchCandidate[FakeListRun]:
        return DomainFetchCandidate(
            receipt=DomainFetchReceipt(
                submission_key=request.submission_id.submission_key,
                job_id=request.job_id,
                status="unknown",
                problems=(
                    problem(
                        "fake_fetch_outcome_unknown",
                        "the fake target could not establish result availability",
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
    def __init__(self) -> None:
        super().__init__()
        self.submit_count = 0

    @override
    def submit(
        self,
        request: DomainSubmitRequest[SelectedFakeMeasurementRealization],
    ) -> DomainSubmitReceipt:
        self.submit_count += 1
        if self.submit_count == 2:
            raise RuntimeError("second target submission returned no evidence")
        return super().submit(request)


class _ConfiguredTestCompiler(QuantumLabCompiler):
    def __init__(self) -> None:
        super().__init__(
            target=configured_fake_list_target(quantum_wiring_config_profile()),
            runtime=FakeListDomainRuntime(),
            response_registry=quantum_lab_response_registry(),
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
    [program_call] = body.child_instances
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
    assert transform.semantic.parameters["discriminator"] == {
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
        journal = sqlite_execution_session(lab.project_root, run.id).journal

        assert run.manifest.status == "completed"
        assert tuple(point.coordinates["x_count"] for point in preview.points) == (
            0,
            1,
            2,
            4,
        )
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


def test_fake_x_count_compiler_absorbs_affine_point_input(
    tmp_path: Path,
) -> None:
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
    assert [record.coordinates["x_count"] for record in records] == [0, 1, 2]


def test_fake_x_count_compiler_projects_cartesian_axes(
    tmp_path: Path,
) -> None:
    auxiliary = sc.coordinate("auxiliary", sc.ScalarType(sc.IntType()))
    capture = fake_x_count_capture.instantiate("capture", x_count=X_COUNT)

    @sc.template(id="test.fake-x-count.cartesian", kind="fake_x_count")
    def cartesian_template() -> sc.ExperimentBody:
        return (
            sc.experiment(capture)
            .scan(
                sc.cartesian(
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

    run = lab.prepare(cartesian_template, system=_domain_only(compiler)).run()

    assert run.manifest.status == "completed"
    assert [
        (record.coordinates["x_count"], record.coordinates["auxiliary"])
        for record in run.data().measurements().dataset.records
    ] == [
        (0, 10),
        (0, 11),
        (0, 12),
        (1, 10),
        (1, 11),
        (1, 12),
        (2, 10),
        (2, 11),
        (2, 12),
    ]


def test_fake_x_count_scans_compiler_qubit_collection(tmp_path: Path) -> None:
    duration_type = sc.ScalarType(sc.QuantityType(unit="ns"))
    duration = sc.coordinate("x_duration", duration_type)
    capture = fake_x_count_capture(x_count=1)

    @sc.scratch(id="test.fake-x-count.compiler-scan", kind="fake_x_count")
    def compiler_scan() -> sc.ExperimentBody:
        return (
            sc.experiment(capture)
            .scan(
                sc.param_axis(
                    duration,
                    sc.parameter_lookup(
                        QUBIT_PARAMETER_TABLE,
                        key=q0_parameter_key(),
                        column="x_duration",
                        value_type=duration_type,
                    ),
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
    records = run.data().measurements().dataset.records

    assert run.manifest.status == "completed"
    assert [record.coordinates["x_duration"] for record in records] == [
        Quantity(4, "ns"),
        Quantity(6, "ns"),
    ]


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
    journal = sqlite_execution_session(lab.project_root, run.id).journal

    assert run.manifest.status == "completed"
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


@pytest.mark.parametrize(
    ("compiler", "error_type", "message"),
    [
        (_RaisingCompiler(), RuntimeError, "compiler implementation defect"),
        (
            _WrongResultCompiler(),
            TypeError,
            "domain compiler prepare must return PreparedDomainExecution",
        ),
    ],
)
def test_check_exposes_domain_prepare_contract_defects(
    compiler: object,
    error_type: type[Exception],
    message: str,
    tmp_path: Path,
) -> None:
    lab = in_process_quantum_lab(project_root=tmp_path)
    experiment = lab.prepare(
        fake_x_count_template,
        system=_domain_only(
            cast("DomainCompiler", compiler),
        ),
    )

    with pytest.raises(error_type, match=message):
        experiment.check()
    assert lab.runs() == ()


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
    assert set(recovery.details) == {
        "phase",
        "certainty",
        "invocation_id",
        "submission_key",
    }
    assert recovery.details["phase"] == "submit"
    assert recovery.details["certainty"] == "indeterminate"
    assert recovery.details["submission_key"]
    journal = sqlite_execution_session(
        lab.project_root,
        caught.value.run_id,
    ).journal
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
    target = replace(
        configured_fake_list_target(quantum_wiring_config_profile()),
        max_list_entries=2,
    )
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
    assert runtime.submit_count == 2
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
    assert set(recovery.details) == {
        "phase",
        "certainty",
        "invocation_id",
        "submission_key",
        "job_id",
    }
    assert recovery.details["phase"] == "fetch"
    assert recovery.details["certainty"] == "indeterminate"
    assert recovery.details["job_id"]
    journal = sqlite_execution_session(
        lab.project_root,
        caught.value.run_id,
    ).journal
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

    [persisted] = lab.runs()
    assert persisted.id == run.id
    assert persisted.manifest.status == "completed"


def _standard_domain_semantics(
    preview: sc.ExperimentPreview,
    journal: SQLiteTestExecutionJournal,
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
