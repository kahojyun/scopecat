from __future__ import annotations

from pathlib import Path

from scopecat.config_registry import resolve_config_registry_config_source
from scopecat.experiments import ExperimentSpec
from scopecat.models.config import ConfigProfileSnapshot, load_config_profile
from scopecat.proposals import accept_parameter_proposal, review_parameter_proposal
from scopecat.run_comparison import execute_run_comparison
from scopecat.runs import open_run_store
from tests.support.records import read_model
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


def assert_run_overview_not_persisted(tmp_path: Path, *, run_id: str) -> None:
    manifest = open_run_store(tmp_path).read_manifest(run_id)
    assert "run-report-result" not in {
        artifact.id for artifact in manifest.artifact_refs
    }
    assert "run-report-summary" not in {
        artifact.id for artifact in manifest.artifact_refs
    }
    assert "run-report-job" not in {artifact.id for artifact in manifest.artifact_refs}
    run_dir = tmp_path / "runs" / run_id
    assert not (run_dir / "artifacts" / "run-report.json").exists()
    assert not (run_dir / "artifacts" / "run-report.md").exists()
    assert not (run_dir / "reports" / "run-report.job.json").exists()
