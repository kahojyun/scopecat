from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import scopecat as sc
from scopecat.config_registry import (
    activate_config_registry_entry,
    load_config_registry_config,
    resolve_config_registry_config_source,
    rollback_config_registry,
)
from scopecat.execution.dry_run import execute_dry_run
from scopecat.experiments import ExperimentSpec
from scopecat.models.config import load_config_profile
from scopecat.reporting import build_run_overview
from scopecat.run_comparison import execute_run_comparison, review_run_comparison
from scopecat.workflows import register_and_activate_candidate_review
from scopecat.workflows.runs import native_run_executor, start_native_run, start_run
from tests.support.native_signal import TestSignalInstrumentProvider
from tests.support.records import read_model
from tests.support.signal_testkit import (
    BestSignalAnalysisStep,
    SummaryStatsAnalysisStep,
    execute_signal_native_run,
)

Exercise = Callable[[Path], None]

REPO_ROOT = Path(__file__).parents[4]
FIXTURE_ROOT = REPO_ROOT / "fixtures"
SIMULATED_FIXTURE_DIR = FIXTURE_ROOT / "core" / "simulated_scan"


def _load_fixture(fixture_dir: Path):
    return (
        load_config_profile(fixture_dir / "config-profile.json"),
        read_model(fixture_dir / "experiment.json", ExperimentSpec),
    )


def _load_simulated_fixture():
    return _load_fixture(SIMULATED_FIXTURE_DIR)


def _start_signal_run(workspace: Path):
    config, experiment = _load_simulated_fixture()
    return start_run(
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
        config=config,
        experiment=experiment,
        workspace=workspace,
    )


def _execute_signal_run(workspace: Path):
    config, experiment = _load_simulated_fixture()
    return execute_signal_native_run(
        config=config,
        experiment=experiment,
        workspace=workspace,
    )


def _review_best_signal(workspace: Path, run_id: str) -> sc.CandidateConfigReview:
    config, _experiment = _load_simulated_fixture()
    lab = sc.open(workspace, config=config, mode="native_simulate")
    run = lab.get_run(run_id)
    analysis = run.analyze(BestSignalAnalysisStep())
    analysis.save()
    return lab.review(
        analysis.candidate_config(reason=analysis.parameter_proposals[0].reason),
        note="accepted",
    )


def exercise_dry_run(workspace: Path) -> None:
    config = load_config_profile(SIMULATED_FIXTURE_DIR / "config-profile.json")
    experiment = read_model(SIMULATED_FIXTURE_DIR / "experiment.json", ExperimentSpec)
    execute_dry_run(config=config, experiment=experiment, workspace=workspace)


def exercise_native_simulation(workspace: Path) -> None:
    _execute_signal_run(workspace)


def exercise_workflow_pipeline(workspace: Path) -> None:
    run = _start_signal_run(workspace)
    config, _experiment = _load_simulated_fixture()
    lab = sc.open(workspace, config=config, mode="native_simulate")
    run_handle = lab.get_run(run.manifest.run_id)
    run_handle.analyze(SummaryStatsAnalysisStep()).save()
    review = _review_best_signal(workspace, run.manifest.run_id)
    register_and_activate_candidate_review(
        review=review,
        workspace=workspace,
        entry_id="best-signal-analysis",
        registered_by="operator",
        operator="operator",
    )


def exercise_config_registry(workspace: Path) -> None:
    config, experiment = _load_simulated_fixture()
    manifest, _simulated_run = execute_signal_native_run(
        config=config,
        experiment=experiment,
        workspace=workspace,
    )
    review = _review_best_signal(workspace, manifest.run_id)
    register_and_activate_candidate_review(
        review=review,
        workspace=workspace,
        entry_id="candidate-a",
        registered_by="operator",
        operator="operator",
    )
    candidate_seed, _candidate_seed_run = execute_signal_native_run(
        config=config,
        experiment=experiment,
        workspace=workspace,
    )
    seed_review = _review_best_signal(workspace, candidate_seed.run_id)
    register_and_activate_candidate_review(
        review=seed_review,
        workspace=workspace,
        entry_id="candidate-b",
        registered_by="operator",
        operator="operator",
    )
    load_config_registry_config(entry_id="candidate-a", workspace=workspace)
    activate_config_registry_entry(
        entry_id="candidate-a",
        workspace=workspace,
        operator="operator",
    )
    activate_config_registry_entry(
        entry_id="candidate-b",
        workspace=workspace,
        operator="operator",
    )
    rollback_config_registry(workspace=workspace, operator="operator")
    config_source_config, _provenance = resolve_config_registry_config_source(
        selector="active",
        workspace=workspace,
    )
    candidate_manifest, _candidate_run = execute_signal_native_run(
        config=config_source_config,
        experiment=experiment,
        workspace=workspace,
    )
    execute_run_comparison(
        baseline_run_id=manifest.run_id,
        candidate_run_id=candidate_manifest.run_id,
        workspace=workspace,
    )
    review_run_comparison(
        run_id=manifest.run_id,
        selector=f"run-comparison-{candidate_manifest.run_id}-signal",
        workspace=workspace,
        state="accepted",
        reviewer="operator",
        note="accepted",
    )
    build_run_overview(run_id=manifest.run_id, workspace=workspace)
    build_run_overview(run_id=candidate_manifest.run_id, workspace=workspace)


def exercise_native_instrument_provider_workflow(workspace: Path) -> None:
    config, experiment = _load_simulated_fixture()
    provider = TestSignalInstrumentProvider()
    start_native_run(
        config=config,
        experiment=experiment,
        workspace=workspace / "start-native",
        instrument_provider=provider,
    )
    native_run_executor(provider).start(
        config=config,
        experiment=experiment,
        workspace=workspace / "executor",
    )


NO_LIVE_IMPORT_EXERCISES: tuple[Exercise, ...] = (
    exercise_dry_run,
    exercise_native_simulation,
    exercise_workflow_pipeline,
    exercise_config_registry,
    exercise_native_instrument_provider_workflow,
)
