from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.errors import ValidationFailed
from scopecat.run_comparison import execute_run_comparison
from tests.support.diagnostics import assert_diagnostic
from tests.support.run_comparison import (
    candidate_data_path,
    candidate_data_records,
    run_signal_experiment,
    write_candidate_records,
)


def test_run_comparison_rejects_unsafe_run_id(tmp_path: Path) -> None:
    with pytest.raises(ValidationFailed) as error:
        execute_run_comparison(
            baseline_run_id="../escape",
            candidate_run_id="candidate",
            workspace=tmp_path,
        )

    assert_diagnostic(error.value.diagnostics[0], "run_comparison_invalid_id")


def test_run_comparison_reports_missing_data(tmp_path: Path) -> None:
    baseline_run_id = run_signal_experiment(tmp_path)
    candidate_run_id = run_signal_experiment(tmp_path)
    candidate_data_path(tmp_path, candidate_run_id).unlink()

    with pytest.raises(ValidationFailed) as error:
        execute_run_comparison(
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
            workspace=tmp_path,
        )

    assert_diagnostic(error.value.diagnostics[0], "missing_run_comparison_input")


def test_run_comparison_reports_observable_unit_mismatch(tmp_path: Path) -> None:
    baseline_run_id = run_signal_experiment(tmp_path)
    candidate_run_id = run_signal_experiment(tmp_path)
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
