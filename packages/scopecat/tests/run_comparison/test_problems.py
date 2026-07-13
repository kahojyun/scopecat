from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.composition.local import local_workspace_services
from scopecat.kernel.errors import CheckFailed, DataIntegrityError
from scopecat.run_comparison import execute_run_comparison
from tests.testkit.run_comparison import (
    candidate_data_path,
    candidate_data_records,
    run_signal_experiment,
    write_candidate_records,
)


def test_run_comparison_rejects_unsafe_run_id(tmp_path: Path) -> None:
    services = local_workspace_services(tmp_path)
    with pytest.raises(CheckFailed) as error:
        execute_run_comparison(
            baseline_run_id="../escape",
            candidate_run_id="candidate",
            services=services,
        )

    assert error.value.problems[0].code == "run_comparison_invalid_id"


def test_run_comparison_reports_missing_data(tmp_path: Path) -> None:
    services = local_workspace_services(tmp_path)
    baseline_run_id = run_signal_experiment(tmp_path)
    candidate_run_id = run_signal_experiment(tmp_path)
    candidate_data_path(tmp_path, candidate_run_id).unlink()

    with pytest.raises(DataIntegrityError) as error:
        execute_run_comparison(
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
            services=services,
        )

    assert error.value.problems[0].code == "missing_run_comparison_input"


def test_run_comparison_reports_observable_unit_mismatch(tmp_path: Path) -> None:
    services = local_workspace_services(tmp_path)
    baseline_run_id = run_signal_experiment(tmp_path)
    candidate_run_id = run_signal_experiment(tmp_path)
    records = candidate_data_records(tmp_path, candidate_run_id)
    records[1]["observables"]["signal"]["unit"] = "count"
    write_candidate_records(tmp_path, candidate_run_id, records)

    with pytest.raises(DataIntegrityError) as error:
        execute_run_comparison(
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
            services=services,
        )

    assert error.value.problems[0].code == "run_comparison_unit_mismatch"
