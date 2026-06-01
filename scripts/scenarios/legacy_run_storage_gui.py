#!/usr/bin/env python3
"""Run a legacy-system to Scopecat storage scenario.

This scenario is intentionally small and local. It creates synthetic legacy
output, records legacy locators in Scopecat storage, converts the legacy output
to normalized primary CSV, imports that primary data as a Measurement Record,
lists storage inventory, and writes a static HTML review page.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import sys
import tempfile
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scopecat.measurement_records import (  # noqa: E402
    LegacyRunLocator,
    LegacyRunRecordRequest,
    MeasurementRecordDurableImportRequest,
    MeasurementRecordImportSource,
    MeasurementRecordReadRequest,
    MeasurementRecordStorageInventoryRequest,
    list_measurement_record_storage_from_request,
    read_created_record_primary_table_from_request,
    record_legacy_measurement_run_from_request,
)
from scopecat.measurement_records.durable_import import (  # noqa: E402
    import_measurement_record_from_request,
)

LEGACY_RECORD_ID = "legacy-run-001"
IMPORTED_RECORD_ID = "imported-run-001"


@dataclass(frozen=True)
class ScenarioResult:
    """Paths and compact outputs produced by the scenario."""

    workspace: Path
    storage_root: Path
    content_root: Path
    legacy_source_path: Path
    normalized_source_path: Path
    html_path: Path
    summary_path: Path
    summary: dict[str, Any]


def run_scenario(workspace: Path | None = None, *, open_browser: bool = False) -> ScenarioResult:
    """Run the full local scenario and return generated artifact paths."""

    scenario_workspace = workspace or Path(tempfile.mkdtemp(prefix="scopecat-legacy-scenario-"))
    scenario_workspace.mkdir(parents=True, exist_ok=True)
    storage_root = scenario_workspace / "storage"
    content_root = scenario_workspace / "content"
    legacy_root = scenario_workspace / "legacy-system"
    review_root = scenario_workspace / "review"
    storage_root.mkdir(exist_ok=True)
    content_root.mkdir(exist_ok=True)
    legacy_root.mkdir(exist_ok=True)
    review_root.mkdir(exist_ok=True)

    legacy_source_path = legacy_root / "run-001.tsv"
    _write_legacy_tsv(legacy_source_path)
    legacy_run = record_legacy_measurement_run_from_request(
        _legacy_record_request(),
        storage_root=storage_root,
    )
    normalized_source_path, rows_recorded = _convert_legacy_tsv_to_normalized_csv(
        legacy_source_path,
        content_root / "normalized" / "run-001.csv",
    )
    import_run = import_measurement_record_from_request(
        _import_request(normalized_source_path, rows_recorded),
        content_root=content_root,
        storage_root=storage_root,
    )
    inventory = list_measurement_record_storage_from_request(
        MeasurementRecordStorageInventoryRequest(request_id="scenario-inventory"),
        storage_root=storage_root,
    )
    read_view = read_created_record_primary_table_from_request(
        MeasurementRecordReadRequest(
            request_id="scenario-read-imported-primary",
            record_id=IMPORTED_RECORD_ID,
            record_dir=f"records/{IMPORTED_RECORD_ID}",
            writer_receipt_path=f"records/{IMPORTED_RECORD_ID}/writer-receipt.json",
            preview_row_limit=10,
        ),
        storage_root=storage_root,
    )

    summary = _summary(
        workspace=scenario_workspace,
        legacy_run=legacy_run.to_dict(),
        import_run=import_run.to_dict(),
        inventory=inventory.to_dict(),
        read_view=read_view.to_dict(),
        legacy_source_path=legacy_source_path,
        normalized_source_path=normalized_source_path,
    )
    html_path = review_root / "legacy-run-review.html"
    html_path.write_text(_html_review(summary), encoding="utf-8")
    summary_path = review_root / "scenario-summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if open_browser:
        webbrowser.open(html_path.resolve().as_uri())
    return ScenarioResult(
        workspace=scenario_workspace,
        storage_root=storage_root,
        content_root=content_root,
        legacy_source_path=legacy_source_path,
        normalized_source_path=normalized_source_path,
        html_path=html_path,
        summary_path=summary_path,
        summary=summary,
    )


def _legacy_record_request() -> LegacyRunRecordRequest:
    return LegacyRunRecordRequest(
        request_id="scenario-record-legacy-run",
        approval_state="approved",
        record_id=LEGACY_RECORD_ID,
        record_dir=f"records/{LEGACY_RECORD_ID}",
        legacy_system_id="legacy-labview",
        legacy_run_id="lv-run-001",
        created_at="2026-06-01T09:00:00Z",
        label="Legacy LabVIEW Run 001",
        experiment_type="rabi",
        run_started_at="2026-06-01T08:50:00Z",
        run_completed_at="2026-06-01T08:55:00Z",
        locators=(
            LegacyRunLocator(
                locator_id="legacy-raw-table",
                kind="workspace_relative_path",
                role="primary_data",
                value="legacy-system/run-001.tsv",
            ),
            LegacyRunLocator(
                locator_id="legacy-notebook",
                kind="opaque_reference",
                role="notebook",
                value="legacy-notebook://operator-workstation/run-001",
            ),
        ),
        operator_notes="Synthetic scenario: legacy system remains outside Scopecat.",
    )


def _import_request(
    normalized_source_path: Path,
    rows_recorded: int,
) -> MeasurementRecordDurableImportRequest:
    content_ref = "normalized/run-001.csv"
    return MeasurementRecordDurableImportRequest(
        request_id="scenario-import-normalized-primary",
        approval_state="approved",
        record_id=IMPORTED_RECORD_ID,
        record_dir=f"records/{IMPORTED_RECORD_ID}",
        primary_data_path=f"records/{IMPORTED_RECORD_ID}/primary.csv",
        writer_receipt_path=f"records/{IMPORTED_RECORD_ID}/writer-receipt.json",
        finalization_receipt_path=f"records/{IMPORTED_RECORD_ID}/finalization-receipt.json",
        read_model_path=f"records/{IMPORTED_RECORD_ID}/record-read-model.json",
        creation_source_kind="import",
        label="Imported Legacy Run 001",
        experiment_type="rabi",
        import_source=MeasurementRecordImportSource(
            source_kind="adapter_normalized_primary_data",
            source_id=LEGACY_RECORD_ID,
            source_item_id="normalized-primary-001",
            content_ref=content_ref,
            declared_digest=_sha256_file(normalized_source_path),
            size_bytes=normalized_source_path.stat().st_size,
            rows_recorded=rows_recorded,
        ),
    )


def _write_legacy_tsv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        ("0", "101", "-2.0"),
        ("100", "128", "-1.0"),
        ("200", "155", "0.0"),
        ("300", "131", "1.0"),
        ("400", "104", "2.0"),
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(("timestamp_ms", "counts", "detuning_mhz"))
        writer.writerows(rows)


def _convert_legacy_tsv_to_normalized_csv(source: Path, target: Path) -> tuple[Path, int]:
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("r", encoding="utf-8", newline="") as source_handle:
        reader = csv.DictReader(source_handle, delimiter="\t")
        rows = list(reader)
    with target.open("w", encoding="utf-8", newline="") as target_handle:
        writer = csv.DictWriter(
            target_handle,
            fieldnames=("time_s", "signal_counts", "detuning_mhz"),
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "time_s": f"{float(row['timestamp_ms']) / 1000:.3f}",
                    "signal_counts": row["counts"],
                    "detuning_mhz": row["detuning_mhz"],
                }
            )
    return target, len(rows)


def _summary(
    *,
    workspace: Path,
    legacy_run: dict[str, Any],
    import_run: dict[str, Any],
    inventory: dict[str, Any],
    read_view: dict[str, Any],
    legacy_source_path: Path,
    normalized_source_path: Path,
) -> dict[str, Any]:
    return {
        "scenario": "legacy_run_storage_gui",
        "workspace": str(workspace),
        "outputs": {
            "legacy_source_path": str(legacy_source_path),
            "normalized_source_path": str(normalized_source_path),
        },
        "workflow": {
            "legacy_record_classification": legacy_run["workflow"]["classification"],
            "import_classification": import_run["workflow"]["classification"],
            "inventory_classification": inventory["workflow"]["classification"],
            "read_view_classification": read_view["workflow"]["classification"],
        },
        "records": {
            "legacy_record_id": LEGACY_RECORD_ID,
            "imported_record_id": IMPORTED_RECORD_ID,
        },
        "legacy_run": legacy_run,
        "import_run": import_run,
        "inventory": inventory,
        "read_view": read_view,
    }


def _html_review(summary: dict[str, Any]) -> str:
    inventory_entries = summary["inventory"]["entries"]
    table = summary["read_view"]["table"]
    preview = table["preview"]
    rows = preview["rows"]
    columns = preview["columns"]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Scopecat Legacy Run Scenario</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f6f7f9;
      color: #20242a;
    }}
    body {{
      margin: 0;
      padding: 24px;
    }}
    main {{
      max-width: 1120px;
      margin: 0 auto;
    }}
    h1 {{
      font-size: 24px;
      margin: 0 0 16px;
    }}
    h2 {{
      font-size: 16px;
      margin: 24px 0 8px;
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
    }}
    .tile {{
      background: #ffffff;
      border: 1px solid #d9dde3;
      border-radius: 6px;
      padding: 12px;
    }}
    .label {{
      color: #59616d;
      font-size: 12px;
      margin-bottom: 4px;
    }}
    .value {{
      font-size: 14px;
      font-weight: 600;
      overflow-wrap: anywhere;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #ffffff;
      border: 1px solid #d9dde3;
      border-radius: 6px;
      overflow: hidden;
    }}
    th, td {{
      border-bottom: 1px solid #e5e8ed;
      padding: 8px 10px;
      text-align: left;
      font-size: 13px;
    }}
    th {{
      background: #eef1f5;
      font-weight: 700;
    }}
    tr:last-child td {{
      border-bottom: 0;
    }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
    }}
  </style>
</head>
<body>
  <main>
    <h1>Scopecat Legacy Run Scenario</h1>
    <section class="summary">
      {_status_tile("Legacy record", summary["workflow"]["legacy_record_classification"])}
      {_status_tile("Primary import", summary["workflow"]["import_classification"])}
      {_status_tile("Inventory", summary["workflow"]["inventory_classification"])}
      {_status_tile("Read view", summary["workflow"]["read_view_classification"])}
    </section>
    <h2>Storage Inventory</h2>
    {_inventory_table(inventory_entries)}
    <h2>Primary Data Preview</h2>
    {_preview_table(columns, rows)}
    <h2>Generated Files</h2>
    <table>
      <tbody>
        <tr><th>Legacy source</th><td><code>{_escape(summary["outputs"]["legacy_source_path"])}</code></td></tr>
        <tr><th>Normalized source</th><td><code>{_escape(summary["outputs"]["normalized_source_path"])}</code></td></tr>
      </tbody>
    </table>
  </main>
</body>
</html>
"""


def _status_tile(label: str, value: str) -> str:
    return (
        '<div class="tile">'
        f'<div class="label">{_escape(label)}</div>'
        f'<div class="value">{_escape(value)}</div>'
        "</div>"
    )


def _inventory_table(entries: list[dict[str, Any]]) -> str:
    rows = []
    for entry in entries:
        legacy = entry["legacy_run"]
        read_model = entry["read_model"]
        rows.append(
            "<tr>"
            f"<td>{_escape(entry['record_id'])}</td>"
            f"<td>{_escape(entry['creation_source_kind'])}</td>"
            f"<td>{_escape(entry['lifecycle_state'])}</td>"
            f"<td>{_escape(entry['primary_data']['state'])}</td>"
            f"<td>{_escape(legacy['state'])}</td>"
            f"<td>{_escape(read_model['state'])}</td>"
            f"<td>{_escape(entry['next_action'])}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>Record</th><th>Source</th><th>Lifecycle</th><th>Primary</th>"
        "<th>Legacy receipt</th><th>Read model</th><th>Next action</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _preview_table(columns: list[str], rows: list[dict[str, Any]]) -> str:
    header = "".join(f"<th>{_escape(column)}</th>" for column in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{_escape(row.get(column, ''))}</td>" for column in columns) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _sha256_file(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        help="Directory for scenario outputs. A temporary directory is used when omitted.",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the generated static HTML review page in the default browser.",
    )
    args = parser.parse_args()
    result = run_scenario(args.workspace, open_browser=args.open)
    print(json.dumps(_console_summary(result), indent=2, sort_keys=True))
    return 0


def _console_summary(result: ScenarioResult) -> dict[str, Any]:
    return {
        "scenario": result.summary["scenario"],
        "workspace": str(result.workspace),
        "workflow": result.summary["workflow"],
        "records": result.summary["records"],
        "html_review": str(result.html_path),
        "scenario_summary": str(result.summary_path),
    }


if __name__ == "__main__":
    raise SystemExit(main())
