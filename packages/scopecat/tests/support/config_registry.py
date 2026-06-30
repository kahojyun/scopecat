from __future__ import annotations

from pathlib import Path

from scopecat.experiments import ExperimentSpec
from scopecat.models.config import ConfigProfileSnapshot, load_config_profile
from scopecat.proposals import accept_parameter_proposal
from tests.support.records import read_model
from tests.support.signal_testkit import (
    execute_best_signal_evaluation,
    execute_signal_native_run,
)

EXAMPLE_DIR = Path(__file__).parents[4] / "fixtures" / "core" / "simulated_scan"


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXAMPLE_DIR / "config-profile.json")


def load_experiment() -> ExperimentSpec:
    return read_model(EXAMPLE_DIR / "experiment.json", ExperimentSpec)


def simulate_and_evaluate(tmp_path: Path) -> str:
    manifest, _snapshot = execute_signal_native_run(
        config=load_config(),
        experiment=load_experiment(),
        workspace=tmp_path,
    )
    execute_best_signal_evaluation(run_id=manifest.run_id, workspace=tmp_path)
    return manifest.run_id


def accept_best_signal(
    tmp_path: Path,
    run_id: str,
    *,
    entry_id: str = "best-signal-entry",
) -> str:
    result, *_ = accept_parameter_proposal(
        run_id=run_id,
        selector="best-signal-proposal",
        workspace=tmp_path,
        reviewer="operator",
        operator="operator",
        entry_id=entry_id,
        note="accept best signal",
    )
    return result.config_registry_entry_id
