from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import scopecat as sc
from scopecat.compiler.frontend.invocation import prepare_invocation
from scopecat.composition.embedded import (
    embedded_workspace_services,
    open_embedded_workspace,
)
from scopecat.config.profiles import load_config_profile
from scopecat.config.registry import (
    activate_config_registry_entry,
    current_config_registry_generation,
    load_config_registry_config,
    resolve_config_registry_config_source,
    rollback_config_registry,
)
from scopecat.config.resolution import register_and_activate_candidate_config
from scopecat.runs.service import start_run
from tests.testkit.paths import CORE_FIXTURE_DIR as SIGNAL_FIXTURE_DIR
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.signal_testkit import (
    BestSignalAnalysisStep,
    SummaryStatsAnalysisStep,
    execute_signal_run,
)
from tests.testkit.workflow_fixtures import load_invocation

Exercise = Callable[[Path], None]


def _load_fixture(fixture_dir: Path):
    return (
        load_config_profile(fixture_dir / "config-profile.json"),
        load_invocation(),
    )


def _load_signal_fixture():
    return _load_fixture(SIGNAL_FIXTURE_DIR)


def _start_signal_run(workspace: Path):
    config, experiment = _load_signal_fixture()
    services = embedded_workspace_services(workspace)
    return start_run(
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
        config=config,
        experiment=prepare_invocation(experiment),
        services=services,
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
    lab = open_embedded_workspace(workspace, config=config)
    run = lab.get_run(run_id)
    analysis = run.analyze(BestSignalAnalysisStep())
    analysis.save()
    candidate = analysis.candidate_config()
    lab.review_parameter_proposal(run, candidate.proposal_ids[0])
    return candidate


def exercise_preview(workspace: Path) -> None:
    config = load_config_profile(SIGNAL_FIXTURE_DIR / "config-profile.json")
    open_embedded_workspace(
        workspace,
        config=config,
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    ).prepare(load_invocation()).preview()


def exercise_signal_provider_run(workspace: Path) -> None:
    _execute_signal_run(workspace)


def exercise_workflow_pipeline(workspace: Path) -> None:
    run = _start_signal_run(workspace)
    config, _experiment = _load_signal_fixture()
    lab = open_embedded_workspace(workspace, config=config)
    run_handle = lab.get_run(run.run_id)
    run_handle.analyze(SummaryStatsAnalysisStep()).save()
    candidate = _candidate_best_signal(workspace, run.run_id)
    register_and_activate_candidate_config(
        candidate=candidate,
        services=embedded_workspace_services(workspace),
        entry_id="best-signal-analysis",
        registered_by="operator",
        operator="operator",
    )


def exercise_config_registry(workspace: Path) -> None:
    services = embedded_workspace_services(workspace)
    unit_of_work = services.config_registry
    config, experiment = _load_signal_fixture()
    manifest = execute_signal_run(
        config=config,
        experiment=experiment,
        workspace=workspace,
    )
    candidate = _candidate_best_signal(workspace, manifest.run_id)
    register_and_activate_candidate_config(
        candidate=candidate,
        services=services,
        entry_id="candidate-a",
        registered_by="operator",
        operator="operator",
    )
    active_config, active_source = resolve_config_registry_config_source(
        selector="active",
        unit_of_work=unit_of_work,
    )
    candidate_seed = execute_signal_run(
        config=active_config,
        experiment=experiment,
        workspace=workspace,
        config_source=active_source,
    )
    seed_candidate = _candidate_best_signal(workspace, candidate_seed.run_id)
    register_and_activate_candidate_config(
        candidate=seed_candidate,
        services=services,
        entry_id="candidate-b",
        registered_by="operator",
        operator="operator",
    )
    load_config_registry_config(entry_id="candidate-a", unit_of_work=unit_of_work)
    rollback_config_registry(
        unit_of_work=unit_of_work,
        operator="operator",
        expected_generation=current_config_registry_generation(
            unit_of_work=unit_of_work
        ),
    )
    activate_config_registry_entry(
        entry_id="candidate-b",
        unit_of_work=unit_of_work,
        operator="operator",
        expected_generation=current_config_registry_generation(
            unit_of_work=unit_of_work
        ),
    )
    rollback_config_registry(
        unit_of_work=unit_of_work,
        operator="operator",
        expected_generation=current_config_registry_generation(
            unit_of_work=unit_of_work
        ),
    )
    config_source_config, config_source = resolve_config_registry_config_source(
        selector="active",
        unit_of_work=unit_of_work,
    )
    execute_signal_run(
        config=config_source_config,
        experiment=experiment,
        workspace=workspace,
        config_source=config_source,
    )


def exercise_instrument_provider_workflow(workspace: Path) -> None:
    config, experiment = _load_signal_fixture()
    start_run(
        config=config,
        experiment=prepare_invocation(experiment),
        services=embedded_workspace_services(workspace),
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )


NO_LIVE_IMPORT_EXERCISES: tuple[Exercise, ...] = (
    exercise_preview,
    exercise_signal_provider_run,
    exercise_workflow_pipeline,
    exercise_config_registry,
    exercise_instrument_provider_workflow,
)
