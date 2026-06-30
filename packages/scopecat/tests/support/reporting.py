from __future__ import annotations

from pathlib import Path

from scopecat.config_registry import resolve_config_registry_config_source
from scopecat.experiments import ExperimentSpec
from scopecat.models.config import ConfigProfileSnapshot, load_config_profile
from scopecat.proposals import accept_parameter_proposal, review_parameter_proposal
from scopecat.reporting import (
    RUN_REPORT_JOB_REF,
    RUN_REPORT_RESULT_REF,
    RUN_REPORT_SUMMARY_REF,
    ReportJob,
    RunReport,
)
from scopecat.run_comparison import execute_run_comparison
from scopecat.runs import open_run_store
from tests.support.records import assert_artifact_ref, read_model
from tests.support.signal_testkit import (
    execute_best_signal_evaluation,
    execute_signal_native_run,
    execute_summary_stats_processing,
)

EXAMPLE_DIR = Path(__file__).parents[4] / "fixtures" / "core" / "simulated_scan"


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXAMPLE_DIR / "config-profile.json")


def load_experiment() -> ExperimentSpec:
    return read_model(EXAMPLE_DIR / "experiment.json", ExperimentSpec)


def simulate(tmp_path: Path) -> str:
    manifest, _simulated_run = execute_signal_native_run(
        config=load_config(),
        experiment=load_experiment(),
        workspace=tmp_path,
    )
    return manifest.run_id


def simulate_process_evaluate_and_review(tmp_path: Path) -> str:
    run_id = simulate(tmp_path)
    execute_summary_stats_processing(run_id=run_id, workspace=tmp_path)
    execute_best_signal_evaluation(run_id=run_id, workspace=tmp_path)
    review_parameter_proposal(
        run_id=run_id,
        selector="best-signal-proposal",
        workspace=tmp_path,
        state="approved",
        reviewer="operator",
        note="looks good",
    )
    return run_id


def simulate_evaluate_and_accept(tmp_path: Path) -> str:
    run_id = simulate(tmp_path)
    execute_best_signal_evaluation(run_id=run_id, workspace=tmp_path)
    accept_parameter_proposal(
        run_id=run_id,
        selector="best-signal-proposal",
        workspace=tmp_path,
        reviewer="operator",
        operator="operator",
        entry_id="best-signal-proposal-candidate-config",
        note="ready to use",
    )
    return run_id


def config_registry_sourced_simulated_run(tmp_path: Path, *, selector: str) -> str:
    simulate_evaluate_and_accept(tmp_path)
    source_selector = (
        "active" if selector == "active" else "best-signal-proposal-candidate-config"
    )

    config, _provenance = resolve_config_registry_config_source(
        selector=source_selector,
        workspace=tmp_path,
    )
    manifest, _snapshot = execute_signal_native_run(
        config=config,
        experiment=load_experiment(),
        workspace=tmp_path,
    )
    return manifest.run_id


def simulated_run_with_active_candidate_comparison(tmp_path: Path) -> str:
    baseline_run_id = simulate(tmp_path)
    execute_best_signal_evaluation(run_id=baseline_run_id, workspace=tmp_path)
    accept_parameter_proposal(
        run_id=baseline_run_id,
        selector="best-signal-proposal",
        workspace=tmp_path,
        reviewer="operator",
        operator="operator",
        entry_id="best-signal-proposal-candidate-config",
        note="ready to use",
    )
    config, _provenance = resolve_config_registry_config_source(
        selector="active",
        workspace=tmp_path,
    )
    candidate_manifest, _snapshot = execute_signal_native_run(
        config=config,
        experiment=load_experiment(),
        workspace=tmp_path,
    )
    execute_run_comparison(
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_manifest.run_id,
        workspace=tmp_path,
    )
    return baseline_run_id


def assert_report_boundary_records(
    tmp_path: Path, *, run_id: str, job: ReportJob, report: RunReport
) -> None:
    run_dir = tmp_path / "runs" / run_id

    persisted_job = read_model(run_dir / RUN_REPORT_JOB_REF, ReportJob)
    persisted_report = read_model(run_dir / RUN_REPORT_RESULT_REF, RunReport)

    assert persisted_job == job
    assert persisted_report == report
    assert persisted_job.output_refs == [
        RUN_REPORT_RESULT_REF,
        RUN_REPORT_SUMMARY_REF,
    ]

    manifest = open_run_store(tmp_path).read_manifest(run_id)
    assert_artifact_ref(
        manifest.artifact_refs,
        "run-report-result",
        kind="run_report",
        path=RUN_REPORT_RESULT_REF,
    )
    assert_artifact_ref(
        manifest.artifact_refs,
        "run-report-summary",
        kind="summary",
        path=RUN_REPORT_SUMMARY_REF,
    )
    assert_artifact_ref(
        manifest.artifact_refs,
        "run-report-job",
        kind="report_job",
        path=RUN_REPORT_JOB_REF,
    )
