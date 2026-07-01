from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat.run_overview import build_run_overview
from scopecat.runs import open_run_store
from scopecat.workflows import StartRunResult
from tests.support.records import assert_artifact_ref
from tests.support.run_overview import (
    config_registry_sourced_simulated_run,
    load_config,
    load_experiment,
    simulate,
    simulate_analyze_and_activate,
    simulate_analyze_and_review,
)
from tests.support.signal_testkit import (
    execute_signal_native_run,
    execute_summary_stats_analysis,
)


def test_build_run_overview_for_simulated_run_does_not_update_manifest(
    tmp_path: Path,
) -> None:
    run_id = simulate(tmp_path)

    overview = build_run_overview(run_id=run_id, workspace=tmp_path)

    assert overview.config_source.status == "not_available"
    assert overview.proposals == []
    assert overview.run_comparisons == []
    assert open_run_store(tmp_path).read_manifest(run_id).status == "completed"


def test_build_run_overview_for_full_local_workflow(
    tmp_path: Path,
) -> None:
    run_id = simulate_analyze_and_review(tmp_path)

    overview = build_run_overview(run_id=run_id, workspace=tmp_path)

    assert overview.config_source.status == "not_available"
    assert [
        (analysis.artifact_id, analysis.output_kinds, analysis.proposal_count)
        for analysis in overview.analysis_records
    ] == [
        (
            "analysis-best-signal-analysis",
            ["artifact", "artifact", "proposal"],
            1,
        ),
        ("analysis-summary-stats", ["artifact", "artifact"], 0),
    ]
    assert sorted(
        [
            (artifact.id, artifact.kind, artifact.path)
            for artifact in overview.artifact_refs
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
            "artifacts/best-signal-analysis.json",
        ),
        (
            "best-signal-analysis-summary",
            "summary",
            "artifacts/best-signal-analysis.md",
        ),
        (
            "summary-stats-result",
            "test_summary_stats_result",
            "artifacts/summary-stats.json",
        ),
        (
            "summary-stats-summary",
            "summary",
            "artifacts/summary-stats.md",
        ),
    ]
    assert len(overview.proposals) == 1
    proposal = overview.proposals[0]
    assert proposal.state == "approved"
    assert proposal.operation_kind == "set_scalar"
    assert proposal.parameter_id == "drive_frequency"
    assert proposal.review.status == "reviewed"
    assert proposal.review.decision == "approved"
    assert proposal.review.reviewer == "operator"
    assert overview.run_comparisons == []


def test_build_run_overview_includes_manual_analysis_artifact_refs(
    tmp_path: Path,
) -> None:
    manifest, snapshot = execute_signal_native_run(
        config=load_config(),
        experiment=load_experiment(),
        workspace=tmp_path,
    )
    lab = sc.open(tmp_path, config=load_config(), mode="native_simulate")
    run = sc.Run(
        session=lab,
        result=StartRunResult(manifest=manifest, snapshot=snapshot),
    )
    (
        run.analysis("report review")
        .note("Notebook inspection before next run.")
        .input("raw-measurements", expected_kind="measurement_dataset")
        .propose("drive_frequency", 5.0, unit="GHz")
        .save()
    )
    analysis_artifact = run.data().artifact("analysis-report-review")
    assert analysis_artifact.metadata["source_artifact_ids"] == ["raw-measurements"]

    overview = build_run_overview(run_id=run.id, workspace=tmp_path)

    assert [
        (
            analysis.artifact_id,
            analysis.ref,
            analysis.output_kinds,
            analysis.proposal_count,
            analysis.source_artifact_ids,
            analysis.output_artifact_ids,
        )
        for analysis in overview.analysis_records
    ] == [
        (
            "analysis-report-review",
            "artifacts/analysis-report-review.json",
            ["note", "proposal"],
            1,
            ["raw-measurements"],
            [],
        )
    ]


def test_build_run_overview_includes_accept_generated_candidate_config_artifact(
    tmp_path: Path,
) -> None:
    run_id = simulate_analyze_and_activate(tmp_path)

    overview = build_run_overview(run_id=run_id, workspace=tmp_path)

    assert overview.config_source.status == "not_available"
    assert_artifact_ref(
        overview.artifact_refs,
        "candidate-best-signal-analysis-candidate-config",
    )


def test_build_run_overview_marks_missing_optional_sections(
    tmp_path: Path,
) -> None:
    run_id = simulate(tmp_path)
    execute_summary_stats_analysis(run_id=run_id, workspace=tmp_path)

    overview = build_run_overview(run_id=run_id, workspace=tmp_path)

    assert overview.config_source.status == "not_available"
    assert len(overview.analysis_records) == 1
    assert overview.proposals == []


def test_build_run_overview_includes_literal_config_registry_config_source(
    tmp_path: Path,
) -> None:
    run_id = config_registry_sourced_simulated_run(tmp_path, selector="literal")

    overview = build_run_overview(run_id=run_id, workspace=tmp_path)

    assert overview.config_source.status == "available"
    assert overview.config_source.source_kind == "config_registry"
    assert overview.config_source.selector == (
        "candidate-best-signal-analysis-candidate-config"
    )
    assert overview.config_source.entry_id == (
        "candidate-best-signal-analysis-candidate-config"
    )
    assert (
        overview.config_source.config_ref == "config-registry/configs/"
        "candidate-best-signal-analysis-candidate-config.config-profile-snapshot.json"
    )
    assert overview.config_source.active_state_ref is None
    assert overview.config_source.active_record_id is None


def test_build_run_overview_includes_active_config_registry_config_source(
    tmp_path: Path,
) -> None:
    run_id = config_registry_sourced_simulated_run(tmp_path, selector="active")

    overview = build_run_overview(run_id=run_id, workspace=tmp_path)

    assert overview.config_source.status == "available"
    assert overview.config_source.selector == "active"
    assert overview.config_source.entry_id == (
        "candidate-best-signal-analysis-candidate-config"
    )
    assert (
        overview.config_source.config_ref == "config-registry/configs/"
        "candidate-best-signal-analysis-candidate-config.config-profile-snapshot.json"
    )
    assert overview.config_source.active_state_ref == "config-registry/active.json"
    assert overview.config_source.active_record_id == "activation-000001"
