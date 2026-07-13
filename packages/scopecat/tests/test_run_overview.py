from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat.run_overview import build_run_overview
from scopecat.runs import open_run_store
from tests.support.run_overview import (
    config_registry_sourced_signal_run,
    load_config,
    run_signal_experiment,
    run_signal_experiment_with_active_candidate,
    run_signal_experiment_with_review,
)
from tests.support.signal_testkit import (
    execute_signal_run,
    execute_summary_stats_analysis,
)
from tests.support.workflow_fixtures import load_invocation


def test_build_run_overview_for_signal_run_does_not_update_manifest(
    tmp_path: Path,
) -> None:
    run_id = run_signal_experiment(tmp_path)

    overview = build_run_overview(run_id=run_id, workspace=tmp_path)

    assert overview.schema_version == "scopecat.run_overview.v4"
    assert overview.config_source is None
    assert overview.execution is not None
    assert overview.execution.status == "completed"
    assert overview.execution.point_count == 3
    assert overview.execution.measurement_count == 3
    assert overview.execution.instrument_ids == ["source-0"]
    assert overview.execution.runtime.completed_point_count == 3
    assert overview.execution.runtime.compute_evaluated_node_count == 0
    assert overview.execution.runtime.compute_reused_node_count == 0
    assert overview.execution.state.state_command_count == 3
    assert overview.execution.state.changed_field_count == 3
    assert len(overview.datasets) == 1
    dataset = overview.datasets[0]
    assert dataset.id == "raw-measurements"
    assert dataset.kind == "measurement_dataset"
    assert dataset.role == "raw"
    assert dataset.record_count == 3
    assert dataset.coordinate_ids == ["drive_frequency"]
    assert dataset.observable_ids == ["signal"]
    assert dataset.dimensions == {"point": 3}
    assert [(variable.id, variable.role) for variable in dataset.variables] == [
        ("drive_frequency", "coordinate"),
        ("signal", "observable"),
    ]
    assert overview.parameter_change_proposals == []
    assert overview.run_comparisons == []
    assert open_run_store(tmp_path).read_manifest(run_id).status == "completed"


def test_build_run_overview_for_full_local_workflow(
    tmp_path: Path,
) -> None:
    run_id = run_signal_experiment_with_review(tmp_path)

    overview = build_run_overview(run_id=run_id, workspace=tmp_path)

    assert overview.config_source is None
    assert [
        (
            analysis.id,
            analysis.output_kinds,
            analysis.parameter_change_proposal_count,
        )
        for analysis in overview.analysis_records
    ] == [
        (
            "analysis-best-signal-analysis",
            ["artifact", "artifact", "parameter_change_proposal"],
            1,
        ),
        ("analysis-summary-stats", ["artifact", "artifact"], 0),
    ]
    assert sorted(
        [
            (artifact.id, artifact.kind)
            for artifact in open_run_store(tmp_path).read_manifest(run_id).artifacts
            if artifact.id
            in {
                "summary-stats-result",
                "summary-stats-summary",
                "best-signal-analysis-result",
                "best-signal-analysis-summary",
            }
        ]
    ) == [
        (
            "best-signal-analysis-result",
            "test_best_signal_analysis_result",
        ),
        (
            "best-signal-analysis-summary",
            "summary",
        ),
        (
            "summary-stats-result",
            "test_summary_stats_result",
        ),
        (
            "summary-stats-summary",
            "summary",
        ),
    ]
    assert len(overview.parameter_change_proposals) == 1
    proposal = overview.parameter_change_proposals[0]
    assert proposal.deltas[0].parameter_id == "drive_frequency"
    assert proposal.decision_info.status == "reviewed"
    assert proposal.decision_info.decision == "approved"
    assert proposal.decision_info.actor == "operator"
    assert [event.decision for event in proposal.decision_info.history] == ["approved"]
    assert overview.run_comparisons == []


def test_build_run_overview_includes_manual_analysis_records(
    tmp_path: Path,
) -> None:
    manifest, _snapshot = execute_signal_run(
        config=load_config(),
        experiment=load_invocation(),
        workspace=tmp_path,
    )
    lab = sc.open(tmp_path, config=load_config())
    run = sc.Run(
        session=lab,
        manifest=manifest,
    )
    (
        run.analysis("report review")
        .note("Notebook inspection before next run.")
        .input("raw-measurements", expected_kind="measurement_dataset")
        .propose(
            "drive_frequency",
            sc.replace_scalar_parameter(
                "drive_frequency",
                sc.Quantity(5.1, "GHz"),
            ),
        )
        .save()
    )
    overview = build_run_overview(run_id=run.id, workspace=tmp_path)

    assert [
        (
            analysis.id,
            analysis.output_kinds,
            analysis.parameter_change_proposal_count,
            analysis.input_ids,
            analysis.output_ids,
        )
        for analysis in overview.analysis_records
    ] == [
        (
            "analysis-report-review",
            ["note", "parameter_change_proposal"],
            1,
            ["dataset:raw-measurements"],
            [],
        )
    ]
    assert len(overview.parameter_change_proposals) == 1
    proposal = overview.parameter_change_proposals[0]
    assert proposal.id == "drive_frequency"
    assert proposal.decision_info.status == "not_reviewed"
    assert proposal.decision_info.history == []


def test_build_run_overview_includes_activation_generated_candidate_config_record(
    tmp_path: Path,
) -> None:
    run_id = run_signal_experiment_with_active_candidate(tmp_path)

    overview = build_run_overview(run_id=run_id, workspace=tmp_path)
    manifest = open_run_store(tmp_path).read_manifest(run_id)

    assert overview.config_source is None
    assert any(
        record.id == "candidate-best-signal-analysis-drive_frequency-candidate-config"
        and record.kind == "candidate_config"
        for record in manifest.records
    )


def test_build_run_overview_marks_missing_optional_sections(
    tmp_path: Path,
) -> None:
    run_id = run_signal_experiment(tmp_path)
    execute_summary_stats_analysis(run_id=run_id, workspace=tmp_path)

    overview = build_run_overview(run_id=run_id, workspace=tmp_path)

    assert overview.config_source is None
    assert len(overview.analysis_records) == 1
    assert overview.parameter_change_proposals == []


def test_build_run_overview_includes_literal_config_registry_config_source(
    tmp_path: Path,
) -> None:
    run_id = config_registry_sourced_signal_run(tmp_path, selector="literal")

    overview = build_run_overview(run_id=run_id, workspace=tmp_path)

    assert overview.config_source is not None
    assert overview.config_source.kind == "config_registry"
    assert overview.config_source.selector == (
        "candidate-best-signal-analysis-candidate-config"
    )
    assert overview.config_source.entry_id == (
        "candidate-best-signal-analysis-candidate-config"
    )


def test_build_run_overview_includes_active_config_registry_config_source(
    tmp_path: Path,
) -> None:
    run_id = config_registry_sourced_signal_run(tmp_path, selector="active")

    overview = build_run_overview(run_id=run_id, workspace=tmp_path)

    assert overview.config_source is not None
    assert overview.config_source.selector == "active"
    assert overview.config_source.entry_id == (
        "candidate-best-signal-analysis-candidate-config"
    )
