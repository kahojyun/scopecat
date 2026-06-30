from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.errors import ValidationFailed
from scopecat.reporting import (
    generate_run_report,
)
from scopecat.runs import open_run_store
from scopecat.workflows import StartRunResult
from tests.support.records import assert_artifact_ref
from tests.support.reporting import (
    assert_report_boundary_records,
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


def test_generate_run_report_for_simulated_run_updates_manifest(
    tmp_path: Path,
) -> None:
    run_id = simulate(tmp_path)

    job, report = generate_run_report(run_id=run_id, workspace=tmp_path)

    run_dir = tmp_path / "runs" / run_id
    assert_report_boundary_records(tmp_path, run_id=run_id, job=job, report=report)
    assert (run_dir / "artifacts" / "run-report.md").is_file()
    assert job.status == "completed"
    assert job.input_refs[0:2] == ["manifest.json", "config-profile.snapshot.json"]
    assert report.config_source.status == "not_available"
    assert report.processing == []
    assert report.evaluation == []
    assert report.proposals == []
    assert report.run_comparisons == []

    report_markdown = (run_dir / "artifacts" / "run-report.md").read_text()
    assert "## ConfigRegistry Evidence" not in report_markdown
    assert report_markdown.endswith("\n")
    assert not report_markdown.endswith("\n\n")

    assert open_run_store(tmp_path).read_manifest(run_id).status == "completed"


def test_generate_run_report_includes_failed_processing_job(
    tmp_path: Path,
) -> None:
    run_id = simulate(tmp_path)
    (tmp_path / "runs" / run_id / "artifacts" / "raw-measurements.jsonl").unlink()
    with pytest.raises(ValidationFailed):
        execute_summary_stats_processing(run_id=run_id, workspace=tmp_path)

    job, report = generate_run_report(run_id=run_id, workspace=tmp_path)

    assert "processing/summary-stats.job.json" in job.input_refs
    assert "artifacts/summary-stats.json" not in job.input_refs
    assert len(report.processing) == 1
    processing = report.processing[0]
    assert processing.job_status == "failed"
    assert processing.result_artifact_ids == []
    assert processing.details == {}
    assert [diagnostic.code for diagnostic in processing.diagnostics] == [
        "missing_processing_input"
    ]
    report_markdown = (
        tmp_path / "runs" / run_id / "artifacts" / "run-report.md"
    ).read_text()
    assert "- Status: failed" in report_markdown
    assert "- Diagnostic: error missing_processing_input" in report_markdown


def test_generate_run_report_includes_failed_evaluation_job(
    tmp_path: Path,
) -> None:
    run_id = simulate(tmp_path)
    (tmp_path / "runs" / run_id / "artifacts" / "raw-measurements.jsonl").unlink()
    with pytest.raises(ValidationFailed):
        execute_best_signal_evaluation(run_id=run_id, workspace=tmp_path)

    job, report = generate_run_report(run_id=run_id, workspace=tmp_path)

    assert "evaluation/best-signal-proposal.job.json" in job.input_refs
    assert "artifacts/best-signal-evaluation.json" not in job.input_refs
    assert len(report.evaluation) == 1
    evaluation = report.evaluation[0]
    assert evaluation.job_status == "failed"
    assert evaluation.result_artifact_ids == []
    assert evaluation.details == {}
    assert [diagnostic.code for diagnostic in evaluation.diagnostics] == [
        "missing_evaluation_input"
    ]
    report_markdown = (
        tmp_path / "runs" / run_id / "artifacts" / "run-report.md"
    ).read_text()
    assert "- Status: failed" in report_markdown
    assert "- Diagnostic: error missing_evaluation_input" in report_markdown


def test_generate_run_report_for_full_local_workflow(
    tmp_path: Path,
) -> None:
    run_id = simulate_process_evaluate_and_review(tmp_path)

    job, report = generate_run_report(run_id=run_id, workspace=tmp_path)

    assert_report_boundary_records(tmp_path, run_id=run_id, job=job, report=report)
    assert report.config_source.status == "not_available"
    assert len(report.processing) == 1
    assert report.processing[0].details == {}
    assert report.processing[0].result_artifact_ids == ["summary-stats-result"]
    assert report.processing[0].summary_artifact_ids == ["summary-stats-summary"]
    assert [
        (artifact.id, artifact.kind, artifact.path)
        for artifact in report.processing[0].result_artifacts
    ] == [
        (
            "summary-stats-result",
            "test_summary_stats_result",
            "artifacts/summary-stats.json",
        )
    ]
    assert [
        (artifact.id, artifact.kind, artifact.path)
        for artifact in report.processing[0].summary_artifacts
    ] == [("summary-stats-summary", "summary", "artifacts/summary-stats.md")]
    assert len(report.evaluation) == 1
    assert report.evaluation[0].details == {}
    assert report.evaluation[0].result_artifact_ids == ["best-signal-evaluation-result"]
    assert report.evaluation[0].summary_artifact_ids == [
        "best-signal-evaluation-summary"
    ]
    assert [
        (artifact.id, artifact.kind, artifact.path)
        for artifact in report.evaluation[0].result_artifacts
    ] == [
        (
            "best-signal-evaluation-result",
            "test_best_signal_evaluation_result",
            "artifacts/best-signal-evaluation.json",
        )
    ]
    assert [
        (artifact.id, artifact.kind, artifact.path)
        for artifact in report.evaluation[0].summary_artifacts
    ] == [
        (
            "best-signal-evaluation-summary",
            "summary",
            "artifacts/best-signal-evaluation.md",
        )
    ]
    assert len(report.proposals) == 1
    proposal = report.proposals[0]
    assert proposal.state == "approved"
    assert proposal.operation_kind == "set_scalar"
    assert proposal.parameter_id == "drive_frequency"
    assert proposal.review.status == "reviewed"
    assert proposal.review.decision == "approved"
    assert proposal.review.reviewer == "operator"
    assert report.run_comparisons == []


def test_generate_run_report_includes_manual_analysis_artifact_refs(
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

    job, report = generate_run_report(run_id=run.id, workspace=tmp_path)

    assert "artifacts/analysis-report-review.json" in job.input_refs
    assert [
        (
            analysis.artifact_id,
            analysis.ref,
            analysis.output_kinds,
            analysis.guess_count,
            analysis.source_artifact_ids,
        )
        for analysis in report.analysis
    ] == [
        (
            "analysis-report-review",
            "artifacts/analysis-report-review.json",
            ["note", "external_ref", "guess"],
            1,
            ["raw-measurements"],
        )
    ]
    report_markdown = (
        tmp_path / "runs" / run.id / "artifacts" / "run-report.md"
    ).read_text()
    assert "## Analysis" in report_markdown
    assert "- Artifact: analysis-report-review" in report_markdown
    assert "- Source artifacts: raw-measurements" in report_markdown


def test_generate_run_report_includes_accept_generated_candidate_config_artifact(
    tmp_path: Path,
) -> None:
    run_id = simulate_evaluate_and_accept(tmp_path)

    _job, report = generate_run_report(run_id=run_id, workspace=tmp_path)

    assert report.config_source.status == "not_available"
    assert_artifact_ref(
        report.artifact_refs,
        "best-signal-proposal-candidate-config",
    )

    report_markdown = (
        tmp_path / "runs" / run_id / "artifacts" / "run-report.md"
    ).read_text()
    assert "best-signal-proposal-candidate-config" in report_markdown


def test_generate_run_report_marks_missing_optional_sections(
    tmp_path: Path,
) -> None:
    run_id = simulate(tmp_path)
    execute_best_signal_evaluation(run_id=run_id, workspace=tmp_path)

    _job, report = generate_run_report(run_id=run_id, workspace=tmp_path)

    assert report.processing == []
    assert report.config_source.status == "not_available"
    assert len(report.evaluation) == 1
    assert report.proposals[0].review.status == "not_reviewed"


def test_generate_run_report_includes_literal_config_registry_config_source(
    tmp_path: Path,
) -> None:
    run_id = config_registry_sourced_simulated_run(tmp_path, selector="literal")

    _job, report = generate_run_report(run_id=run_id, workspace=tmp_path)

    assert report.config_source.status == "available"
    assert report.config_source.source_kind == "config_registry"
    assert report.config_source.selector == "best-signal-proposal-candidate-config"
    assert report.config_source.entry_id == "best-signal-proposal-candidate-config"
    assert (
        report.config_source.config_ref == "config-registry/configs/"
        "best-signal-proposal-candidate-config.config-profile-snapshot.json"
    )
    assert report.config_source.active_state_ref is None
    assert report.config_source.active_record_id is None

    report_markdown = (
        tmp_path / "runs" / run_id / "artifacts" / "run-report.md"
    ).read_text()
    assert "## Config Source" in report_markdown
    assert "- Status: available" in report_markdown
    assert "- Selector: best-signal-proposal-candidate-config" in report_markdown


def test_generate_run_report_includes_active_config_registry_config_source(
    tmp_path: Path,
) -> None:
    run_id = config_registry_sourced_simulated_run(tmp_path, selector="active")

    _job, report = generate_run_report(run_id=run_id, workspace=tmp_path)

    assert report.config_source.status == "available"
    assert report.config_source.selector == "active"
    assert report.config_source.entry_id == "best-signal-proposal-candidate-config"
    assert (
        report.config_source.config_ref == "config-registry/configs/"
        "best-signal-proposal-candidate-config.config-profile-snapshot.json"
    )
    assert report.config_source.active_state_ref == "config-registry/active.json"
    assert report.config_source.active_record_id == "activation-000001"
