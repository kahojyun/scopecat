"""Local static HTML artifact for Measurement Records operator review."""

from __future__ import annotations

import html
import os
from pathlib import Path
from typing import Any

from scopecat.measurement_records.operator_review import MeasurementRecordOperatorReviewRun

MEASUREMENT_RECORD_REVIEW_ARTIFACT_NAME = "measurement-record-review.html"


def build_measurement_record_review_html(
    operator_review: MeasurementRecordOperatorReviewRun | dict[str, Any],
) -> str:
    """Render an operator-review projection into local static HTML."""

    review = _review_payload(operator_review)
    entries = review["catalog"]["entries"]
    running = review["running_inspections"]
    context_attachments = review.get("context_attachments", {"entries": []})
    selected = review["selected_record"]
    findings = review["review_findings"]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Measurement Records Review</title>
  <style>{_style()}</style>
</head>
<body>
  <main>
    <header>
      <p class="eyebrow">local measurement records review artifact</p>
      <h1>Measurement Records Review</h1>
      <div class="facts">
        <span><b>review</b>{_esc(review["workflow"]["classification"])}</span>
        <span><b>catalog records</b>{_esc(review["catalog"]["entry_count"])}</span>
        <span><b>running inspections</b>{_esc(len(running))}</span>
        <span><b>findings</b>{_esc(len(findings))}</span>
      </div>
    </header>

    <section>
      <h2>Measurement Index</h2>
      {_catalog_table(entries)}
    </section>

    <section>
      <h2>Selected Record</h2>
      {_selected_record(selected)}
    </section>

    <section>
      <h2>Context Attachments</h2>
      {_context_attachment_table(context_attachments.get("entries", []))}
    </section>

    <section>
      <h2>Running Inspections</h2>
      {_running_table(running)}
    </section>

    <section>
      <h2>Review Findings</h2>
      {_findings_table(findings)}
    </section>

    <footer>
      Static local review artifact. Not a durable GUI state, public export,
      storage authority, record repair, read-model refresh, import approval,
      or history/audit log.
    </footer>
  </main>
</body>
</html>
"""


def write_measurement_record_review_artifact(
    operator_review: MeasurementRecordOperatorReviewRun | dict[str, Any],
    *,
    output_dir: Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Write a local static operator-review artifact and return a receipt."""

    review = _review_payload(operator_review)
    storage_root = Path(review["storage_root"]).resolve()
    output_dir_resolved = output_dir.resolve()
    if output_dir_resolved == storage_root or storage_root in output_dir_resolved.parents:
        raise ValueError("measurement record review artifact output_dir must not be in storage")
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / MEASUREMENT_RECORD_REVIEW_ARTIFACT_NAME
    if html_path.is_symlink():
        raise ValueError("measurement record review artifact target must not be a symlink")
    existed = os.path.lexists(html_path)
    if existed and not overwrite:
        raise ValueError("measurement record review artifact already exists")
    html_path.write_text(build_measurement_record_review_html(review), encoding="utf-8")
    return {
        "artifact_posture": "review_summary",
        "html_artifact": {
            "filename": MEASUREMENT_RECORD_REVIEW_ARTIFACT_NAME,
            "local_path": str(html_path),
            "created": html_path.is_file(),
            "overwritten": existed,
            "durable_storage_member": False,
        },
        "operator_review": {
            "request_id": review["request"]["request_id"],
            "classification": review["workflow"]["classification"],
            "catalog_entry_count": review["catalog"]["entry_count"],
            "running_inspection_count": len(review["running_inspections"]),
            "review_finding_count": len(review["review_findings"]),
        },
    }


def _review_payload(
    operator_review: MeasurementRecordOperatorReviewRun | dict[str, Any],
) -> dict[str, Any]:
    if isinstance(operator_review, MeasurementRecordOperatorReviewRun):
        return operator_review.to_dict()
    if not isinstance(operator_review, dict):
        raise ValueError("measurement record review artifact input must be an operator review")
    if operator_review.get("artifact_posture") != "local_measurement_record_operator_review":
        raise ValueError("measurement record review artifact input posture is unsupported")
    return operator_review


def _catalog_table(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return '<p class="empty">No projected records are visible.</p>'
    rows = []
    for entry in entries:
        primary = entry["primary_data"]
        table = entry["table"]
        rows.append(
            "<tr>"
            f"<td><code>{_esc(entry['record_id'])}</code></td>"
            f"<td>{_esc(entry['lifecycle_state'])}</td>"
            f"<td>{_esc(primary['observed_row_count'])}</td>"
            f"<td>{_esc(table['column_count'])}</td>"
            f"<td>{_esc(table['preview_row_count'])}</td>"
            f"<td>{_esc(entry['review_finding_count'])}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>Record</th><th>Lifecycle</th><th>Rows</th><th>Columns</th>"
        "<th>Preview Rows</th><th>Findings</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _selected_record(selected: dict[str, Any] | None) -> str:
    if selected is None:
        return '<p class="empty">No selected record is visible.</p>'
    record = selected.get("record") or {}
    source = selected.get("source")
    inspection = selected.get("inspection")
    facts = [
        ("source", source),
        ("record", record.get("record_id")),
        ("lifecycle", record.get("lifecycle_state")),
    ]
    if inspection is not None:
        facts.extend(
            [
                ("visible rows", inspection.get("visible_rows_recorded")),
                ("remaining rows", inspection.get("remaining_rows")),
            ]
        )
    return _fact_list(facts)


def _context_attachment_table(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return '<p class="empty">No context attachment receipts were recorded.</p>'
    rows = []
    for entry in entries:
        for attachment in entry["attachments"]:
            rows.append(
                "<tr>"
                f"<td><code>{_esc(entry['record_id'])}</code></td>"
                f"<td>{_esc(attachment['family'])}</td>"
                f"<td>{_esc(attachment['role'])}</td>"
                f"<td>{_esc(attachment.get('label'))}</td>"
                f"<td>{_esc(attachment['reference_kind'])}</td>"
                f"<td><code>{_esc(attachment['reference_value'])}</code></td>"
                f"<td>{_esc(attachment['state'])}</td>"
                "</tr>"
            )
    return (
        "<table><thead><tr>"
        "<th>Record</th><th>Family</th><th>Role</th><th>Label</th>"
        "<th>Reference</th><th>Value</th><th>State</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _running_table(running: list[dict[str, Any]]) -> str:
    if not running:
        return '<p class="empty">No running inspections were declared.</p>'
    rows = []
    for summary in running:
        record = summary["record"]
        inspection = summary["inspection"]
        rows.append(
            "<tr>"
            f"<td><code>{_esc(record['record_id'])}</code></td>"
            f"<td>{_esc(record['lifecycle_state'])}</td>"
            f"<td>{_esc(inspection['classification'])}</td>"
            f"<td>{_esc(inspection['visible_rows_recorded'])}</td>"
            f"<td>{_esc(inspection['expected_total_rows'])}</td>"
            f"<td>{_esc(inspection['remaining_rows'])}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>Record</th><th>Lifecycle</th><th>Inspection</th>"
        "<th>Visible Rows</th><th>Expected Rows</th><th>Remaining</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _findings_table(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return '<p class="empty">No operator-review findings.</p>'
    rows = []
    for finding in findings:
        rows.append(
            "<tr>"
            f"<td>{_esc(finding.get('code'))}</td>"
            f"<td><code>{_esc(finding.get('target'))}</code></td>"
            f"<td>{_esc(finding.get('message'))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Code</th><th>Target</th><th>Message</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _fact_list(items: list[tuple[str, object]]) -> str:
    return (
        '<dl class="facts-list">'
        + "".join(
            f"<dt>{_esc(label)}</dt><dd>{_esc(value if value is not None else 'not visible')}</dd>"
            for label, value in items
        )
        + "</dl>"
    )


def _style() -> str:
    return """
      :root {
        color-scheme: light;
        --bg: #f6f7f9;
        --panel: #ffffff;
        --text: #20242a;
        --muted: #59616d;
        --line: #d9dde3;
        --head: #eef1f5;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      body { background: var(--bg); color: var(--text); margin: 0; }
      main { max-width: 1120px; margin: 0 auto; padding: 24px; }
      header { margin-bottom: 24px; }
      .eyebrow {
        color: var(--muted);
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0;
        margin: 0 0 4px;
        text-transform: uppercase;
      }
      h1 { font-size: 24px; margin: 0 0 16px; }
      h2 { font-size: 16px; margin: 24px 0 8px; }
      .facts {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
        gap: 10px;
      }
      .facts span {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 6px;
        padding: 10px;
      }
      .facts b {
        color: var(--muted);
        display: block;
        font-size: 12px;
        margin-bottom: 4px;
      }
      .facts-list {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 6px;
        display: grid;
        font-size: 13px;
        gap: 6px 10px;
        grid-template-columns: 140px 1fr;
        padding: 12px;
      }
      .facts-list dt { color: var(--muted); }
      .facts-list dd { margin: 0; overflow-wrap: anywhere; }
      table {
        background: var(--panel);
        border: 1px solid var(--line);
        border-collapse: collapse;
        border-radius: 6px;
        overflow: hidden;
        width: 100%;
      }
      th, td {
        border-bottom: 1px solid #e5e8ed;
        font-size: 13px;
        padding: 8px 10px;
        text-align: left;
      }
      th { background: var(--head); font-weight: 700; }
      tr:last-child td { border-bottom: 0; }
      code {
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 12px;
      }
      .empty {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 6px;
        color: var(--muted);
        font-size: 13px;
        margin: 0;
        padding: 12px;
      }
      footer {
        border-top: 1px solid var(--line);
        color: var(--muted);
        font-size: 13px;
        margin-top: 28px;
        padding-top: 14px;
      }
    """


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)
