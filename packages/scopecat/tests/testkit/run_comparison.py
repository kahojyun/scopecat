from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scopecat.composition.local import local_workspace_services
from scopecat.config.profiles import load_config_profile
from scopecat.config.registry import resolve_config_registry_config_source
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.runs.refs import dataset_content_ref
from tests.testkit.config_registry import (
    activate_best_signal,
    seed_best_signal_parameter_change,
)
from tests.testkit.paths import CORE_FIXTURE_DIR as SIGNAL_EXAMPLE_DIR
from tests.testkit.records import read_measurement_records
from tests.testkit.signal_testkit import execute_signal_run
from tests.testkit.workflow_fixtures import load_invocation


def load_signal_config() -> ConfigProfileSnapshot:
    return load_config_profile(SIGNAL_EXAMPLE_DIR / "config-profile.json")


def run_signal_experiment(tmp_path: Path) -> str:
    manifest, _snapshot = execute_signal_run(
        config=load_signal_config(),
        experiment=load_invocation(),
        workspace=tmp_path,
    )
    return manifest.run_id


def active_config_registry_signal_run(
    *,
    baseline_run_id: str,
    tmp_path: Path,
) -> str:
    services = local_workspace_services(tmp_path)
    seed_best_signal_parameter_change(tmp_path=tmp_path, run_id=baseline_run_id)
    activate_best_signal(
        tmp_path,
        baseline_run_id,
        entry_id="best-signal-candidate-config",
    )
    config, source = resolve_config_registry_config_source(
        selector="active",
        unit_of_work=services.config_registry,
    )
    manifest, _snapshot = execute_signal_run(
        config=config,
        experiment=load_invocation(),
        workspace=tmp_path,
        config_source=source,
    )
    return manifest.run_id


def candidate_data_path(tmp_path: Path, run_id: str) -> Path:
    return (
        tmp_path
        / "runs"
        / run_id
        / dataset_content_ref(
            dataset_id="raw-measurements",
            kind="measurement_dataset",
        )
    )


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
