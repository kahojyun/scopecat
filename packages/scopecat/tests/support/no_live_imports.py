from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import scopecat as sc
from scopecat._workflows.config import register_and_activate_candidate_config
from scopecat._workflows.runs import preview_experiment, start_run
from scopecat.authoring._invocation_plan import prepare_invocation
from scopecat.config_profiles import load_config_profile
from scopecat.config_registry import (
    activate_config_registry_entry,
    current_config_registry_generation,
    load_config_registry_config,
    resolve_config_registry_config_source,
    rollback_config_registry,
)
from scopecat.run_comparison import execute_run_comparison, review_run_comparison
from scopecat.run_overview import build_run_overview
from tests.support.signal_instruments import TestSignalInstrumentProvider
from tests.support.signal_testkit import (
    BestSignalAnalysisStep,
    SummaryStatsAnalysisStep,
    execute_signal_run,
)
from tests.support.workflow_fixtures import load_invocation

Exercise = Callable[[Path], None]

REPO_ROOT = Path(__file__).parents[4]
FIXTURE_ROOT = REPO_ROOT / "fixtures"
SIGNAL_FIXTURE_DIR = FIXTURE_ROOT / "core" / "simple_scan"


def _load_fixture(fixture_dir: Path):
    return (
        load_config_profile(fixture_dir / "config-profile.json"),
        load_invocation(),
    )


def _load_signal_fixture():
    return _load_fixture(SIGNAL_FIXTURE_DIR)


def _start_signal_run(workspace: Path):
    config, experiment = _load_signal_fixture()
    return start_run(
        execution_backend=sc.PointInstrumentBackend(TestSignalInstrumentProvider()),
        config=config,
        experiment=prepare_invocation(experiment),
        workspace=workspace,
    )


def _execute_signal_run(workspace: Path):
    config, experiment = _load_signal_fixture()
    return execute_signal_run(
        config=config,
        experiment=experiment,
        workspace=workspace,
    )


def _candidate_best_signal(workspace: Path, run_id: str) -> sc.CandidateConfig:
    config, _experiment = _load_signal_fixture()
    lab = sc.open(workspace, config=config)
    run = lab.get_run(run_id)
    analysis = run.analyze(BestSignalAnalysisStep())
    analysis.save()
    candidate = analysis.candidate_config()
    lab.review_parameter_proposal(run, candidate.proposal_ids[0])
    return candidate


def exercise_preview(workspace: Path) -> None:
    config = load_config_profile(SIGNAL_FIXTURE_DIR / "config-profile.json")
    preview_experiment(
        config=config,
        execution_backend=sc.PointInstrumentBackend(TestSignalInstrumentProvider()),
        experiment=prepare_invocation(load_invocation()),
        workspace=workspace,
    )


def exercise_signal_provider_run(workspace: Path) -> None:
    _execute_signal_run(workspace)


def exercise_workflow_pipeline(workspace: Path) -> None:
    run = _start_signal_run(workspace)
    config, _experiment = _load_signal_fixture()
    lab = sc.open(workspace, config=config)
    run_handle = lab.get_run(run.run_id)
    run_handle.analyze(SummaryStatsAnalysisStep()).save()
    candidate = _candidate_best_signal(workspace, run.run_id)
    register_and_activate_candidate_config(
        candidate=candidate,
        workspace=workspace,
        entry_id="best-signal-analysis",
        registered_by="operator",
        operator="operator",
    )


def exercise_config_registry(workspace: Path) -> None:
    config, experiment = _load_signal_fixture()
    manifest, _snapshot = execute_signal_run(
        config=config,
        experiment=experiment,
        workspace=workspace,
    )
    candidate = _candidate_best_signal(workspace, manifest.run_id)
    register_and_activate_candidate_config(
        candidate=candidate,
        workspace=workspace,
        entry_id="candidate-a",
        registered_by="operator",
        operator="operator",
    )
    active_config, active_source = resolve_config_registry_config_source(
        selector="active",
        workspace=workspace,
    )
    candidate_seed, _snapshot = execute_signal_run(
        config=active_config,
        experiment=experiment,
        workspace=workspace,
        config_source=active_source,
    )
    seed_candidate = _candidate_best_signal(workspace, candidate_seed.run_id)
    register_and_activate_candidate_config(
        candidate=seed_candidate,
        workspace=workspace,
        entry_id="candidate-b",
        registered_by="operator",
        operator="operator",
    )
    load_config_registry_config(entry_id="candidate-a", workspace=workspace)
    rollback_config_registry(
        workspace=workspace,
        operator="operator",
        expected_generation=current_config_registry_generation(workspace=workspace),
    )
    activate_config_registry_entry(
        entry_id="candidate-b",
        workspace=workspace,
        operator="operator",
        expected_generation=current_config_registry_generation(workspace=workspace),
    )
    rollback_config_registry(
        workspace=workspace,
        operator="operator",
        expected_generation=current_config_registry_generation(workspace=workspace),
    )
    config_source_config, config_source = resolve_config_registry_config_source(
        selector="active",
        workspace=workspace,
    )
    candidate_manifest, _candidate_run = execute_signal_run(
        config=config_source_config,
        experiment=experiment,
        workspace=workspace,
        config_source=config_source,
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


def exercise_instrument_provider_workflow(workspace: Path) -> None:
    config, experiment = _load_signal_fixture()
    start_run(
        config=config,
        experiment=prepare_invocation(experiment),
        workspace=workspace,
        execution_backend=sc.PointInstrumentBackend(TestSignalInstrumentProvider()),
    )


NO_LIVE_IMPORT_EXERCISES: tuple[Exercise, ...] = (
    exercise_preview,
    exercise_signal_provider_run,
    exercise_workflow_pipeline,
    exercise_config_registry,
    exercise_instrument_provider_workflow,
)
