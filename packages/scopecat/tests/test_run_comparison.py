from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat.run_comparison import (
    RunComparisonJob,
    RunComparisonResult,
    execute_run_comparison,
)
from scopecat.runs import open_run_store
from scopecat.workflows import StartRunResult
from tests.support.records import (
    assert_artifact_ref,
    read_model,
)
from tests.support.run_comparison import (
    active_config_registry_simulated_run,
    load_experiment,
    load_simulated_config,
    simulate,
)
from tests.support.signal_testkit import execute_signal_native_run


def test_execute_run_comparison_writes_baseline_artifacts_and_manifest(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulate(tmp_path)
    candidate_run_id = simulate(tmp_path)
    candidate_manifest_path = tmp_path / "runs" / candidate_run_id / "manifest.json"
    candidate_manifest_before = candidate_manifest_path.read_text()

    job, result = execute_run_comparison(
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        workspace=tmp_path,
    )

    comparison_id = f"run-comparison-{candidate_run_id}-signal"
    baseline_run_dir = tmp_path / "runs" / baseline_run_id
    assert (baseline_run_dir / "comparisons" / f"{comparison_id}.job.json").is_file()
    assert (baseline_run_dir / "artifacts" / f"{comparison_id}.json").is_file()
    assert (baseline_run_dir / "artifacts" / f"{comparison_id}.md").is_file()
    stored_job = read_model(
        baseline_run_dir / "comparisons" / f"{comparison_id}.job.json",
        RunComparisonJob,
    )
    stored_result = read_model(
        baseline_run_dir / "artifacts" / f"{comparison_id}.json",
        RunComparisonResult,
    )
    assert stored_job == job
    assert stored_result == result
    assert stored_job.output_artifact_ids == [
        f"{comparison_id}-result",
        f"{comparison_id}-summary",
    ]
    assert [
        (artifact.id, artifact.kind, artifact.path)
        for artifact in stored_job.output_artifacts
    ] == [
        (
            f"{comparison_id}-result",
            "run_comparison_result",
            f"artifacts/{comparison_id}.json",
        ),
        (f"{comparison_id}-summary", "summary", f"artifacts/{comparison_id}.md"),
    ]
    assert stored_result.job_ref == f"comparisons/{comparison_id}.job.json"
    assert stored_result.result_ref == f"artifacts/{comparison_id}.json"
    assert stored_result.summary_ref == f"artifacts/{comparison_id}.md"
    assert [
        (artifact.id, artifact.kind, artifact.path)
        for artifact in stored_result.artifact_refs
    ] == [
        (
            f"{comparison_id}-result",
            "run_comparison_result",
            f"artifacts/{comparison_id}.json",
        ),
        (f"{comparison_id}-summary", "summary", f"artifacts/{comparison_id}.md"),
        (
            f"{comparison_id}-job",
            "run_comparison_job",
            f"comparisons/{comparison_id}.job.json",
        ),
    ]
    assert job.id == comparison_id
    assert result.comparison_id == comparison_id
    assert result.measurement_count == 3
    assert result.outcome == "unchanged"
    assert result.observable_id == "signal"
    assert result.baseline_peak_point_index == 1
    assert result.candidate_peak_point_index == 1
    assert result.peak_value_delta.value == 0.0
    assert result.peak_value_delta.unit == "ratio"
    assert result.mean_value_delta.value == 0.0
    assert len(result.points) == 3
    assert result.points[0].value_delta.value == 0.0
    assert result.baseline_config_source.status == "not_available"
    assert result.candidate_config_source.status == "not_available"

    baseline_manifest = open_run_store(tmp_path).read_manifest(baseline_run_id)
    assert_artifact_ref(
        baseline_manifest.artifact_refs,
        f"{comparison_id}-result",
        kind="run_comparison_result",
        path=result.result_ref,
    )
    assert_artifact_ref(
        baseline_manifest.artifact_refs,
        f"{comparison_id}-summary",
        kind="summary",
        path=result.summary_ref,
    )
    assert_artifact_ref(
        baseline_manifest.artifact_refs,
        f"{comparison_id}-job",
        kind="run_comparison_job",
        path=result.job_ref,
    )
    assert candidate_manifest_path.read_text() == candidate_manifest_before


def test_execute_run_comparison_includes_active_config_source(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulate(tmp_path)
    candidate_run_id = active_config_registry_simulated_run(
        baseline_run_id=baseline_run_id,
        tmp_path=tmp_path,
    )

    _job, result = execute_run_comparison(
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        workspace=tmp_path,
    )

    assert result.baseline_config_source.status == "not_available"
    assert result.candidate_config_source.status == "available"
    assert result.candidate_config_source.selector == "active"
    assert result.candidate_config_source.entry_id == (
        "best-signal-proposal-candidate-config"
    )
    assert result.candidate_config_source.active_state_ref == (
        "config-registry/active.json"
    )
    assert result.candidate_config_source.active_record_id == "activation-000001"


def test_execute_run_comparison_references_analysis_artifacts_by_id(
    tmp_path: Path,
) -> None:
    config = load_simulated_config()
    experiment = load_experiment()
    baseline_manifest, baseline_snapshot = execute_signal_native_run(
        config=config,
        experiment=experiment,
        workspace=tmp_path,
    )
    candidate_manifest, candidate_snapshot = execute_signal_native_run(
        config=config,
        experiment=experiment,
        workspace=tmp_path,
    )
    lab = sc.open(tmp_path, config=config, mode="native_simulate")
    baseline = sc.Run(
        session=lab,
        result=StartRunResult(manifest=baseline_manifest, snapshot=baseline_snapshot),
    )
    candidate = sc.Run(
        session=lab,
        result=StartRunResult(manifest=candidate_manifest, snapshot=candidate_snapshot),
    )
    baseline.analysis("baseline review").artifact_ref("raw-measurements").save()
    candidate.analysis("candidate review").artifact_ref("raw-measurements").save()

    job, result = execute_run_comparison(
        baseline_run_id=baseline.id,
        candidate_run_id=candidate.id,
        workspace=tmp_path,
    )

    assert result.baseline_analysis_artifact_ids == ["analysis-baseline-review"]
    assert result.candidate_analysis_artifact_ids == ["analysis-candidate-review"]
    assert job.baseline_input_artifact_ids == [
        "raw-measurements",
        "analysis-baseline-review",
    ]
    assert job.candidate_input_artifact_ids == [
        "raw-measurements",
        "analysis-candidate-review",
    ]
    summary = (
        tmp_path / "runs" / baseline.id / "artifacts" / f"{result.comparison_id}.md"
    ).read_text()
    assert "## Analysis Artifacts" in summary
    assert "- analysis-baseline-review" in summary
    assert "- analysis-candidate-review" in summary
