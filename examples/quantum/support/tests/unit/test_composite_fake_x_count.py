from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat._storage.local import LocalExecutionJournal
from scopecat._workflows.runs import load_run_plan

from quantum_lab_demo import quantum_lab
from quantum_lab_demo.reference_experiments import (
    FAKE_X_COUNT_CAPTURE_MODULE,
    FakeXCountDomainExecutionAdapter,
    fake_x_count_scratch_experiment,
)
from quantum_lab_demo.reference_experiments.fake_x_count_experiment import X_COUNT


def _mixed_fake_x_count_template() -> sc.TemplateBuilder:
    capture = FAKE_X_COUNT_CAPTURE_MODULE.instantiate("capture")
    peripheral_module = (
        sc.module("quantum_lab_demo.reference.fake_x_count.peripheral")
        .resource("readout", requires=("acquire_iq",))
        .bind_field(
            "readout",
            capability="acquire_iq",
            field="repetitions",
            value=sc.Quantity(value=32.0, unit="count"),
        )
        .product(
            "local_probability_0",
            resource="readout",
            capability="acquire_iq",
            product_key="probability_0",
            unit=None,
        )
        .build()
        .instantiate("peripheral")
    )
    return (
        sc.module("quantum_lab_demo.reference.fake_x_count.mixed.root")
        .use(capture, peripheral_module)
        .template(
            "quantum_lab_demo.reference.fake_x_count.mixed",
            kind="fake-x-count-mixed",
        )
        .experiment_id("fake-x-count-mixed")
        .scan(X_COUNT, (0, 1, 2, 4))
        .record_product(
            capture.products.integrated_iq_shots,
            record_id="integrated_iq_shots",
        )
        .record_product(
            capture.products.probability_0,
            record_id="probability_0",
        )
        .record_product(
            capture.products.probability_1,
            record_id="probability_1",
        )
        .record_product(
            peripheral_module.products.local_probability_0,
            record_id="local_probe",
        )
    )


def test_point_peripheral_surrounds_one_fused_fake_domain_job(
    tmp_path: Path,
) -> None:
    lab = quantum_lab(workspace=tmp_path)
    point = lab.execution_backend
    assert isinstance(point, sc.PointInstrumentBackend)
    adapter = FakeXCountDomainExecutionAdapter()
    backend = sc.CompositeExecutionBackend(
        point=point,
        domains=(sc.DomainProgramBackend(adapter),),
    )

    run = lab.prepare(
        _mixed_fake_x_count_template(),
        execution_backend=backend,
    ).run()
    plan = load_run_plan(run_id=run.id, workspace=lab.workspace)
    records = run.data().measurements().dataset.records
    journal = LocalExecutionJournal(lab.workspace, run_id=run.id).entries()

    assert run.manifest.status == "completed"
    assert adapter.runtime.physical_execution_count == 1
    assert [unit.kind for unit in plan.execution_units] == [
        "point_instrument",
        "domain_job",
    ]
    assert {record.id: record.producer_kind for record in plan.records} == {
        "integrated_iq_shots": "domain",
        "probability_0": "host_transform",
        "probability_1": "host_transform",
        "local_probe": "instrument",
    }
    assert len(records) == 4
    assert all(
        set(record.observables)
        == {
            "integrated_iq_shots",
            "probability_0",
            "probability_1",
            "local_probe",
        }
        for record in records
    )
    assert any(
        record.kind == "instrument_state_evidence" for record in run.manifest.records
    )

    stage_first_sequence = {
        stage: next(
            index for index, entry in enumerate(journal) if entry.stage == stage
        )
        for stage in ("apply_state", "domain_submit", "domain_fetch", "collect")
    }
    assert (
        stage_first_sequence["apply_state"]
        < stage_first_sequence["domain_submit"]
        < stage_first_sequence["domain_fetch"]
        < stage_first_sequence["collect"]
    )


def test_fused_list_and_one_entry_jobs_preserve_logical_records(
    tmp_path: Path,
) -> None:
    x_counts = (0, 1, 2, 4)
    fused_lab = quantum_lab(workspace=tmp_path / "fused")
    fused_adapter = FakeXCountDomainExecutionAdapter()
    fused_run = fused_lab.prepare(
        fake_x_count_scratch_experiment(fused_lab, x_counts=x_counts),
        execution_backend=sc.DomainProgramBackend(fused_adapter),
    ).run()
    fused_records = _logical_record_values(fused_run)

    point_records: dict[int, object] = {}
    physical_execution_count = 0
    for x_count in x_counts:
        point_lab = quantum_lab(workspace=tmp_path / f"point-{x_count}")
        point_adapter = FakeXCountDomainExecutionAdapter()
        point_run = point_lab.prepare(
            fake_x_count_scratch_experiment(
                point_lab,
                x_counts=(x_count,),
            ),
            execution_backend=sc.DomainProgramBackend(point_adapter),
        ).run()
        point_records.update(_logical_record_values(point_run))
        physical_execution_count += point_adapter.runtime.physical_execution_count

    assert fused_adapter.runtime.physical_execution_count == 1
    assert physical_execution_count == len(x_counts)
    assert point_records == fused_records


def _logical_record_values(run: sc.RunHandle) -> dict[int, object]:
    selected: dict[int, object] = {}
    for record in run.data().measurements().dataset.records:
        x_count = record.coordinates["x_count"]
        if type(x_count) is not int:
            raise AssertionError("fake x-count coordinate must remain an integer")
        selected[x_count] = record.model_dump(
            mode="json",
            include={"coordinates", "observables"},
        )
    return selected
