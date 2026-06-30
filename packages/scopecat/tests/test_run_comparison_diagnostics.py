from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.errors import ValidationFailed
from scopecat.execution.dry_run import execute_dry_run
from scopecat.run_comparison import execute_run_comparison
from scopecat.runs import open_run_store
from tests.support.diagnostics import assert_diagnostic
from tests.support.records import assert_artifact_ref
from tests.support.run_comparison import (
    candidate_data_lines,
    candidate_data_records,
    load_experiment,
    load_simulated_config,
    simulate,
    write_candidate_data,
    write_candidate_records,
)


def test_run_comparison_unsafe_run_id_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationFailed) as error:
        execute_run_comparison(
            baseline_run_id="../escape",
            candidate_run_id="candidate",
            workspace=tmp_path,
        )

    assert_diagnostic(error.value.diagnostics[0], "run_comparison_invalid_id")


def test_run_comparison_rejects_dry_run_input_with_stable_diagnostic(
    tmp_path: Path,
) -> None:
    dry_manifest, _dry_run = execute_dry_run(
        config=load_simulated_config(),
        experiment=load_experiment(),
        workspace=tmp_path,
    )
    candidate_run_id = simulate(tmp_path)

    with pytest.raises(ValidationFailed) as error:
        execute_run_comparison(
            baseline_run_id=dry_manifest.run_id,
            candidate_run_id=candidate_run_id,
            workspace=tmp_path,
        )

    assert_diagnostic(
        error.value.diagnostics[0],
        "unsupported_run_comparison_input",
        path="dry_run",
    )


def test_run_comparison_missing_data_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulate(tmp_path)
    candidate_run_id = simulate(tmp_path)
    (
        tmp_path / "runs" / candidate_run_id / "artifacts" / "raw-measurements.jsonl"
    ).unlink()

    with pytest.raises(ValidationFailed) as error:
        execute_run_comparison(
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
            workspace=tmp_path,
        )

    assert_diagnostic(error.value.diagnostics[0], "missing_run_comparison_input")


def test_run_comparison_empty_data_reports_stable_diagnostic(tmp_path: Path) -> None:
    baseline_run_id = simulate(tmp_path)
    candidate_run_id = simulate(tmp_path)
    write_candidate_data(tmp_path, candidate_run_id, "")

    with pytest.raises(ValidationFailed) as error:
        execute_run_comparison(
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
            workspace=tmp_path,
        )

    assert_diagnostic(error.value.diagnostics[0], "empty_run_comparison_input")


def test_run_comparison_invalid_data_reports_stable_diagnostic(tmp_path: Path) -> None:
    baseline_run_id = simulate(tmp_path)
    candidate_run_id = simulate(tmp_path)
    write_candidate_data(tmp_path, candidate_run_id, "{bad json}\n")

    with pytest.raises(ValidationFailed) as error:
        execute_run_comparison(
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
            workspace=tmp_path,
        )

    assert_diagnostic(error.value.diagnostics[0], "invalid_run_comparison_input")


def test_run_comparison_measurement_count_mismatch_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulate(tmp_path)
    candidate_run_id = simulate(tmp_path)
    lines = candidate_data_lines(tmp_path, candidate_run_id)
    write_candidate_data(tmp_path, candidate_run_id, "\n".join(lines[:-1]) + "\n")

    with pytest.raises(ValidationFailed) as error:
        execute_run_comparison(
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
            workspace=tmp_path,
        )

    assert_diagnostic(
        error.value.diagnostics[0],
        "run_comparison_measurement_mismatch",
    )


def test_run_comparison_point_mismatch_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulate(tmp_path)
    candidate_run_id = simulate(tmp_path)
    records = candidate_data_records(tmp_path, candidate_run_id)
    records[1]["point_index"] = 99
    write_candidate_records(tmp_path, candidate_run_id, records)

    with pytest.raises(ValidationFailed) as error:
        execute_run_comparison(
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
            workspace=tmp_path,
        )

    assert_diagnostic(error.value.diagnostics[0], "run_comparison_point_mismatch")


def test_run_comparison_missing_observable_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulate(tmp_path)
    candidate_run_id = simulate(tmp_path)
    records = candidate_data_records(tmp_path, candidate_run_id)
    records[1]["observables"] = {}
    write_candidate_records(tmp_path, candidate_run_id, records)

    with pytest.raises(ValidationFailed) as error:
        execute_run_comparison(
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
            workspace=tmp_path,
        )

    assert_diagnostic(
        error.value.diagnostics[0],
        "run_comparison_missing_observable",
    )


def test_run_comparison_unit_mismatch_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulate(tmp_path)
    candidate_run_id = simulate(tmp_path)
    records = candidate_data_records(tmp_path, candidate_run_id)
    records[1]["observables"]["signal"]["unit"] = "count"
    write_candidate_records(tmp_path, candidate_run_id, records)

    with pytest.raises(ValidationFailed) as error:
        execute_run_comparison(
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
            workspace=tmp_path,
        )

    assert_diagnostic(error.value.diagnostics[0], "run_comparison_unit_mismatch")


def test_run_comparison_missing_dataset_schema_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulate(tmp_path)
    candidate_run_id = simulate(tmp_path)
    storage = open_run_store(tmp_path)
    manifest = storage.read_manifest(candidate_run_id)
    raw_artifact = assert_artifact_ref(manifest.artifact_refs, "raw-measurements")
    raw_artifact.metadata.pop("dataset_schema")
    storage.write_manifest(manifest)

    with pytest.raises(ValidationFailed) as error:
        execute_run_comparison(
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
            workspace=tmp_path,
        )

    assert_diagnostic(
        error.value.diagnostics[0],
        "missing_run_comparison_dataset_schema",
    )


def test_run_comparison_ambiguous_primary_observable_requires_explicit_observable(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulate(tmp_path)
    candidate_run_id = simulate(tmp_path)
    storage = open_run_store(tmp_path)
    manifest = storage.read_manifest(candidate_run_id)
    raw_artifact = assert_artifact_ref(manifest.artifact_refs, "raw-measurements")
    schema = raw_artifact.metadata["dataset_schema"]
    signal_variable = next(
        variable for variable in schema["variables"] if variable["id"] == "signal"
    )
    contrast_variable = dict(signal_variable)
    contrast_variable["id"] = "contrast"
    schema["variables"].append(contrast_variable)
    schema["primary_observables"] = ["signal", "contrast"]
    storage.write_manifest(manifest)

    with pytest.raises(ValidationFailed) as error:
        execute_run_comparison(
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
            workspace=tmp_path,
        )

    assert_diagnostic(
        error.value.diagnostics[0],
        "run_comparison_ambiguous_primary_observable",
    )


def test_run_comparison_primary_observable_mismatch_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulate(tmp_path)
    candidate_run_id = simulate(tmp_path)
    storage = open_run_store(tmp_path)
    manifest = storage.read_manifest(candidate_run_id)
    raw_artifact = assert_artifact_ref(manifest.artifact_refs, "raw-measurements")
    schema = raw_artifact.metadata["dataset_schema"]
    for variable in schema["variables"]:
        if variable["id"] == "signal":
            variable["id"] = "contrast"
            break
    schema["primary_observables"] = ["contrast"]
    storage.write_manifest(manifest)

    with pytest.raises(ValidationFailed) as error:
        execute_run_comparison(
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
            workspace=tmp_path,
        )

    assert_diagnostic(
        error.value.diagnostics[0],
        "run_comparison_primary_observable_mismatch",
    )
