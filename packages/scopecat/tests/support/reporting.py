from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat.config_registry import resolve_config_registry_config_source
from scopecat.experiments import ExperimentSpec
from scopecat.models.config import ConfigProfileSnapshot, load_config_profile
from scopecat.run_comparison import execute_run_comparison
from scopecat.workflows import register_and_activate_candidate_review
from tests.support.records import read_model
from tests.support.signal_testkit import (
    execute_best_signal_analysis,
    execute_signal_native_run,
    execute_summary_stats_analysis,
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


def _review_best_signal_analysis(
    tmp_path: Path,
    run_id: str,
) -> sc.CandidateConfigReview:
    lab = sc.open(tmp_path, config=load_config(), mode="native_simulate")
    analysis = execute_best_signal_analysis(run_id=run_id, workspace=tmp_path)
    analysis.save()
    return lab.review(
        analysis.candidate_config(reason=analysis.parameter_guesses[0].reason),
        note="looks good",
    )


def simulate_analyze_and_review(tmp_path: Path) -> str:
    run_id = simulate(tmp_path)
    execute_summary_stats_analysis(run_id=run_id, workspace=tmp_path)
    _review_best_signal_analysis(tmp_path, run_id)
    return run_id


def simulate_analyze_and_activate(tmp_path: Path) -> str:
    run_id = simulate(tmp_path)
    review = _review_best_signal_analysis(tmp_path, run_id)
    register_and_activate_candidate_review(
        review=review,
        workspace=tmp_path,
        entry_id="candidate-best-signal-analysis-candidate-config",
        registered_by="operator",
        operator="operator",
        note="ready to use",
    )
    return run_id


def config_registry_sourced_simulated_run(tmp_path: Path, *, selector: str) -> str:
    simulate_analyze_and_activate(tmp_path)
    source_selector = (
        "active"
        if selector == "active"
        else "candidate-best-signal-analysis-candidate-config"
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
    review = _review_best_signal_analysis(tmp_path, baseline_run_id)
    register_and_activate_candidate_review(
        review=review,
        workspace=tmp_path,
        entry_id="candidate-best-signal-analysis-candidate-config",
        registered_by="operator",
        operator="operator",
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
