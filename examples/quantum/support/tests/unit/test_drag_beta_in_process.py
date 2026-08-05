from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
import scopecat as sc
from scopecat import Quantity
from scopecat.config.registry import CandidateConfigRegistrySource
from scopecat.records.measurement import MeasurementScalar
from scopecat.records.parameter import TableParameterValue
from scopecat.sdk.domain import DomainBatchRequest

from quantum_lab_demo.compiler import QuantumLabCompiler
from quantum_lab_demo.virtual_lab.parameters import (
    DRAG_BETA_PARAMETER_COLUMN,
    QUBIT_PARAMETER_TABLE,
)
from quantum_lab_demo.workflows.drag_beta_analysis import (
    drag_beta_analysis,
)
from quantum_lab_demo.workflows.drag_beta_experiment import (
    PROBABILITY_0_RECORD_ID,
    PROBABILITY_1_RECORD_ID,
    drag_beta_experiment,
)

from .demo_lab_experiment_testkit import in_process_quantum_lab

_BETA_VALUES = tuple(Quantity(value, "ns") for value in (0.0, 0.25, 0.5, 0.75, 1.0))


def _entity_id(value: object) -> str:
    assert isinstance(value, sc.EntityRef)
    return value.id


def _quantity_in_unit(value: object, unit: str) -> float:
    assert isinstance(value, Quantity)
    return float(value.to(unit).value)


def _measurement_in_unit(value: object, unit: str) -> float:
    assert isinstance(value, MeasurementScalar)
    assert value.dtype in {"float64", "int64"}
    assert isinstance(value.value, int | float) and not isinstance(value.value, bool)
    assert value.unit is not None
    return float(Quantity(value.value, value.unit).to(unit).value)


def test_drag_beta_closes_measurement_analysis_publish_and_undo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compile_requests: list[DomainBatchRequest] = []
    compile_batch = QuantumLabCompiler.compile_batch

    def capture_compile_batch(
        compiler: QuantumLabCompiler,
        request: DomainBatchRequest,
    ):
        compile_requests.append(request)
        return compile_batch(compiler, request)

    monkeypatch.setattr(QuantumLabCompiler, "compile_batch", capture_compile_batch)
    lab = in_process_quantum_lab(project_root=tmp_path)
    source_run = lab.prepare(drag_beta_experiment).run()
    analysis = source_run.analyze(drag_beta_analysis())

    assert source_run.manifest.status == "completed"
    beta_and_compiler_tables = [
        (beta, rows)
        for request in compile_requests
        for beta, rows in zip(
            request.inputs.program_input("beta"),
            request.inputs.compiler_input(QUBIT_PARAMETER_TABLE),
            strict=True,
        )
    ]
    assert len(beta_and_compiler_tables) == 15
    for beta, table in beta_and_compiler_tables:
        rows = cast("tuple[dict[str, object], ...]", table)
        q0_row = next(row for row in rows if _entity_id(row["qubit"]) == "q0")
        assert q0_row[DRAG_BETA_PARAMETER_COLUMN] == beta
    assert {
        _quantity_in_unit(beta, "ns") for beta, _rows in beta_and_compiler_tables
    } == {0.0, 0.25, 0.5, 0.75, 1.0}

    records = source_run.measurements().records
    assert len(records) == 15
    assert all(
        _measurement_in_unit(record.observables[PROBABILITY_0_RECORD_ID], "ratio")
        + _measurement_in_unit(record.observables[PROBABILITY_1_RECORD_ID], "ratio")
        == pytest.approx(1.0)
        for record in records
    )
    assert analysis.step_id == drag_beta_analysis.id
    assert [selected.kind for selected in analysis.inputs] == ["measurement_dataset"]
    assert [output.kind for output in analysis.outputs] == [
        "table",
        "table",
        "figure",
        "parameter_change_proposal",
    ]

    [proposal] = analysis.parameter_proposals
    [delta] = proposal.deltas
    assert delta.parameter_id == QUBIT_PARAMETER_TABLE
    assert isinstance(delta.after, TableParameterValue)
    q0 = next(row for row in delta.after.rows if _entity_id(row["qubit"]) == "q0")
    fitted_beta = q0[DRAG_BETA_PARAMETER_COLUMN]
    assert isinstance(fitted_beta, Quantity)
    assert float(fitted_beta.to("ns").value) == pytest.approx(0.765)

    saved = analysis.save()
    candidate = analysis.candidate_config()
    baseline = lab.publish_config(
        source_run.config,
        entry_id="drag-beta-baseline",
        expected_generation=0,
    )
    assert baseline.activation is not None
    approval = lab.review_parameter_proposal(
        source_run,
        proposal.id,
        note="fit reviewed",
    )
    activated = lab.publish(
        candidate,
        entry_id="drag-beta-q0",
        expected_generation=baseline.activation.generation,
    )
    assert activated.activation is not None

    assert saved.record.id == "analysis-drag-beta-calibration"
    assert saved.inputs[0].kind == "measurement_dataset"
    assert approval.actor == "operator"
    assert isinstance(activated.entry.source, CandidateConfigRegistrySource)
    assert activated.entry.source.proposal_id == proposal.id

    active_preview = lab.prepare(drag_beta_experiment, config="active").preview()
    active_betas = sorted(
        {
            _quantity_in_unit(point.coordinates["beta"], "ns")
            for point in active_preview.points
        }
    )
    fitted_beta_ns = float(fitted_beta.to("ns").value)
    assert active_betas == pytest.approx(
        [fitted_beta_ns + offset for offset in (-0.5, -0.25, 0.0, 0.25, 0.5)]
    )

    restored = lab.undo(
        expected_generation=activated.activation.generation,
        note="restore baseline",
    )
    assert restored.activation is not None
    restored_preview = lab.prepare(drag_beta_experiment, config="active").preview()
    restored_betas = sorted(
        {
            _quantity_in_unit(point.coordinates["beta"], "ns")
            for point in restored_preview.points
        }
    )
    assert restored.activation.action == "undo"
    assert restored_betas == pytest.approx(
        [float(beta.to("ns").value) for beta in _BETA_VALUES]
    )
