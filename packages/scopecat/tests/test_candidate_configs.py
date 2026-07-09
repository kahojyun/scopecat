from __future__ import annotations

import json
from pathlib import Path

import pytest

import scopecat as sc
from scopecat._workflows.config import register_and_activate_candidate_config
from scopecat.candidate_configs import CandidateConfig
from scopecat.config_registry import list_config_registry_entries
from scopecat.errors import ValidationFailed
from scopecat.experiments import ExperimentSpec
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.parameter_changes import load_parameter_change
from scopecat.relations import col
from tests.support.config_registry import signal_run_with_parameter_change
from tests.support.records import read_model
from tests.support.signal_instruments import TestSignalInstrumentProvider

EXAMPLE_DIR = Path(__file__).parents[3] / "fixtures" / "core" / "simple_scan"


def load_experiment() -> ExperimentSpec:
    return read_model(EXAMPLE_DIR / "experiment.json", ExperimentSpec)


def test_candidate_config_resolves_parameter_change_and_runs_follow_up(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
    )
    run = lab.prepare(load_experiment()).run()
    candidate = (
        run.analysis("manual readout review")
        .propose(
            "drive_frequency",
            sc.set_param("drive_frequency", sc.Quantity(5.5, "GHz")),
            confidence=0.9,
        )
        .candidate_config()
    )

    follow_up = lab.prepare(load_experiment(), config=candidate).run()
    decision = lab.review_parameter_changes(
        run,
        "drive_frequency",
        note="checked parameter change",
    )

    assert decision.decision == "approved"
    assert candidate.change_set_ids == ("drive_frequency",)
    updated = follow_up.config.parameter_state.scalar_value_set().get("drive_frequency")
    assert updated is not None
    assert updated.quantity.value == 5.5


def test_candidate_config_selects_independent_parameter_changes(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
    )
    run = lab.prepare(load_experiment()).run()
    analysis = (
        run.analysis("multi fit")
        .propose(
            "q0",
            sc.set_param("drive_frequency", sc.Quantity(5.5, "GHz")),
            reason="q0 fit passed",
        )
        .propose(
            "q1",
            sc.set_param("missing_frequency", sc.Quantity(4.9, "GHz")),
            reason="q1 fit produced an invalid change",
        )
    )

    with pytest.raises(ValidationFailed) as selection_error:
        analysis.candidate_config()
    assert selection_error.value.diagnostics[0].code == (
        "candidate_config_selection_required"
    )

    follow_up = lab.prepare(
        load_experiment(),
        config=analysis.candidate_config("q0"),
    ).run()
    updated = follow_up.config.parameter_state.scalar_value_set().get("drive_frequency")
    assert updated is not None
    assert updated.quantity.value == 5.5

    with pytest.raises(ValidationFailed) as invalid_change:
        lab.prepare(load_experiment(), config=analysis.candidate_config("q1")).run()
    assert invalid_change.value.diagnostics[0].code == (
        "parameter_change_candidate_patch_invalid"
    )


def test_analysis_rejects_point_local_parameter_change_patch(
    tmp_path: Path,
) -> None:
    lab = sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        instrument_provider=TestSignalInstrumentProvider(),
    )
    run = lab.prepare(load_experiment()).run()

    with pytest.raises(ValidationFailed) as error:
        run.analysis("bad patch").propose(
            "drive_frequency",
            sc.set_param("drive_frequency", col("drive_frequency")),
        )

    assert error.value.diagnostics[0].code == "analysis_parameter_change_invalid"


def test_candidate_config_preflight_failure_does_not_register(
    tmp_path: Path,
) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    config_path = tmp_path / "runs" / run_id / "config-profile.snapshot.json"
    persisted_config = read_model(config_path, ConfigProfileSnapshot)
    config = persisted_config.model_dump(mode="json")
    config["parameter_state"]["scalar_values"]["values"] = []
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    change_set = load_parameter_change(
        run_id=run_id,
        selector="best-signal",
        workspace=tmp_path,
    )
    candidate = CandidateConfig(
        analysis_title="best signal fixture",
        analysis_key="best-signal",
        changes=(change_set,),
    )

    with pytest.raises(ValidationFailed) as error:
        register_and_activate_candidate_config(
            candidate=candidate,
            workspace=tmp_path,
            registered_by="operator",
            operator="operator",
        )

    assert error.value.diagnostics[0].code == "parameter_change_candidate_patch_invalid"
    assert list_config_registry_entries(workspace=tmp_path) == []
