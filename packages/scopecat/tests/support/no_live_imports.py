from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from scopecat.config_registry import (
    activate_config_registry_entry,
    load_config_registry_config,
    resolve_config_registry_config_source,
    rollback_config_registry,
)
from scopecat.execution.dry_run import execute_dry_run
from scopecat.experiments import ExperimentSpec
from scopecat.models.config import load_config_profile
from scopecat.proposals import (
    accept_parameter_proposal,
    review_parameter_proposal,
)
from scopecat.reporting import build_run_overview
from scopecat.run_comparison import execute_run_comparison, review_run_comparison
from scopecat.workflows import (
    accept_proposal,
    compare_runs,
    describe_analysis_catalog,
    list_run_artifacts,
    list_runs,
    load_run,
    read_run_artifact_json,
    read_run_artifact_text,
    read_run_measurement_dataset,
    resolve_analysis_step,
    validate_config_profile,
)
from scopecat.workflows import (
    activate_config_entry as workflow_activate_config_entry,
)
from scopecat.workflows import (
    register_and_activate_config_profile as workflow_register_and_activate_config,
)
from scopecat.workflows import (
    review_run_comparison as workflow_review_run_comparison,
)
from scopecat.workflows import (
    rollback_config as workflow_rollback_config,
)
from scopecat.workflows._types import CalibrationRoutine, CandidateReviewPolicy
from scopecat.workflows.routines import run_calibration_routine
from scopecat.workflows.runs import (
    native_run_executor,
    run_mode_executor,
    start_native_run,
    start_run,
)
from scopecat.workflows.steps import (
    describe_calibration_routine,
    evaluate_run,
    process_run,
)
from tests.support.native_signal import TestSignalInstrumentProvider
from tests.support.records import read_model
from tests.support.signal_testkit import (
    BestSignalEvaluationStep,
    SummaryStatsProcessingStep,
    TestSignalAnalysisCatalog,
    TestSignalAnalysisStep,
    execute_best_signal_evaluation,
    execute_signal_native_run,
    execute_summary_stats_processing,
)

Exercise = Callable[[Path], None]

REPO_ROOT = Path(__file__).parents[4]
FIXTURE_ROOT = REPO_ROOT / "fixtures"
FIXTURE_DIR = FIXTURE_ROOT / "core"
SIMULATED_FIXTURE_DIR = FIXTURE_DIR / "simulated_scan"


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


def _execute_evaluated_signal_run(workspace: Path):
    manifest, simulated_run = _execute_signal_run(workspace)
    execute_best_signal_evaluation(run_id=manifest.run_id, workspace=workspace)
    return manifest, simulated_run


def exercise_dry_run(workspace: Path) -> None:
    config = load_config_profile(SIMULATED_FIXTURE_DIR / "config-profile.json")
    experiment = read_model(SIMULATED_FIXTURE_DIR / "experiment.json", ExperimentSpec)
    execute_dry_run(config=config, experiment=experiment, workspace=workspace)


def exercise_native_simulation(workspace: Path) -> None:
    _execute_signal_run(workspace)


def exercise_run_comparison(workspace: Path) -> None:
    baseline_manifest, _baseline_run = _execute_signal_run(workspace)
    candidate_manifest, _candidate_run = _execute_signal_run(workspace)
    execute_run_comparison(
        baseline_run_id=baseline_manifest.run_id,
        candidate_run_id=candidate_manifest.run_id,
        workspace=workspace,
    )
    review_run_comparison(
        run_id=baseline_manifest.run_id,
        selector=f"run-comparison-{candidate_manifest.run_id}-signal",
        workspace=workspace,
        state="accepted",
        reviewer="operator",
        note="accepted",
    )


def exercise_processing(workspace: Path) -> None:
    manifest, _simulated_run = _execute_signal_run(workspace)
    execute_summary_stats_processing(run_id=manifest.run_id, workspace=workspace)


def exercise_evaluation_and_proposal_review(workspace: Path) -> None:
    manifest, _simulated_run = _execute_evaluated_signal_run(workspace)
    review_parameter_proposal(
        run_id=manifest.run_id,
        selector="best-signal-proposal",
        workspace=workspace,
        state="approved",
        reviewer="operator",
    )


def exercise_accept_proposal(workspace: Path) -> None:
    manifest, _simulated_run = _execute_evaluated_signal_run(workspace)
    accept_parameter_proposal(
        run_id=manifest.run_id,
        selector="best-signal-proposal",
        workspace=workspace,
        reviewer="operator",
        operator="operator",
    )


def exercise_workflow_pipeline(workspace: Path) -> None:
    run = _start_signal_run(workspace)
    process_run(
        run_id=run.manifest.run_id,
        workspace=workspace,
        step=SummaryStatsProcessingStep(),
    )
    evaluate_run(
        run_id=run.manifest.run_id,
        workspace=workspace,
        step=BestSignalEvaluationStep(),
    )
    accept_proposal(
        run_id=run.manifest.run_id,
        selector="best-signal-proposal",
        workspace=workspace,
        reviewer="operator",
        operator="operator",
    )


def exercise_analysis_catalog(workspace: Path) -> None:
    del workspace
    catalog = TestSignalAnalysisCatalog()
    describe_analysis_catalog(catalog)
    resolve_analysis_step(
        catalog=catalog,
        step_id="best-signal-analysis",
        options={"input": "raw-measurements"},
    )


def exercise_provider_descriptors(workspace: Path) -> None:
    del workspace
    config, experiment = _load_simulated_fixture()
    describe_analysis_catalog(TestSignalAnalysisCatalog())
    TestSignalInstrumentProvider().describe()
    describe_calibration_routine(
        CalibrationRoutine(
            id="no-live-descriptor-routine",
            experiment=experiment,
            run_executor=run_mode_executor(
                "native_simulate",
                native_instrument_provider=TestSignalInstrumentProvider(),
            ),
            analysis_steps=(TestSignalAnalysisStep(),),
            review_candidate=CandidateReviewPolicy(
                reviewer="operator",
            ),
            metadata={"workspace_id": config.workspace_id},
        )
    )


def exercise_workflow_run_data_access(workspace: Path) -> None:
    run = _start_signal_run(workspace)
    list_runs(workspace=workspace)
    load_run(run_id=run.manifest.run_id, workspace=workspace)
    list_run_artifacts(run_id=run.manifest.run_id, workspace=workspace)
    read_run_artifact_text(
        run_id=run.manifest.run_id,
        selector="native-run-summary",
        workspace=workspace,
    )
    read_run_artifact_json(
        run_id=run.manifest.run_id,
        selector="native-run-snapshot",
        workspace=workspace,
    )
    read_run_measurement_dataset(run_id=run.manifest.run_id, workspace=workspace)


def exercise_calibration_routine(workspace: Path) -> None:
    _run_calibration_routine(workspace=workspace, entry_id=None)


def exercise_workflow_comparison(workspace: Path) -> None:
    baseline = _start_signal_run(workspace)
    candidate = _start_signal_run(workspace)
    comparison = compare_runs(
        baseline_run_id=baseline.manifest.run_id,
        candidate_run_id=candidate.manifest.run_id,
        workspace=workspace,
    )
    workflow_review_run_comparison(
        run_id=baseline.manifest.run_id,
        selector=comparison.result.comparison_id,
        workspace=workspace,
        state="accepted",
        reviewer="operator",
    )


def exercise_reporting(workspace: Path) -> None:
    manifest, _simulated_run = _execute_evaluated_signal_run(workspace)
    execute_summary_stats_processing(run_id=manifest.run_id, workspace=workspace)
    review_parameter_proposal(
        run_id=manifest.run_id,
        selector="best-signal-proposal",
        workspace=workspace,
        state="approved",
        reviewer="operator",
    )
    build_run_overview(run_id=manifest.run_id, workspace=workspace)


def exercise_config_registry(workspace: Path) -> None:
    config, experiment = _load_simulated_fixture()
    manifest, _simulated_run = execute_signal_native_run(
        config=config,
        experiment=experiment,
        workspace=workspace,
    )
    execute_best_signal_evaluation(run_id=manifest.run_id, workspace=workspace)
    accept_parameter_proposal(
        run_id=manifest.run_id,
        selector="best-signal-proposal",
        workspace=workspace,
        reviewer="operator",
        operator="operator",
        entry_id="candidate-a",
    )
    candidate_seed, _candidate_seed_run = execute_signal_native_run(
        config=config,
        experiment=experiment,
        workspace=workspace,
    )
    execute_best_signal_evaluation(run_id=candidate_seed.run_id, workspace=workspace)
    accept_parameter_proposal(
        run_id=candidate_seed.run_id,
        selector="best-signal-proposal",
        workspace=workspace,
        reviewer="operator",
        operator="operator",
        entry_id="candidate-b",
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


def exercise_config_workflows(workspace: Path) -> None:
    config = validate_config_profile(
        SIMULATED_FIXTURE_DIR / "config-profile.json"
    ).config
    first = workflow_register_and_activate_config(
        config=config,
        workspace=workspace,
        entry_id="seed-a",
        registered_by="operator",
        operator="operator",
    )
    workflow_register_and_activate_config(
        config=config,
        workspace=workspace,
        entry_id="seed-b",
        registered_by="operator",
        operator="operator",
    )
    workflow_activate_config_entry(
        entry_id=first.entry.id,
        workspace=workspace,
        operator="operator",
    )
    workflow_rollback_config(workspace=workspace, operator="operator")


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


def _run_calibration_routine(*, workspace: Path, entry_id: str | None):
    del entry_id
    config, experiment = _load_simulated_fixture()
    return run_calibration_routine(
        routine=CalibrationRoutine(
            id="no-live-routine",
            experiment=experiment,
            run_executor=run_mode_executor(
                "native_simulate",
                native_instrument_provider=TestSignalInstrumentProvider(),
            ),
            analysis_steps=(TestSignalAnalysisStep(),),
            review_candidate=CandidateReviewPolicy(
                reviewer="operator",
            ),
        ),
        config=config,
        workspace=workspace,
    )


NO_LIVE_IMPORT_EXERCISES: tuple[Exercise, ...] = (
    exercise_dry_run,
    exercise_native_simulation,
    exercise_run_comparison,
    exercise_processing,
    exercise_evaluation_and_proposal_review,
    exercise_accept_proposal,
    exercise_workflow_pipeline,
    exercise_analysis_catalog,
    exercise_provider_descriptors,
    exercise_workflow_run_data_access,
    exercise_calibration_routine,
    exercise_workflow_comparison,
    exercise_reporting,
    exercise_config_registry,
    exercise_config_workflows,
    exercise_native_instrument_provider_workflow,
)
