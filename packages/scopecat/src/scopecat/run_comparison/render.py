"""Run comparison rendering helpers."""

from scopecat.run_comparison.models import (
    RunComparisonConfigSourceSummary,
    RunComparisonResult,
)


def render_run_comparison_summary(result: RunComparisonResult) -> str:
    lines = [
        "# Run Comparison",
        "",
        f"- Comparison: {result.comparison_id}",
        f"- Baseline run: {result.baseline_run_id}",
        f"- Candidate run: {result.candidate_run_id}",
        f"- Observable: {result.observable_id}",
        f"- Measurements: {result.measurement_count}",
        f"- Outcome: {result.outcome}",
        f"- Baseline peak point: {result.baseline_peak_point_index}",
        f"- Candidate peak point: {result.candidate_peak_point_index}",
        (
            f"- Baseline peak value: {result.baseline_peak_value.value} "
            f"{result.baseline_peak_value.unit}"
        ),
        (
            f"- Candidate peak value: {result.candidate_peak_value.value} "
            f"{result.candidate_peak_value.unit}"
        ),
        f"- Peak value delta: {result.peak_value_delta.value} {result.value_unit}",
        f"- Mean value delta: {result.mean_value_delta.value} {result.value_unit}",
        "",
        "## Config Sources",
        "",
        "### Baseline",
        "",
        *_config_source_lines(result.baseline_config_source),
        "",
        "### Candidate",
        "",
        *_config_source_lines(result.candidate_config_source),
        "",
        "## Analysis Artifacts",
        "",
        "### Baseline",
        "",
        *_artifact_id_lines(result.baseline_analysis_artifact_ids),
        "",
        "### Candidate",
        "",
        *_artifact_id_lines(result.candidate_analysis_artifact_ids),
        "",
        "## Points",
        "",
    ]
    for point in result.points:
        lines.append(
            f"- {point.point_index}: baseline {point.baseline_value.value} "
            f"{point.baseline_value.unit}, candidate {point.candidate_value.value} "
            f"{point.candidate_value.unit}, delta {point.value_delta.value} "
            f"{point.value_delta.unit}"
        )
    return "\n".join(lines) + "\n"


def _artifact_id_lines(artifact_ids: list[str]) -> list[str]:
    if not artifact_ids:
        return ["- none"]
    return [f"- {artifact_id}" for artifact_id in artifact_ids]


def _config_source_lines(source: RunComparisonConfigSourceSummary) -> list[str]:
    if source.status == "not_available":
        return ["- Status: not_available"]
    return [
        f"- Status: {source.status}",
        f"- Source kind: {source.source_kind}",
        f"- Selector: {source.selector}",
        f"- Entry: {source.entry_id}",
        f"- Config ref: {source.config_ref}",
        f"- Active state: {_optional_text(source.active_state_ref)}",
        f"- Active record: {_optional_text(source.active_record_id)}",
    ]


def _optional_text(value: str | None) -> str:
    return value if value is not None else "n/a"
