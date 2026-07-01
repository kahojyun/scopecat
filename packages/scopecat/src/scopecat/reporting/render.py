"""Run overview rendering helpers."""

from __future__ import annotations

from scopecat.reporting.models import (
    AnalysisRecordOverview,
    AnalysisReportOverview,
    RunOverview,
)


def render_run_overview(overview: RunOverview) -> str:
    lines = [
        "# Scopecat Run Overview",
        "",
        f"- Run ID: {overview.run.run_id}",
        f"- Status: {overview.run.status}",
        f"- Runner: {overview.run.runner_id}",
        f"- Dry-run: {str(overview.run.dry_run).lower()}",
        f"- Experiment: {overview.run.experiment_ref}",
        f"- Workspace: {overview.run.workspace_ref}",
        f"- Device: {overview.run.device_ref}",
        "",
        "## Config Source",
        "",
    ]
    if overview.config_source.status == "available":
        lines.extend(
            [
                f"- Status: {overview.config_source.status}",
                f"- Source kind: {overview.config_source.source_kind}",
                f"- Selector: {overview.config_source.selector}",
                f"- Entry: {overview.config_source.entry_id}",
                f"- Config ref: {overview.config_source.config_ref}",
                (
                    "- Active state: "
                    f"{_optional_text(overview.config_source.active_state_ref)}"
                ),
                (
                    "- Active record: "
                    f"{_optional_text(overview.config_source.active_record_id)}"
                ),
            ]
        )
    else:
        lines.append("- Status: not_available")

    lines.extend(["", "## Run Comparisons", ""])
    if overview.run_comparisons:
        for comparison in overview.run_comparisons:
            lines.extend(
                [
                    f"### {comparison.comparison_id}",
                    "",
                    f"- Candidate run: {comparison.candidate_run_id}",
                    f"- Observable: {comparison.observable_id}",
                    f"- Outcome: {comparison.outcome}",
                    f"- Measurements: {comparison.measurement_count}",
                    f"- Baseline peak point: {comparison.baseline_peak_point_index}",
                    f"- Candidate peak point: {comparison.candidate_peak_point_index}",
                    (
                        f"- Baseline peak value: "
                        f"{comparison.baseline_peak_value.value} "
                        f"{comparison.baseline_peak_value.unit}"
                    ),
                    (
                        f"- Candidate peak value: "
                        f"{comparison.candidate_peak_value.value} "
                        f"{comparison.candidate_peak_value.unit}"
                    ),
                    (
                        f"- Peak value delta: {comparison.peak_value_delta.value} "
                        f"{comparison.value_unit}"
                    ),
                    (
                        f"- Mean value delta: {comparison.mean_value_delta.value} "
                        f"{comparison.value_unit}"
                    ),
                    (
                        "- Baseline config source: "
                        f"{comparison.baseline_config_source_status}"
                    ),
                    (
                        "- Candidate config source: "
                        f"{comparison.candidate_config_source_status}"
                    ),
                    f"- Review status: {comparison.review_status}",
                ]
            )
            if comparison.review_status == "reviewed":
                lines.extend(
                    [
                        f"- Decision: {comparison.decision}",
                        f"- Reviewer: {comparison.reviewer}",
                        f"- Note: {comparison.note}",
                    ]
                )
            else:
                lines.append("- Decision: n/a")
            lines.extend(
                [
                    f"- Result: {comparison.result_ref}",
                    f"- Summary: {comparison.summary_ref}",
                    f"- Job: {comparison.job_ref}",
                    "",
                ]
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Artifacts", ""])
    if overview.artifact_refs:
        for artifact in overview.artifact_refs:
            lines.append(
                f"- {artifact.id}: {artifact.kind}, "
                f"{artifact.media_type or '-'}, {artifact.path}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Analysis Records", ""])
    if overview.analysis_records:
        for analysis in overview.analysis_records:
            lines.extend(_analysis_record_lines(analysis))
    else:
        lines.append("- none")

    lines.extend(["", "## Analysis Reports", ""])
    if overview.analysis_reports:
        for analysis_report in overview.analysis_reports:
            lines.extend(_analysis_report_lines(analysis_report))
    else:
        lines.append("- none")

    lines.extend(["", "## Proposals", ""])
    if overview.proposals:
        for proposal in overview.proposals:
            lines.extend(
                [
                    f"### {proposal.id}",
                    "",
                    f"- State: {proposal.state}",
                    f"- Operation: {proposal.operation_kind}",
                    f"- Reason: {proposal.reason}",
                    f"- Review status: {proposal.review.status}",
                ]
            )
            if proposal.parameter_id is not None:
                lines.append(f"- Parameter: {proposal.parameter_id}")
            if proposal.old_value is not None:
                lines.append(
                    f"- Old value: {proposal.old_value.value} {proposal.old_value.unit}"
                )
            if proposal.value is not None:
                lines.append(
                    f"- Proposed value: {proposal.value.value} {proposal.value.unit}"
                )
            if proposal.review.status == "reviewed":
                lines.extend(
                    [
                        f"- Decision: {proposal.review.decision}",
                        f"- Reviewer: {proposal.review.reviewer}",
                        f"- Note: {proposal.review.note}",
                    ]
                )
            lines.append("")
    else:
        lines.append("- none")

    return "\n".join(lines).rstrip("\n") + "\n"


def _analysis_record_lines(record: AnalysisRecordOverview) -> list[str]:
    lines = [
        f"### {record.title}",
        "",
        f"- Artifact: {record.artifact_id}",
        f"- Ref: {record.ref}",
        f"- Outputs: {', '.join(record.output_kinds) or 'none'}",
        f"- Proposals: {record.proposal_count}",
    ]
    if record.source_artifact_ids:
        lines.append(f"- Source artifacts: {', '.join(record.source_artifact_ids)}")
    if record.report_artifact_ids:
        lines.append(f"- Reports: {', '.join(record.report_artifact_ids)}")
    lines.append("")
    return lines


def _analysis_report_lines(report: AnalysisReportOverview) -> list[str]:
    lines = [
        f"### {report.title}",
        "",
        f"- Artifact: {report.artifact_id}",
        f"- Ref: {report.ref}",
        f"- Media type: {report.media_type or '-'}",
    ]
    if report.source_analysis_artifact_id is not None:
        lines.append(f"- Analysis record: {report.source_analysis_artifact_id}")
    if report.source_artifact_ids:
        lines.append(f"- Source artifacts: {', '.join(report.source_artifact_ids)}")
    lines.append("")
    return lines


def _optional_text(value: str | None) -> str:
    return value if value is not None else "n/a"
