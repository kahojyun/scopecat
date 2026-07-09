from __future__ import annotations

from pathlib import Path

from scopecat._manifest_updates import write_manifest_records
from scopecat._workflows.config import register_and_activate_candidate_config
from scopecat.candidate_configs import CandidateConfig
from scopecat.config_profiles import load_config_profile
from scopecat.models.artifact import RunRecordEntry
from scopecat.models.config import ConfigProfileSnapshot, build_config_parameters
from scopecat.models.parameter import ParameterChangeSet, ParameterPatch, Quantity
from scopecat.runs import open_run_store, record_storage_ref
from tests.support.signal_testkit import execute_signal_run
from tests.support.workflow_fixtures import load_invocation

EXAMPLE_DIR = Path(__file__).parents[4] / "fixtures" / "core" / "simple_scan"


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXAMPLE_DIR / "config-profile.json")


def signal_run_with_parameter_change(tmp_path: Path) -> str:
    manifest, _snapshot = execute_signal_run(
        config=load_config(),
        experiment=load_invocation(),
        workspace=tmp_path,
    )
    seed_best_signal_parameter_change(tmp_path=tmp_path, run_id=manifest.run_id)
    return manifest.run_id


def seed_best_signal_parameter_change(*, tmp_path: Path, run_id: str) -> None:
    storage = open_run_store(tmp_path)
    config = storage.read_config_profile_snapshot(run_id)
    parameter = build_config_parameters(config).get("drive_frequency")
    old_value = (
        parameter.quantity if parameter is not None else Quantity(value=5.0, unit="GHz")
    )
    change_set = ParameterChangeSet(
        id="best-signal",
        source_run_id=run_id,
        reason="Best signal fixture parameter change.",
        patches=[
            ParameterPatch(
                kind="set_scalar",
                parameter_id="drive_frequency",
                expected_value=old_value,
                value=old_value,
            )
        ],
        confidence=1.0,
    )
    record = RunRecordEntry(
        id=change_set.id,
        kind="parameter_change_set",
        media_type="application/json",
    )
    ref = record_storage_ref(record)
    storage.write_model(run_id, ref, change_set)
    manifest = storage.read_manifest(run_id)
    write_manifest_records(
        storage=storage,
        manifest=manifest,
        records=[record],
    )


def activate_best_signal(
    tmp_path: Path,
    run_id: str,
    *,
    entry_id: str = "best-signal-entry",
) -> str:
    change_set = open_run_store(tmp_path).read_model(
        run_id,
        "records/parameter_change_set/best-signal.json",
        ParameterChangeSet,
    )
    candidate = CandidateConfig(
        analysis_title="best signal fixture",
        analysis_key="best-signal",
        changes=(change_set,),
    )
    activation = register_and_activate_candidate_config(
        candidate=candidate,
        workspace=tmp_path,
        entry_id=entry_id,
        registered_by="operator",
        operator="operator",
        note="activate best signal",
    )
    return activation.entry.id
