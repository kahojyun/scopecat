from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.errors import ValidationFailed
from scopecat.reporting import (
    build_run_overview,
    render_run_overview,
)
from scopecat.runs import open_run_store
from scopecat.workflows import StartRunResult
from tests.support.records import assert_artifact_ref
from tests.support.reporting import (
    assert_run_overview_not_persisted,
    config_registry_sourced_simulated_run,
    load_config,
    load_experiment,
    simulate,
    simulate_evaluate_and_accept,
    simulate_process_evaluate_and_review,
)
from tests.support.signal_testkit import (
    execute_best_signal_evaluation,
    execute_signal_native_run,
    execute_summary_stats_processing,
)


def test_build_run_overview_for_simulated_run_does_not_update_manifest(
    tmp_path: Path,
) -> None:
    run_id = simulate(tmp_path)

    overview = build_run_overview(run_id=run_id, workspace=tmp_path)

    assert_run_overview_not_persisted(tmp_path, run_id=run_id)
    assert overview.config_source.status == "not_available"
    assert overview.processing == []
    assert overview.evaluation == []
    assert overview.proposals == []
    assert overview.run_comparisons == []

    overview_markdown = render_run_overview(overview)
    assert "## ConfigRegistry Evidence" not in overview_markdown
    assert overview_markdown.endswith("\n")
    assert not overview_markdown.endswith("\n\n")

    assert open_run_store(tmp_path).read_manifest(run_id).status == "completed"


def test_build_run_overview_includes_failed_processing_job(
    tmp_path: Path,
) -> None:
    run_id = simulate(tmp_path)
    (tmp_path / "runs" / run_id / "artifacts" / "raw-measurements.jsonl").unlink()
    with pytest.raises(ValidationFailed):
        execute_summary_stats_processing(run_id=run_id, workspace=tmp_path)

    overview = build_run_overview(run_id=run_id, workspace=tmp_path)

    assert len(overview.processing) == 1
    processing = overview.processing[0]
    assert processing.job_status == "failed"
    assert processing.result_artifact_ids == []
    assert processing.details == {}
    assert [diagnostic.code for diagnostic in processing.diagnostics] == [
        "missing_processing_input"
    ]
    overview_markdown = render_run_overview(overview)
    assert "- Status: failed" in overview_markdown
    assert "- Diagnostic: error missing_processing_input" in overview_markdown


def test_build_run_overview_includes_failed_evaluation_job(
    tmp_path: Path,
) -> None:
    run_id = simulate(tmp_path)
    (tmp_path / "runs" / run_id / "artifacts" / "raw-measurements.jsonl").unlink()
    with pytest.raises(ValidationFailed):
        execute_best_signal_evaluation(run_id=run_id, workspace=tmp_path)

    overview = build_run_overview(run_id=run_id, workspace=tmp_path)

    assert len(overview.evaluation) == 1
    evaluation = overview.evaluation[0]
    assert evaluation.job_status == "failed"
    assert evaluation.result_artifact_ids == []
    assert evaluation.details == {}
    assert [diagnostic.code for diagnostic in evaluation.diagnostics] == [
        "missing_evaluation_input"
    ]
    overview_markdown = render_run_overview(overview)
    assert "- Status: failed" in overview_markdown
    assert "- Diagnostic: error missing_evaluation_input" in overview_markdown


def test_build_run_overview_for_full_local_workflow(
    tmp_path: Path,
) -> None:
    run_id = simulate_process_evaluate_and_review(tmp_path)

    overview = build_run_overview(run_id=run_id, workspace=tmp_path)

    assert_run_overview_not_persisted(tmp_path, run_id=run_id)
    assert overview.config_source.status == "not_available"
    assert len(overview.processing) == 1
    assert overview.processing[0].details == {}
    assert overview.processing[0].result_artifact_ids == ["summary-stats-result"]
    assert overview.processing[0].summary_artifact_ids == ["summary-stats-summary"]
    assert [
        (artifact.id, artifact.kind, artifact.path)
        for artifact in overview.processing[0].result_artifacts
    ] == [
        (
            "summary-stats-result",
            "test_summary_stats_result",
            "artifacts/summary-stats.json",
        )
    ]
    assert [
        (artifact.id, artifact.kind, artifact.path)
        for artifact in overview.processing[0].summary_artifacts
    ] == [("summary-stats-summary", "summary", "artifacts/summary-stats.md")]
    assert len(overview.evaluation) == 1
    assert overview.evaluation[0].details == {}
    assert overview.evaluation[0].result_artifact_ids == [
        "best-signal-evaluation-result"
    ]
    assert overview.evaluation[0].summary_artifact_ids == [
        "best-signal-evaluation-summary"
    ]
    assert [
        (artifact.id, artifact.kind, artifact.path)
        for artifact in overview.evaluation[0].result_artifacts
    ] == [
        (
            "best-signal-evaluation-result",
            "test_best_signal_evaluation_result",
            "artifacts/best-signal-evaluation.json",
        )
    ]
    assert [
        (artifact.id, artifact.kind, artifact.path)
        for artifact in overview.evaluation[0].summary_artifacts
    ] == [
        (
            "best-signal-evaluation-summary",
            "summary",
            "artifacts/best-signal-evaluation.md",
        )
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
        .artifact_ref("raw-measurements", expected_kind="measurement_dataset")
        .guess("drive_frequency", 5.0, unit="GHz")
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
            analysis.guess_count,
            analysis.source_artifact_ids,
            analysis.report_artifact_ids,
        )
        for analysis in overview.analysis_records
    ] == [
        (
            "analysis-report-review",
            "artifacts/analysis-report-review.json",
            ["note", "external_ref", "guess"],
            1,
            ["raw-measurements"],
            [],
        )
    ]
    overview_markdown = render_run_overview(overview)
    assert "## Analysis Records" in overview_markdown
    assert "- Artifact: analysis-report-review" in overview_markdown
    assert "- Source artifacts: raw-measurements" in overview_markdown


def test_build_run_overview_includes_accept_generated_candidate_config_artifact(
    tmp_path: Path,
) -> None:
    run_id = simulate_evaluate_and_accept(tmp_path)

    overview = build_run_overview(run_id=run_id, workspace=tmp_path)

    assert overview.config_source.status == "not_available"
    assert_artifact_ref(
        overview.artifact_refs,
        "best-signal-proposal-candidate-config",
    )

    overview_markdown = render_run_overview(overview)
    assert "best-signal-proposal-candidate-config" in overview_markdown


def test_build_run_overview_marks_missing_optional_sections(
    tmp_path: Path,
) -> None:
    run_id = simulate(tmp_path)
    execute_best_signal_evaluation(run_id=run_id, workspace=tmp_path)

    overview = build_run_overview(run_id=run_id, workspace=tmp_path)

    assert overview.processing == []
    assert overview.config_source.status == "not_available"
    assert len(overview.evaluation) == 1
    assert overview.proposals[0].review.status == "not_reviewed"


def test_build_run_overview_includes_literal_config_registry_config_source(
    tmp_path: Path,
) -> None:
    run_id = config_registry_sourced_simulated_run(tmp_path, selector="literal")

    overview = build_run_overview(run_id=run_id, workspace=tmp_path)

    assert overview.config_source.status == "available"
    assert overview.config_source.source_kind == "config_registry"
    assert overview.config_source.selector == "best-signal-proposal-candidate-config"
    assert overview.config_source.entry_id == "best-signal-proposal-candidate-config"
    assert (
        overview.config_source.config_ref == "config-registry/configs/"
        "best-signal-proposal-candidate-config.config-profile-snapshot.json"
    )
    assert overview.config_source.active_state_ref is None
    assert overview.config_source.active_record_id is None

    overview_markdown = render_run_overview(overview)
    assert "## Config Source" in overview_markdown
    assert "- Status: available" in overview_markdown
    assert "- Selector: best-signal-proposal-candidate-config" in overview_markdown


def test_build_run_overview_includes_active_config_registry_config_source(
    tmp_path: Path,
) -> None:
    run_id = config_registry_sourced_simulated_run(tmp_path, selector="active")

    overview = build_run_overview(run_id=run_id, workspace=tmp_path)

    assert overview.config_source.status == "available"
    assert overview.config_source.selector == "active"
    assert overview.config_source.entry_id == "best-signal-proposal-candidate-config"
    assert (
        overview.config_source.config_ref == "config-registry/configs/"
        "best-signal-proposal-candidate-config.config-profile-snapshot.json"
    )
    assert overview.config_source.active_state_ref == "config-registry/active.json"
    assert overview.config_source.active_record_id == "activation-000001"
