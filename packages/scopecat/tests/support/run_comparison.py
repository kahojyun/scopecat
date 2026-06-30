from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scopecat.config_registry import resolve_config_registry_config_source
from scopecat.experiments import ExperimentSpec
from scopecat.models.config import ConfigProfileSnapshot, load_config_profile
from scopecat.proposals import accept_parameter_proposal
from tests.support.records import read_measurement_records, read_model
from tests.support.signal_testkit import (
    execute_best_signal_evaluation,
    execute_signal_native_run,
)

ROOT = Path(__file__).parents[4]
SIMULATED_EXAMPLE_DIR = ROOT / "fixtures" / "core" / "simulated_scan"


def load_simulated_config() -> ConfigProfileSnapshot:
    return load_config_profile(SIMULATED_EXAMPLE_DIR / "config-profile.json")


def load_experiment() -> ExperimentSpec:
    return read_model(SIMULATED_EXAMPLE_DIR / "experiment.json", ExperimentSpec)


def simulate(tmp_path: Path) -> str:
    manifest, _snapshot = execute_signal_native_run(
        config=load_simulated_config(),
        experiment=load_experiment(),
        workspace=tmp_path,
    )
    return manifest.run_id


def active_config_registry_simulated_run(
    *,
    baseline_run_id: str,
    tmp_path: Path,
) -> str:
    execute_best_signal_evaluation(run_id=baseline_run_id, workspace=tmp_path)
    accept_parameter_proposal(
        run_id=baseline_run_id,
        selector="best-signal-proposal",
        workspace=tmp_path,
        reviewer="operator",
        operator="operator",
        entry_id="best-signal-proposal-candidate-config",
        note="looks good",
    )
    config, _provenance = resolve_config_registry_config_source(
        selector="active",
        workspace=tmp_path,
    )
    manifest, _snapshot = execute_signal_native_run(
        config=config,
        experiment=load_experiment(),
        workspace=tmp_path,
    )
    return manifest.run_id


def candidate_data_path(tmp_path: Path, run_id: str) -> Path:
    return tmp_path / "runs" / run_id / "artifacts" / "raw-measurements.jsonl"


def candidate_data_lines(tmp_path: Path, run_id: str) -> list[str]:
    return candidate_data_path(tmp_path, run_id).read_text().splitlines()


def candidate_data_records(tmp_path: Path, run_id: str) -> list[dict[str, Any]]:
    return [
        record.model_dump(mode="json")
        for record in read_measurement_records(candidate_data_path(tmp_path, run_id))
    ]


def write_candidate_data(tmp_path: Path, run_id: str, text: str) -> None:
    candidate_data_path(tmp_path, run_id).write_text(text)


def write_candidate_records(
    tmp_path: Path,
    run_id: str,
    records: list[dict[str, Any]],
) -> None:
    write_candidate_data(
        tmp_path,
        run_id,
        "".join(json.dumps(record) + "\n" for record in records),
    )
