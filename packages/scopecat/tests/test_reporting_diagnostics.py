from __future__ import annotations

import json
from pathlib import Path

import pytest

from scopecat.errors import ValidationFailed
from scopecat.models.artifact import Artifact
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.reporting import generate_run_report
from scopecat.runs import open_run_store
from tests.support.records import read_model, require_artifact_by_kind
from tests.support.reporting import (
    simulate,
    simulated_run_with_active_candidate_comparison,
)
from tests.support.signal_testkit import execute_best_signal_evaluation


def test_generate_run_report_missing_run_comparison_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulated_run_with_active_candidate_comparison(tmp_path)
    manifest = open_run_store(tmp_path).read_manifest(baseline_run_id)
    comparison_artifact = require_artifact_by_kind(
        manifest.artifact_refs,
        "run_comparison_result",
    )
    (tmp_path / "runs" / baseline_run_id / comparison_artifact.path).unlink()

    with pytest.raises(ValidationFailed) as error:
        generate_run_report(run_id=baseline_run_id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == "missing_report_input"


def test_generate_run_report_missing_run_comparison_job_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulated_run_with_active_candidate_comparison(tmp_path)
    comparison_job = next(
        (tmp_path / "runs" / baseline_run_id / "comparisons").glob(
            "run-comparison-*.job.json"
        )
    )
    comparison_job.unlink()

    with pytest.raises(ValidationFailed) as error:
        generate_run_report(run_id=baseline_run_id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == "missing_report_input"


def test_generate_run_report_invalid_run_comparison_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulated_run_with_active_candidate_comparison(tmp_path)
    manifest = open_run_store(tmp_path).read_manifest(baseline_run_id)
    comparison_artifact = require_artifact_by_kind(
        manifest.artifact_refs,
        "run_comparison_result",
    )
    (tmp_path / "runs" / baseline_run_id / comparison_artifact.path).write_text("{}\n")

    with pytest.raises(ValidationFailed) as error:
        generate_run_report(run_id=baseline_run_id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == "invalid_report_input"


def test_generate_run_report_missing_config_snapshot_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    run_id = simulate(tmp_path)
    (tmp_path / "runs" / run_id / "config-profile.snapshot.json").unlink()

    with pytest.raises(ValidationFailed) as error:
        generate_run_report(run_id=run_id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == "missing_report_input"


def test_generate_run_report_invalid_config_snapshot_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    run_id = simulate(tmp_path)
    (tmp_path / "runs" / run_id / "config-profile.snapshot.json").write_text("{}\n")

    with pytest.raises(ValidationFailed) as error:
        generate_run_report(run_id=run_id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == "invalid_report_input"


def test_generate_run_report_invalid_config_source_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    run_id = simulate(tmp_path)
    config_path = tmp_path / "runs" / run_id / "config-profile.snapshot.json"
    persisted_config = read_model(config_path, ConfigProfileSnapshot)
    config_json = persisted_config.model_dump(mode="json")
    config_json["source"] = {"kind": "not_a_config_source"}
    config_path.write_text(json.dumps(config_json, indent=2) + "\n")

    with pytest.raises(ValidationFailed) as error:
        generate_run_report(run_id=run_id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == "invalid_report_input"


def test_generate_run_report_invalid_proposal_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    run_id = simulate(tmp_path)
    execute_best_signal_evaluation(run_id=run_id, workspace=tmp_path)
    proposal_path = (
        tmp_path / "runs" / run_id / "proposals" / "best-signal-proposal.json"
    )
    proposal_path.write_text("{}\n")

    with pytest.raises(ValidationFailed) as error:
        generate_run_report(run_id=run_id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == "invalid_report_input"


def test_generate_run_report_proposal_path_escape_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    run_id = simulate(tmp_path)
    execute_best_signal_evaluation(run_id=run_id, workspace=tmp_path)
    storage = open_run_store(tmp_path)
    manifest = storage.read_manifest(run_id)
    proposal_artifact = next(
        artifact
        for artifact in manifest.artifact_refs
        if artifact.kind == "parameter_change_set"
    )
    proposal_artifact.path = "../escape.json"
    storage.write_manifest(manifest)

    with pytest.raises(ValidationFailed) as error:
        generate_run_report(run_id=run_id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == "artifact_path_escape"


def test_generate_run_report_directory_artifact_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    run_id = simulate(tmp_path)
    storage = open_run_store(tmp_path)
    manifest = storage.read_manifest(run_id)
    manifest.artifact_refs.append(
        Artifact(
            id="bad-dir",
            kind="bad",
            path="artifacts",
            media_type="application/json",
        )
    )
    storage.write_manifest(manifest)

    with pytest.raises(ValidationFailed) as error:
        generate_run_report(run_id=run_id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == "report_artifact_is_directory"
