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
import re
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


@dataclass(frozen=True)
class LegacyScenarioInput:
    """User-facing facts the scenario expects from a legacy workflow."""

    legacy_system_id: str
    legacy_run_id: str
    label: str
    experiment_type: str
    primary_locator: str
    notebook_locator: str
    run_started_at: str
    run_completed_at: str
    created_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "legacy_system_id": self.legacy_system_id,
            "legacy_run_id": self.legacy_run_id,
            "label": self.label,
            "experiment_type": self.experiment_type,
            "primary_locator": self.primary_locator,
            "notebook_locator": self.notebook_locator,
            "run_started_at": self.run_started_at,
            "run_completed_at": self.run_completed_at,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ScenarioIds:
    """Scenario-local generated Scopecat ids.

    This is not a final id policy. It keeps the scenario user input focused on
    legacy/domain facts while still satisfying current prototype APIs.
    """

    measurement_id: str
    legacy_record_id: str
    imported_record_id: str
    legacy_record_request_id: str
    import_request_id: str
    inventory_request_id: str
    read_request_id: str
    primary_locator_id: str
    notebook_locator_id: str
    normalized_source_item_id: str

    def to_dict(self) -> dict[str, str]:
        return {
            "measurement_id": self.measurement_id,
            "legacy_record_id": self.legacy_record_id,
            "imported_record_id": self.imported_record_id,
            "legacy_record_request_id": self.legacy_record_request_id,
            "import_request_id": self.import_request_id,
            "inventory_request_id": self.inventory_request_id,
            "read_request_id": self.read_request_id,
            "primary_locator_id": self.primary_locator_id,
            "notebook_locator_id": self.notebook_locator_id,
            "normalized_source_item_id": self.normalized_source_item_id,
        }


def run_scenario(workspace: Path | None = None, *, open_browser: bool = False) -> ScenarioResult:
    """Run the full local scenario and return generated artifact paths."""

    scenario_input = _scenario_input()
    scenario_ids = _scenario_ids(scenario_input)
    scenario_workspace = workspace or Path(tempfile.mkdtemp(prefix="scopecat-legacy-scenario-"))
    scenario_workspace.mkdir(parents=True, exist_ok=True)
    storage_root = scenario_workspace / "storage"
    content_root = scenario_workspace / "content"
    review_root = scenario_workspace / "review"
    storage_root.mkdir(exist_ok=True)
    content_root.mkdir(exist_ok=True)
    review_root.mkdir(exist_ok=True)

    legacy_source_path = scenario_workspace / scenario_input.primary_locator
    _write_legacy_tsv(legacy_source_path)
    legacy_run = record_legacy_measurement_run_from_request(
        _legacy_record_request(scenario_input, scenario_ids),
        storage_root=storage_root,
    )
    normalized_source_path, rows_recorded = _convert_legacy_tsv_to_normalized_csv(
        legacy_source_path,
        content_root / "normalized" / f"{scenario_ids.measurement_id}.csv",
    )
    import_run = import_measurement_record_from_request(
        _import_request(
            scenario_input,
            scenario_ids,
            normalized_source_path,
            rows_recorded,
        ),
        content_root=content_root,
        storage_root=storage_root,
    )
    inventory = list_measurement_record_storage_from_request(
        MeasurementRecordStorageInventoryRequest(request_id=scenario_ids.inventory_request_id),
        storage_root=storage_root,
    )
    read_view = read_created_record_primary_table_from_request(
        MeasurementRecordReadRequest(
            request_id=scenario_ids.read_request_id,
            record_id=scenario_ids.imported_record_id,
            record_dir=f"records/{scenario_ids.imported_record_id}",
            writer_receipt_path=f"records/{scenario_ids.imported_record_id}/writer-receipt.json",
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
        scenario_input=scenario_input,
        scenario_ids=scenario_ids,
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


def _scenario_input() -> LegacyScenarioInput:
    return LegacyScenarioInput(
        legacy_system_id="legacy-labview",
        legacy_run_id="lv-run-001",
        label="Legacy LabVIEW Run 001",
        experiment_type="rabi",
        primary_locator="legacy-system/run-001.tsv",
        notebook_locator="legacy-notebook://operator-workstation/run-001",
        created_at="2026-06-01T09:00:00Z",
        run_started_at="2026-06-01T08:50:00Z",
        run_completed_at="2026-06-01T08:55:00Z",
    )


def _scenario_ids(source: LegacyScenarioInput) -> ScenarioIds:
    base = _slug(f"{source.legacy_system_id}-{source.legacy_run_id}")
    return ScenarioIds(
        measurement_id=f"meas-{base}",
        legacy_record_id=f"rec-{base}-legacy",
        imported_record_id=f"rec-{base}-primary",
        legacy_record_request_id=f"record-{base}-legacy",
        import_request_id=f"import-{base}-primary",
        inventory_request_id=f"inventory-{base}",
        read_request_id=f"read-{base}-primary",
        primary_locator_id=f"loc-{base}-primary",
        notebook_locator_id=f"loc-{base}-notebook",
        normalized_source_item_id=f"normalized-{base}",
    )


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "legacy-run"


def _legacy_record_request(
    source: LegacyScenarioInput,
    ids: ScenarioIds,
) -> LegacyRunRecordRequest:
    return LegacyRunRecordRequest(
        request_id=ids.legacy_record_request_id,
        approval_state="approved",
        record_id=ids.legacy_record_id,
        record_dir=f"records/{ids.legacy_record_id}",
        legacy_system_id=source.legacy_system_id,
        legacy_run_id=source.legacy_run_id,
        created_at=source.created_at,
        label=source.label,
        experiment_type=source.experiment_type,
        run_started_at=source.run_started_at,
        run_completed_at=source.run_completed_at,
        locators=(
            LegacyRunLocator(
                locator_id=ids.primary_locator_id,
                kind="workspace_relative_path",
                role="primary_data",
                value=source.primary_locator,
            ),
            LegacyRunLocator(
                locator_id=ids.notebook_locator_id,
                kind="opaque_reference",
                role="notebook",
                value=source.notebook_locator,
            ),
        ),
        operator_notes="Synthetic scenario: legacy system remains outside Scopecat.",
    )


def _import_request(
    source: LegacyScenarioInput,
    ids: ScenarioIds,
    normalized_source_path: Path,
    rows_recorded: int,
) -> MeasurementRecordDurableImportRequest:
    content_ref = f"normalized/{ids.measurement_id}.csv"
    return MeasurementRecordDurableImportRequest(
        request_id=ids.import_request_id,
        approval_state="approved",
        record_id=ids.imported_record_id,
        record_dir=f"records/{ids.imported_record_id}",
        primary_data_path=f"records/{ids.imported_record_id}/primary.csv",
        writer_receipt_path=f"records/{ids.imported_record_id}/writer-receipt.json",
        finalization_receipt_path=f"records/{ids.imported_record_id}/finalization-receipt.json",
        read_model_path=f"records/{ids.imported_record_id}/record-read-model.json",
        creation_source_kind="import",
        label=source.label,
        experiment_type=source.experiment_type,
        import_source=MeasurementRecordImportSource(
            source_kind="adapter_normalized_primary_data",
            source_id=ids.legacy_record_id,
            source_item_id=ids.normalized_source_item_id,
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
    scenario_input: LegacyScenarioInput,
    scenario_ids: ScenarioIds,
) -> dict[str, Any]:
    measurement_review = _measurement_review_model(
        legacy_run=legacy_run,
        import_run=import_run,
        inventory=inventory,
        read_view=read_view,
    )
    return {
        "scenario": "legacy_run_storage_gui",
        "workspace": str(workspace),
        "outputs": {
            "legacy_source_path": str(legacy_source_path),
            "normalized_source_path": str(normalized_source_path),
        },
        "user_input": scenario_input.to_dict(),
        "generated_ids": scenario_ids.to_dict(),
        "workflow": {
            "legacy_record_classification": legacy_run["workflow"]["classification"],
            "import_classification": import_run["workflow"]["classification"],
            "inventory_classification": inventory["workflow"]["classification"],
            "read_view_classification": read_view["workflow"]["classification"],
        },
        "records": {
            "legacy_record_id": scenario_ids.legacy_record_id,
            "imported_record_id": scenario_ids.imported_record_id,
        },
        "legacy_run": legacy_run,
        "import_run": import_run,
        "inventory": inventory,
        "read_view": read_view,
        "measurement_review": measurement_review,
    }


def _measurement_review_model(
    *,
    legacy_run: dict[str, Any],
    import_run: dict[str, Any],
    inventory: dict[str, Any],
    read_view: dict[str, Any],
) -> dict[str, Any]:
    entries = {entry["record_id"]: entry for entry in inventory["entries"]}
    legacy_request = legacy_run["request"]
    import_request = import_run["request"]
    source_id = import_request["import_source"]["source_id"]
    imported_from_legacy = source_id == legacy_request["record_id"]
    primary_locator = _first_locator_by_role(legacy_request["locators"], "primary_data")
    imported_entry = entries[import_request["record_id"]]
    legacy_entry = entries[legacy_request["record_id"]]
    preview = read_view["table"]["preview"]
    measurement_id = _slug(
        f"{legacy_request['legacy_system_id']}-{legacy_request['legacy_run_id']}"
    )
    return {
        "artifact_posture": "scenario_measurement_review_projection",
        "projection_policy": {
            "input_authority": "scenario_outputs_and_storage_inventory",
            "storage_mutation": "not_performed",
            "relationship_inference": "durable_import_source_id_only",
            "scopecat_id_generation": "scenario_local_from_legacy_facts",
            "recursive_relation_traversal": "not_performed",
            "final_gui_contract": "not_defined",
        },
        "measurements": [
            {
                "measurement_id": f"meas-{measurement_id}",
                "title": legacy_request.get("label") or legacy_request["legacy_run_id"],
                "kind": "legacy_measurement_with_imported_primary_data",
                "experiment_type": import_request.get("experiment_type"),
                "primary_data": {
                    "state": "available",
                    "row_count": read_view["table"]["row_count"],
                    "columns": preview["columns"],
                    "preview_rows": preview["rows"],
                },
                "legacy": {
                    "legacy_system_id": legacy_request["legacy_system_id"],
                    "legacy_run_id": legacy_request["legacy_run_id"],
                    "primary_locator": primary_locator,
                    "run_started_at": legacy_request["run_started_at"],
                    "run_completed_at": legacy_request["run_completed_at"],
                },
                "conversion": {
                    "relationship": (
                        "converted_from_recorded_legacy_locator"
                        if imported_from_legacy
                        else "declared_import_source"
                    ),
                    "normalized_source": import_request["import_source"]["content_ref"],
                },
                "storage_artifacts": {
                    "legacy_record_id": legacy_request["record_id"],
                    "legacy_record_dir": legacy_entry["record_dir"],
                    "legacy_receipt_state": legacy_entry["legacy_run"]["state"],
                    "primary_record_id": import_request["record_id"],
                    "primary_record_dir": imported_entry["record_dir"],
                    "primary_read_model_state": imported_entry["read_model"]["state"],
                },
                "next_action": "review_primary_data_preview",
            },
        ],
        "diagnostics": {
            "inventory_classification": inventory["workflow"]["classification"],
            "review_finding_count": len(inventory["review_findings"]),
        },
    }


def _first_locator_by_role(
    locators: list[dict[str, Any]],
    role: str,
) -> dict[str, Any] | None:
    for locator in locators:
        if locator["role"] == role:
            return locator
    return None


def _html_review(summary: dict[str, Any]) -> str:
    measurement_review = summary["measurement_review"]
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
    .subtitle {{
      color: #59616d;
      font-size: 14px;
      margin: -8px 0 20px;
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
    .measurements {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 14px;
      margin-top: 14px;
    }}
    .measurement {{
      background: #ffffff;
      border: 1px solid #d9dde3;
      border-radius: 6px;
      padding: 14px;
    }}
    .measurement h3 {{
      font-size: 15px;
      margin: 0 0 4px;
    }}
    .meta {{
      color: #59616d;
      font-size: 12px;
      margin-bottom: 12px;
      overflow-wrap: anywhere;
    }}
    .facts {{
      display: grid;
      grid-template-columns: 120px 1fr;
      gap: 6px 10px;
      font-size: 13px;
    }}
    .facts dt {{
      color: #59616d;
    }}
    .facts dd {{
      margin: 0;
      overflow-wrap: anywhere;
    }}
    .secondary {{
      margin-top: 24px;
      padding-top: 8px;
      border-top: 1px solid #d9dde3;
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
    <h1>Measurement Review</h1>
    <p class="subtitle">Legacy run recorded, converted to normalized primary data, and shown as one user-facing measurement.</p>
    <section class="summary">
      {_status_tile("Legacy record", summary["workflow"]["legacy_record_classification"])}
      {_status_tile("Primary import", summary["workflow"]["import_classification"])}
      {_status_tile("Inventory", summary["workflow"]["inventory_classification"])}
      {_status_tile("Read view", summary["workflow"]["read_view_classification"])}
    </section>
    <h2>Measurements</h2>
    {_measurement_cards(measurement_review["measurements"])}
    <h2>Primary Data Preview</h2>
    {_preview_table(columns, rows)}
    <section class="secondary">
      <h2>Storage Diagnostics</h2>
      {_inventory_table(inventory_entries)}
    </section>
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


def _measurement_cards(measurements: list[dict[str, Any]]) -> str:
    return (
        '<section class="measurements">'
        + "".join(_measurement_card(measurement) for measurement in measurements)
        + "</section>"
    )


def _measurement_card(measurement: dict[str, Any]) -> str:
    legacy = measurement["legacy"]
    conversion = measurement["conversion"]
    primary = measurement["primary_data"]
    locator = legacy.get("primary_locator") or {}
    storage = measurement["storage_artifacts"]
    return f"""
      <article class="measurement">
        <h3>{_escape(measurement["title"])}</h3>
        <div class="meta">{_escape(legacy["legacy_system_id"])} / {_escape(legacy["legacy_run_id"])} · {_escape(measurement["kind"])}</div>
        <dl class="facts">
          <dt>Primary data</dt><dd>{_escape(primary["state"])}</dd>
          <dt>Rows</dt><dd>{_escape(primary["row_count"] if primary["row_count"] is not None else "not imported")}</dd>
          <dt>Source</dt><dd>{_escape(conversion["relationship"])}</dd>
          <dt>Legacy locator</dt><dd><code>{_escape(locator.get("value", "not declared"))}</code></dd>
          <dt>Scopecat artifacts</dt><dd>{_escape(storage["legacy_record_id"])} + {_escape(storage["primary_record_id"])}</dd>
          <dt>Next action</dt><dd>{_escape(measurement["next_action"])}</dd>
        </dl>
      </article>
    """


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
        "measurement": {
            "measurement_id": result.summary["generated_ids"]["measurement_id"],
            "legacy_system_id": result.summary["user_input"]["legacy_system_id"],
            "legacy_run_id": result.summary["user_input"]["legacy_run_id"],
        },
        "diagnostic_records": result.summary["records"],
        "html_review": str(result.html_path),
        "scenario_summary": str(result.summary_path),
    }


if __name__ == "__main__":
    raise SystemExit(main())
