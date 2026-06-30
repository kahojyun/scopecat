from __future__ import annotations

from pathlib import Path

from scopecat.reporting import generate_run_report
from scopecat.run_comparison import review_run_comparison
from scopecat.runs import open_run_store
from tests.support.records import require_artifact_by_kind
from tests.support.reporting import simulated_run_with_active_candidate_comparison


def test_generate_run_report_includes_run_comparison(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulated_run_with_active_candidate_comparison(tmp_path)

    _job, report = generate_run_report(run_id=baseline_run_id, workspace=tmp_path)

    assert len(report.run_comparisons) == 1
    comparison = report.run_comparisons[0]
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
    assert comparison.baseline_config_source_status == "not_available"
    assert comparison.candidate_config_source_status == "available"
    assert comparison.review_status == "not_reviewed"
    assert comparison.decision is None

    report_markdown = (
        tmp_path / "runs" / baseline_run_id / "artifacts" / "run-report.md"
    ).read_text()
    assert "## Run Comparisons" in report_markdown
    assert "- Outcome: unchanged" in report_markdown
    assert "- Candidate config source: available" in report_markdown
    assert "- Review status: not_reviewed" in report_markdown


def test_generate_run_report_includes_reviewed_run_comparison(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulated_run_with_active_candidate_comparison(tmp_path)
    manifest = open_run_store(tmp_path).read_manifest(baseline_run_id)
    comparison_artifact = require_artifact_by_kind(
        manifest.artifact_refs,
        "run_comparison_result",
    )
    comparison_id = comparison_artifact.id.removesuffix("-result")
    review_run_comparison(
        run_id=baseline_run_id,
        selector=comparison_id,
        workspace=tmp_path,
        state="accepted",
        reviewer="operator",
        note="candidate accepted",
    )

    _job, report = generate_run_report(run_id=baseline_run_id, workspace=tmp_path)

    comparison = report.run_comparisons[0]
    assert comparison.review_status == "reviewed"
    assert comparison.review_ref == f"reviews/{comparison_id}.review.json"
    assert comparison.decision == "accepted"
    assert comparison.reviewer == "operator"
    assert comparison.note == "candidate accepted"

    report_markdown = (
        tmp_path / "runs" / baseline_run_id / "artifacts" / "run-report.md"
    ).read_text()
    assert "- Review status: reviewed" in report_markdown
    assert "- Decision: accepted" in report_markdown
    assert "- Reviewer: operator" in report_markdown
