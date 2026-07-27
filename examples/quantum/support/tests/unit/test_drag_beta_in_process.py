from __future__ import annotations

from pathlib import Path

import pytest
import scopecat as sc
from scopecat import Quantity
from scopecat.config.registry import CandidateConfigRegistrySource
from scopecat.records.parameter import TableParameterValue

from quantum_lab_demo.virtual_lab.parameters import (
    DRAG_BETA_PARAMETER_COLUMN,
    QUBIT_PARAMETER_TABLE,
)
from quantum_lab_demo.workflows.drag_beta_analysis import (
    drag_beta_analysis,
)
from quantum_lab_demo.workflows.drag_beta_experiment import (
    drag_beta_template,
)

from .demo_lab_experiment_testkit import in_process_quantum_lab

_BETA_VALUES = tuple(Quantity(value, "ns") for value in (0.0, 0.25, 0.5, 0.75, 1.0))


def _entity_id(value: object) -> str:
    assert isinstance(value, sc.EntityRef)
    return value.id


def _quantity_in_unit(value: object, unit: str) -> float:
    assert isinstance(value, Quantity)
    return float(value.to(unit).value)


def test_drag_beta_closes_measurement_analysis_activation_and_rollback(
    tmp_path: Path,
) -> None:
    lab = in_process_quantum_lab(project_root=tmp_path)
    source_run = lab.prepare(drag_beta_template).run()
    analysis = source_run.analyze(drag_beta_analysis())

    assert source_run.manifest.status == "completed"
    records = source_run.data().measurements().dataset.records
    assert len(records) == 15
    assert all(
        _quantity_in_unit(record.observables["probability_0"], "ratio")
        + _quantity_in_unit(record.observables["probability_1"], "ratio")
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
    baseline = lab.activate_config(
        source_run.config,
        entry_id="drag-beta-baseline",
        expected_generation=0,
    )
    approval = lab.review_parameter_proposal(
        source_run,
        proposal.id,
        note="fit reviewed",
    )
    activated = lab.activate(
        candidate,
        entry_id="drag-beta-q0",
        expected_generation=baseline.active_state.generation,
        activation_note="use reviewed DRAG beta",
    )

    assert saved.record.id == "analysis-drag-beta-calibration"
    assert saved.inputs[0].kind == "measurement_dataset"
    assert approval.actor == "operator"
    assert isinstance(activated.entry.source, CandidateConfigRegistrySource)
    assert activated.entry.source.proposal_id == proposal.id

    active_preview = lab.prepare(drag_beta_template, config="active").preview()
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

    restored = lab.rollback(
        expected_generation=activated.active_state.generation,
        note="restore baseline",
    )
    restored_preview = lab.prepare(drag_beta_template, config="active").preview()
    restored_betas = sorted(
        {
            _quantity_in_unit(point.coordinates["beta"], "ns")
            for point in restored_preview.points
        }
    )
    assert restored.activation.action == "rollback"
    assert restored_betas == pytest.approx(
        [float(beta.to("ns").value) for beta in _BETA_VALUES]
    )
