from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat.run_comparison import (
    execute_run_comparison,
    list_run_comparisons,
)
from tests.support.run_comparison import (
    active_config_registry_signal_run,
    load_experiment,
    load_signal_config,
    run_signal_experiment,
)
from tests.support.signal_testkit import execute_signal_run


def test_execute_run_comparison_returns_result_and_lists_baseline_comparison(
    tmp_path: Path,
) -> None:
    baseline_run_id = run_signal_experiment(tmp_path)
    candidate_run_id = run_signal_experiment(tmp_path)

    result = execute_run_comparison(
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        workspace=tmp_path,
    )

    comparison_id = f"run-comparison-{candidate_run_id}-signal"
    assert result.comparison_id == comparison_id
    assert result.measurement_count == 3
    assert result.outcome == "unchanged"
    assert result.observable_id == "signal"
    assert result.baseline_peak_point_index == 1
    assert result.candidate_peak_point_index == 1
    assert result.peak_value_delta.value == 0.0
    assert result.peak_value_delta.unit == "ratio"
    assert result.mean_value_delta.value == 0.0
    assert len(result.points) == 3
    assert result.points[0].value_delta.value == 0.0
    assert result.baseline_config_source is None
    assert result.candidate_config_source is None

    assert [
        view.id
        for view in list_run_comparisons(run_id=baseline_run_id, workspace=tmp_path)
    ] == [comparison_id]
    assert list_run_comparisons(run_id=candidate_run_id, workspace=tmp_path) == []


def test_execute_run_comparison_includes_active_config_source(
    tmp_path: Path,
) -> None:
    baseline_run_id = run_signal_experiment(tmp_path)
    candidate_run_id = active_config_registry_signal_run(
        baseline_run_id=baseline_run_id,
        tmp_path=tmp_path,
    )

    result = execute_run_comparison(
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        workspace=tmp_path,
    )

    assert result.baseline_config_source is None
    assert result.candidate_config_source is not None
    assert result.candidate_config_source.selector == "active"
    assert result.candidate_config_source.entry_id == ("best-signal-candidate-config")


def test_execute_run_comparison_tracks_compared_runs(
    tmp_path: Path,
) -> None:
    config = load_signal_config()
    experiment = load_experiment()
    baseline_manifest, _baseline_snapshot = execute_signal_run(
        config=config,
        experiment=experiment,
        workspace=tmp_path,
    )
    candidate_manifest, _candidate_snapshot = execute_signal_run(
        config=config,
        experiment=experiment,
        workspace=tmp_path,
    )
    lab = sc.open(tmp_path, config=config)
    baseline = sc.Run(
        session=lab,
        manifest=baseline_manifest,
    )
    candidate = sc.Run(
        session=lab,
        manifest=candidate_manifest,
    )
    baseline.analysis("baseline review").input(
        "raw-measurements",
        expected_kind="measurement_dataset",
    ).save()
    candidate.analysis("candidate review").input(
        "raw-measurements",
        expected_kind="measurement_dataset",
    ).save()

    result = execute_run_comparison(
        baseline_run_id=baseline.id,
        candidate_run_id=candidate.id,
        workspace=tmp_path,
    )

    assert result.baseline_run_id == baseline.id
    assert result.candidate_run_id == candidate.id
