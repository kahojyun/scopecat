from __future__ import annotations

from pathlib import Path

from scopecat.composition.local import local_run_repository, local_workspace_services
from scopecat.run_comparison import review_run_comparison
from scopecat.run_overview import build_run_overview
from tests.testkit.run_overview import signal_run_with_active_candidate_comparison


def test_build_run_overview_includes_run_comparison(
    tmp_path: Path,
) -> None:
    baseline_run_id = signal_run_with_active_candidate_comparison(tmp_path)

    overview = build_run_overview(
        run_id=baseline_run_id, services=local_workspace_services(tmp_path)
    )

    assert len(overview.run_comparisons) == 1
    comparison = overview.run_comparisons[0]
    assert comparison.baseline_run_id == baseline_run_id
    assert comparison.candidate_run_id.startswith("run_")
    assert comparison.outcome == "unchanged"
    assert comparison.measurement_count == 3
    assert comparison.observable_id == "signal"
    assert comparison.baseline_peak_point_index == 1
    assert comparison.candidate_peak_point_index == 1
    assert comparison.baseline_peak_value.value == 1.0
    assert comparison.candidate_peak_value.value == 1.0
    assert comparison.peak_value_delta.value == 0.0
    assert comparison.mean_value_delta.value == 0.0
    assert comparison.baseline_config_source is None
    assert comparison.candidate_config_source is not None
    assert comparison.review_status == "not_reviewed"
    assert comparison.decision is None


def test_build_run_overview_includes_reviewed_run_comparison(
    tmp_path: Path,
) -> None:
    baseline_run_id = signal_run_with_active_candidate_comparison(tmp_path)
    manifest = local_run_repository(tmp_path).read_manifest(baseline_run_id)
    comparison_record = next(
        record for record in manifest.records if record.kind == "run_comparison_result"
    )
    comparison_id = comparison_record.id.removesuffix("-result")
    review_run_comparison(
        run_id=baseline_run_id,
        selector=comparison_id,
        services=local_workspace_services(tmp_path),
        state="accepted",
        reviewer="operator",
        note="candidate accepted",
    )

    overview = build_run_overview(
        run_id=baseline_run_id, services=local_workspace_services(tmp_path)
    )

    comparison = overview.run_comparisons[0]
    assert comparison.review_status == "reviewed"
    assert comparison.decision == "accepted"
    assert comparison.reviewer == "operator"
    assert comparison.note == "candidate accepted"
