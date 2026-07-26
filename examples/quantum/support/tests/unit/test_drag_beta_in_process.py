from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest
import scopecat as sc
from scopecat import Quantity
from scopecat.config.registry import CandidateConfigRegistrySource
from scopecat.records.parameter import TableParameterValue
from scopecat.records.run import ConfigRegistryRunConfigSource
from scopecat_quantum import authoring as quantum
from tests.testkit.runtime import sqlite_execution_session

import quantum_lab_demo.workflows.drag_beta_analysis as analysis_module
from quantum_lab_demo import quantum_lab_compiler
from quantum_lab_demo.targets.fake_list_mode import configured_fake_list_target
from quantum_lab_demo.virtual_lab.parameters import (
    DRAG_BETA_PARAMETER_COLUMN,
    QUBIT_PARAMETER_TABLE,
    q0_drag_beta_lookup,
)
from quantum_lab_demo.virtual_lab.responses.drag_beta import (
    synthetic_drag_beta_response,
)
from quantum_lab_demo.virtual_lab.wiring import quantum_wiring_config_profile
from quantum_lab_demo.workflows.drag_beta_analysis import (
    DRAG_BETA_PROPOSAL_ID,
    DragBetaFit,
    DragBetaFitAssessment,
    DragBetaObservation,
    analyze_drag_beta_run,
    assess_drag_beta_fit,
    fit_drag_beta,
)
from quantum_lab_demo.workflows.drag_beta_experiment import (
    AMPLIFICATION,
    DEFAULT_AMPLIFICATIONS,
    DEFAULT_BETAS,
    drag_beta_program,
    drag_beta_scratch_experiment,
    drag_beta_template,
)

from .demo_lab_experiment_testkit import (
    in_process_quantum_lab,
)


def _entity_id(value: object) -> str:
    assert isinstance(value, sc.EntityRef)
    return value.id


def _quantity_in_unit(value: object, unit: str) -> float:
    assert isinstance(value, Quantity)
    return float(value.to(unit).value)


def test_drag_beta_authors_one_mixed_program_for_both_scan_axes() -> None:
    declaration = drag_beta_program
    call = declaration(
        qubit="q0",
        amplification=AMPLIFICATION,
        beta=q0_drag_beta_lookup(),
    ).with_shots(64)
    [execution] = call.module_invocation.module.domain_executions
    program = execution.program

    assert declaration.id == "drag-beta-rough-calibration"
    assert [port.id for port in declaration.ports] == [
        "qubit",
        "amplification",
        "beta",
    ]
    assert tuple(result.id for result in declaration.results) == ("iq_shots",)
    assert program.dialect_id == "scopecat.quantum.program"
    assert isinstance(program.body, quantum.Program)
    assert program.body.id == declaration.id
    assert tuple(port.id for port in program.input_ports) == (
        "qubit",
        "amplification",
        "beta",
    )
    assert tuple(port.id for port in program.result_ports) == ("iq_shots",)
    assert tuple(name for name, _value in execution.input_bindings) == (
        "qubit",
        "amplification",
        "beta",
    )
    assert tuple(name for name, _value in execution.result_bindings) == ("iq_shots",)


def test_drag_beta_template_and_scratch_share_the_2d_point_model(
    tmp_path: Path,
) -> None:
    lab = in_process_quantum_lab(project_root=tmp_path)
    template_preview = lab.prepare(drag_beta_template).preview()
    scratch_preview = lab.prepare(drag_beta_scratch_experiment()).preview()

    assert template_preview.point_count == scratch_preview.point_count == 15
    assert (
        template_preview.coordinate_ids
        == scratch_preview.coordinate_ids
        == (
            "beta",
            "amplification",
        )
    )
    expected = [
        {"beta": beta, "amplification": amplification}
        for beta in DEFAULT_BETAS
        for amplification in DEFAULT_AMPLIFICATIONS
    ]
    assert [point.coordinates for point in template_preview.points] == expected
    assert [point.coordinates for point in scratch_preview.points] == expected


def test_drag_beta_in_process_analysis_authors_typed_native_proposal(
    tmp_path: Path,
) -> None:
    compiler = quantum_lab_compiler()
    lab = in_process_quantum_lab(project_root=tmp_path, compiler=compiler)
    experiment = lab.prepare(drag_beta_template)

    run = experiment.run()
    records = run.data().measurements().dataset.records
    for record in records:
        beta = record.coordinates["beta"]
        amplification = record.coordinates["amplification"]
        probability_0 = record.observables["probability_0"]
        probability_1 = record.observables["probability_1"]
        assert isinstance(beta, Quantity)
        assert type(amplification) is int
        assert isinstance(probability_0, Quantity)
        assert isinstance(probability_1, Quantity)
        assert probability_0.value + probability_1.value == pytest.approx(1.0)
    analysis = analyze_drag_beta_run(run)
    journal = sqlite_execution_session(lab.project_root, run.id).journal

    assert run.manifest.status == "completed"
    assert (
        sum(
            entry.stage == "domain_submit" and entry.state == "started"
            for entry in journal.entries()
        )
        == 1
    )
    assert len(records) == 15
    assert len(analysis.observations) == 15
    assert float(analysis.fit.beta_hat.to("ns").value) == pytest.approx(0.765)
    assert isinstance(analysis.assessment, DragBetaFitAssessment)
    assert analysis.assessment.eligible
    assert analysis.assessment.recommendation == "propose"
    assert analysis.assessment.score_kind == "heuristic"
    assert 0.0 <= analysis.assessment.quality_score <= 1.0
    assert analysis.assessment.observed_beta_span > 0.02
    assert analysis.assessment.fitted_beta_span > 0.02
    assert analysis.assessment.beta_signal_span > 0.02
    assert analysis.assessment.beta_signal_to_rmse > 3.0
    assert analysis.proposal_id == DRAG_BETA_PROPOSAL_ID
    assert isinstance(analysis.analysis, sc.Analysis)
    assert [output.kind for output in analysis.analysis.outputs] == [
        "table",
        "table",
        "figure",
        "parameter_change_proposal",
    ]

    [proposal] = analysis.analysis.parameter_proposals
    assert proposal.id == DRAG_BETA_PROPOSAL_ID
    assert proposal.source_run_id == run.id
    assert proposal.confidence == analysis.assessment.quality_score
    [delta] = proposal.deltas
    assert delta.parameter_id == QUBIT_PARAMETER_TABLE
    assert isinstance(delta.after, TableParameterValue)
    q0 = next(row for row in delta.after.rows if _entity_id(row["qubit"]) == "q0")
    assert q0[DRAG_BETA_PARAMETER_COLUMN] == analysis.fit.beta_hat

    saved = analysis.analysis.save()
    rebuilt = analyze_drag_beta_run(run)
    assert rebuilt.analysis.parameter_proposals[0].proposed_at != proposal.proposed_at
    rebuilt.analysis.save()

    assert saved.record.id == "analysis-drag-beta-calibration"
    assert [
        record.id
        for record in run.manifest.records
        if record.kind == "parameter_change_proposal"
    ] == [DRAG_BETA_PROPOSAL_ID]


def test_drag_beta_low_quality_fit_saves_evidence_without_a_proposal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiler = quantum_lab_compiler()
    lab = in_process_quantum_lab(project_root=tmp_path)
    run = lab.prepare(
        drag_beta_template,
        system=sc.ExperimentSystem(domain_compiler=compiler),
    ).run()
    original_fit = fit_drag_beta

    def low_quality_fit(
        observations: Sequence[DragBetaObservation],
    ) -> DragBetaFit:
        return replace(original_fit(observations), rmse=0.03)

    monkeypatch.setattr(analysis_module, "fit_drag_beta", low_quality_fit)

    result = analyze_drag_beta_run(run)
    saved = result.analysis.save()

    assert not result.assessment.eligible
    assert result.assessment.recommendation == "hold"
    assert result.assessment.failed_checks == (
        "rmse_above_limit",
        "beta_signal_to_rmse_below_limit",
    )
    assert result.proposal_id is None
    assert result.analysis.parameter_proposals == ()
    assert [output.kind for output in result.analysis.outputs] == [
        "table",
        "table",
        "figure",
    ]
    assert saved.record.id == "analysis-drag-beta-calibration"
    assert not any(
        record.kind == "parameter_change_proposal" for record in run.manifest.records
    )


def test_drag_beta_assessment_rejects_amplification_offset_without_beta_signal() -> (
    None
):
    observations = tuple(
        DragBetaObservation(
            beta=beta,
            amplification=amplification,
            p1=(
                0.04
                + amplification**2
                * (0.015 + 1e-6 * (float(beta.to("ns").value) - 0.75) ** 2)
            ),
        )
        for amplification in DEFAULT_AMPLIFICATIONS
        for beta in DEFAULT_BETAS
    )

    fit = fit_drag_beta(observations)
    assessment = assess_drag_beta_fit(fit, observations)

    assert (
        max(observation.p1 for observation in observations)
        - min(observation.p1 for observation in observations)
        > 0.1
    )
    assert assessment.observed_beta_span < 1e-5
    assert assessment.fitted_beta_span < 1e-5
    assert assessment.beta_signal_span < 1e-5
    assert not assessment.eligible
    assert "beta_signal_span_below_limit" in assessment.failed_checks


def test_synthetic_joint_quadratic_recovers_beta_optimum() -> None:
    beta_values = tuple(Quantity(value, "ns") for value in (0.0, 0.5, 0.75, 1.0, 1.5))
    observations = tuple(
        DragBetaObservation(
            beta=beta,
            amplification=amplification,
            p1=synthetic_drag_beta_response(beta, amplification=amplification),
        )
        for amplification in (1, 2, 3)
        for beta in beta_values
    )

    fit = fit_drag_beta(observations)

    assert synthetic_drag_beta_response(
        Quantity(1.25, "ns"),
        amplification=2,
    ) == pytest.approx(0.048)
    assert float(fit.beta_hat.to("ns").value) == pytest.approx(0.75)
    assert fit.baseline == pytest.approx(0.04)
    assert fit.quadratic == pytest.approx(0.008)
    assert fit.linear == pytest.approx(-0.012)
    assert fit.scaled_offset == pytest.approx(0.0045)
    assert fit.rmse < 1e-14

    with pytest.raises(ValueError, match=r"must lie in \[0, 1\]"):
        DragBetaObservation(
            beta=Quantity(0.75, "ns"),
            amplification=1,
            p1=1.01,
        )


def test_drag_beta_approve_activate_active_replay_and_rollback(
    tmp_path: Path,
) -> None:
    lab = in_process_quantum_lab(project_root=tmp_path)
    source_compiler = quantum_lab_compiler()
    source_run = lab.prepare(
        drag_beta_template,
        system=sc.ExperimentSystem(domain_compiler=source_compiler),
    ).run()
    result = analyze_drag_beta_run(source_run)
    result.analysis.save()
    candidate = result.analysis.candidate_config()
    assert result.proposal_id is not None

    baseline = lab.activate_config(
        source_run.config,
        entry_id="drag-beta-baseline",
        expected_generation=0,
    )
    approved = lab.review_parameter_proposal(
        source_run,
        result.proposal_id,
        note="fit evidence reviewed",
    )
    activated = lab.activate(
        candidate,
        entry_id="drag-beta-q0",
        expected_generation=baseline.active_state.generation,
        activation_note="use reviewed DRAG beta",
    )
    active_compiler = quantum_lab_compiler()
    active_experiment = lab.prepare(
        drag_beta_template,
        config="active",
        system=sc.ExperimentSystem(domain_compiler=active_compiler),
    )
    active_preview = active_experiment.preview()
    active_run = active_experiment.run()

    active_betas = sorted(
        {
            _quantity_in_unit(point.coordinates["beta"], "ns")
            for point in active_preview.points
        }
    )
    fitted_beta = float(result.fit.beta_hat.to("ns").value)
    assert approved.actor == "operator"
    assert activated.active_state.generation == 2
    assert isinstance(activated.entry.source, CandidateConfigRegistrySource)
    proposal_evidence = activated.entry.source.proposal_evidence
    assert proposal_evidence.proposal_id == result.proposal_id
    assert proposal_evidence.approval_record_id == f"{result.proposal_id}-approval"
    assert proposal_evidence.proposal_record_content_hash.startswith("sha256:")
    assert proposal_evidence.approval_record_content_hash.startswith("sha256:")
    assert activated.entry.source.proposal_evidence
    assert activated.entry.source.base_config_content_hash.startswith("sha256:")
    assert active_betas == pytest.approx(
        [fitted_beta + offset for offset in (-0.5, -0.25, 0.0, 0.25, 0.5)]
    )
    active_source = active_run.manifest.config_source
    assert isinstance(active_source, ConfigRegistryRunConfigSource)
    assert active_source.entry_id == activated.entry.id
    assert active_source.registry_generation == 2

    restored = lab.rollback(
        expected_generation=activated.active_state.generation,
        note="restore baseline after active-config provenance replay",
    )
    restored_preview = lab.prepare(
        drag_beta_template,
        config="active",
        system=sc.ExperimentSystem(domain_compiler=quantum_lab_compiler()),
    ).preview()
    restored_betas = sorted(
        {
            _quantity_in_unit(point.coordinates["beta"], "ns")
            for point in restored_preview.points
        }
    )

    assert restored.active_state.generation == 3
    assert restored.active_state.active_entry_id == baseline.entry.id
    assert restored.activation.action == "rollback"
    assert restored_betas == pytest.approx(
        [float(beta.to("ns").value) for beta in DEFAULT_BETAS]
    )


def test_drag_beta_response_remains_batch_local(tmp_path: Path) -> None:
    target = replace(
        configured_fake_list_target(quantum_wiring_config_profile()),
        max_list_entries=4,
    )
    compiler = quantum_lab_compiler(target=target)
    lab = in_process_quantum_lab(project_root=tmp_path, compiler=compiler)

    run = lab.prepare(drag_beta_template).run()
    analysis = analyze_drag_beta_run(run)
    journal = sqlite_execution_session(lab.project_root, run.id).journal

    assert run.manifest.status == "completed"
    assert len(run.data().measurements().dataset.records) == 15
    assert (
        sum(
            entry.stage == "domain_submit" and entry.state == "started"
            for entry in journal.entries()
        )
        == 5
    )
    assert float(analysis.fit.beta_hat.to("ns").value) == pytest.approx(0.765)
    assert analysis.assessment.eligible
    assert analysis.proposal_id == DRAG_BETA_PROPOSAL_ID
