#!/usr/bin/env python3
"""Run a legacy-system to Scopecat storage scenario.

This scenario is intentionally small and local. It creates synthetic legacy
output, records legacy locators in Scopecat storage, converts the legacy output
to normalized primary CSV, attaches that primary data to the same Measurement
Record, lists storage inventory, and writes a static HTML review page.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import tempfile
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.measurement_records import (
    ConvertedPrimaryData,
    LegacyMeasurementSource,
    MeasurementRecordOperatorReviewRequest,
    MeasurementRecordStorageInventoryRequest,
    RecordedReferenceInput,
    legacy_measurement_slug,
    list_measurement_record_storage_from_request,
    record_legacy_measurement,
    review_measurement_records_from_request,
    write_measurement_record_review_artifact,
)


@dataclass(frozen=True)
class ScenarioResult:
    """Paths and compact outputs produced by the scenario."""

    workspace: Path
    storage_root: Path
    content_root: Path
    legacy_source_paths: tuple[Path, ...]
    normalized_source_paths: tuple[Path, ...]
    html_path: Path
    operator_review_html_path: Path
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


def run_scenario(workspace: Path | None = None, *, open_browser: bool = False) -> ScenarioResult:
    """Run the full local scenario and return generated artifact paths."""

    scenario_inputs = _scenario_inputs()
    scenario_workspace = workspace or Path(tempfile.mkdtemp(prefix="scopecat-legacy-scenario-"))
    scenario_workspace.mkdir(parents=True, exist_ok=True)
    storage_root = scenario_workspace / "storage"
    content_root = scenario_workspace / "content"
    review_root = scenario_workspace / "review"
    operator_review_root = scenario_workspace / "operator-review"
    storage_root.mkdir(exist_ok=True)
    content_root.mkdir(exist_ok=True)
    review_root.mkdir(exist_ok=True)
    operator_review_root.mkdir(exist_ok=True)

    measurement_runs = []
    legacy_source_paths = []
    normalized_source_paths = []
    for scenario_input in scenario_inputs:
        source = _legacy_measurement_source(scenario_input)
        slug = legacy_measurement_slug(source)
        legacy_source_path = scenario_workspace / scenario_input.primary_locator
        _write_legacy_tsv(legacy_source_path, rows=_legacy_rows(scenario_input))
        normalized_source_path, rows_recorded = _convert_legacy_tsv_to_normalized_csv(
            legacy_source_path,
            content_root / "normalized" / f"{slug}.csv",
        )
        reference_artifacts = _write_reference_artifacts(
            scenario_workspace,
            scenario_input,
        )
        workflow_run = record_legacy_measurement(
            source=source,
            primary_data=ConvertedPrimaryData(
                path=normalized_source_path,
                rows_recorded=rows_recorded,
            ),
            references=_recorded_reference_inputs(scenario_input, reference_artifacts),
            storage_root=storage_root,
            content_root=content_root,
        )
        measurement_runs.append(
            {
                "scenario_input": scenario_input,
                "workflow_run": workflow_run.to_dict(),
                "scenario_ids": workflow_run.generated_ids,
                "legacy_source_path": legacy_source_path,
                "normalized_source_path": normalized_source_path,
                "legacy_run": workflow_run.legacy_run.to_dict(),
                "primary_attach": workflow_run.primary_attach.to_dict(),
                "reference_artifacts": reference_artifacts,
                "recorded_reference": (
                    None
                    if workflow_run.recorded_reference is None
                    else workflow_run.recorded_reference.to_dict()
                ),
                "read_view": workflow_run.read_view.to_dict(),
            }
        )
        legacy_source_paths.append(legacy_source_path)
        normalized_source_paths.append(normalized_source_path)

    inventory = list_measurement_record_storage_from_request(
        MeasurementRecordStorageInventoryRequest(request_id="inventory-legacy-measurements"),
        storage_root=storage_root,
    )
    operator_review = review_measurement_records_from_request(
        MeasurementRecordOperatorReviewRequest(request_id="operator-review-legacy-measurements"),
        storage_root=storage_root,
    )
    operator_review_artifact = write_measurement_record_review_artifact(
        operator_review,
        output_dir=operator_review_root,
    )

    summary = _summary(
        workspace=scenario_workspace,
        measurement_runs=measurement_runs,
        inventory=inventory.to_dict(),
        operator_review=operator_review.to_dict(),
        operator_review_artifact=operator_review_artifact,
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
        legacy_source_paths=tuple(legacy_source_paths),
        normalized_source_paths=tuple(normalized_source_paths),
        html_path=html_path,
        operator_review_html_path=Path(operator_review_artifact["html_artifact"]["local_path"]),
        summary_path=summary_path,
        summary=summary,
    )


def _scenario_inputs() -> tuple[LegacyScenarioInput, ...]:
    return (
        LegacyScenarioInput(
            legacy_system_id="legacy-labview",
            legacy_run_id="lv-run-001",
            label="Legacy LabVIEW Run 001",
            experiment_type="rabi",
            primary_locator="legacy-system/run-001.tsv",
            notebook_locator="legacy-notebook://operator-workstation/run-001",
            created_at="2026-06-01T09:00:00Z",
            run_started_at="2026-06-01T08:50:00Z",
            run_completed_at="2026-06-01T08:55:00Z",
        ),
        LegacyScenarioInput(
            legacy_system_id="legacy-labview",
            legacy_run_id="lv-run-002",
            label="Legacy LabVIEW Run 002",
            experiment_type="ramsey",
            primary_locator="legacy-system/run-002.tsv",
            notebook_locator="legacy-notebook://operator-workstation/run-002",
            created_at="2026-06-01T10:00:00Z",
            run_started_at="2026-06-01T09:45:00Z",
            run_completed_at="2026-06-01T09:52:00Z",
        ),
    )


def _legacy_measurement_source(source: LegacyScenarioInput) -> LegacyMeasurementSource:
    return LegacyMeasurementSource(
        legacy_system_id=source.legacy_system_id,
        legacy_run_id=source.legacy_run_id,
        label=source.label,
        experiment_type=source.experiment_type,
        primary_locator=source.primary_locator,
        notebook_locator=source.notebook_locator,
        created_at=source.created_at,
        run_started_at=source.run_started_at,
        run_completed_at=source.run_completed_at,
        operator_notes="Synthetic scenario: legacy system remains outside Scopecat.",
    )


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "legacy-run"


def _write_reference_artifacts(
    workspace: Path,
    source: LegacyScenarioInput,
) -> dict[str, dict[str, Any]]:
    parameter_path = workspace / "legacy-system" / "params" / f"{source.legacy_run_id}.json"
    setup_path = workspace / "legacy-system" / "setup" / f"{source.legacy_run_id}.json"
    code_dir = workspace / "legacy-system" / "code" / source.experiment_type
    code_path = code_dir / "acquire.py"
    analysis_path = workspace / "analysis" / _slug(source.legacy_run_id) / "summary.csv"
    parameter_payload = {
        "legacy_run_id": source.legacy_run_id,
        "pulse_length_ns": 40 if source.experiment_type == "rabi" else 80,
        "detuning_span_mhz": 4.0 if source.experiment_type == "rabi" else 3.0,
    }
    setup_payload = {
        "legacy_run_id": source.legacy_run_id,
        "readout_line": "synthetic-readout-a",
        "drive_line": "synthetic-drive-a",
    }
    _write_json(parameter_path, parameter_payload)
    _write_json(setup_path, setup_payload)
    code_path.parent.mkdir(parents=True, exist_ok=True)
    code_path.write_text(
        (
            "# Synthetic legacy acquisition entrypoint for scenario review.\n"
            f"EXPERIMENT_TYPE = {source.experiment_type!r}\n"
            "def acquire():\n"
            "    return 'legacy-system-owned acquisition'\n"
        ),
        encoding="utf-8",
    )
    analysis_path.parent.mkdir(parents=True, exist_ok=True)
    analysis_path.write_text(
        "metric,value\n"
        f"legacy_run_id,{source.legacy_run_id}\n"
        f"initial_quality,{'reviewable' if source.experiment_type == 'rabi' else 'needs_followup'}\n",
        encoding="utf-8",
    )
    return {
        "parameter_file": _workspace_file_ref(workspace, parameter_path),
        "setup_binding_file": _workspace_file_ref(workspace, setup_path),
        "code_directory": {
            "relative_path": code_dir.relative_to(workspace).as_posix(),
            "size_bytes": None,
            "digest": None,
        },
        "preliminary_analysis_result": _workspace_file_ref(workspace, analysis_path),
    }


def _recorded_reference_inputs(
    source: LegacyScenarioInput,
    artifacts: dict[str, dict[str, Any]],
) -> tuple[RecordedReferenceInput, ...]:
    return (
        RecordedReferenceInput(
            family="parameter_state",
            role="parameter_file",
            reference_kind="workspace_relative_path",
            reference_value=artifacts["parameter_file"]["relative_path"],
            label="Legacy parameter file",
            digest=artifacts["parameter_file"]["digest"],
            size_bytes=artifacts["parameter_file"]["size_bytes"],
        ),
        RecordedReferenceInput(
            family="setup_binding",
            role="setup_binding_file",
            reference_kind="workspace_relative_path",
            reference_value=artifacts["setup_binding_file"]["relative_path"],
            label="Legacy setup binding file",
            digest=artifacts["setup_binding_file"]["digest"],
            size_bytes=artifacts["setup_binding_file"]["size_bytes"],
        ),
        RecordedReferenceInput(
            family="experiment_code",
            role="code_directory",
            reference_kind="workspace_relative_path",
            reference_value=artifacts["code_directory"]["relative_path"],
            label="Legacy acquisition code directory",
        ),
        RecordedReferenceInput(
            family="derived_artifact",
            role="preliminary_analysis_result",
            reference_kind="workspace_relative_path",
            reference_value=artifacts["preliminary_analysis_result"]["relative_path"],
            label="Initial analysis summary",
            digest=artifacts["preliminary_analysis_result"]["digest"],
            size_bytes=artifacts["preliminary_analysis_result"]["size_bytes"],
            preview=f"{source.experiment_type} initial summary",
        ),
    )


def _legacy_rows(source: LegacyScenarioInput) -> tuple[tuple[str, str, str], ...]:
    if source.legacy_run_id == "lv-run-002":
        return (
            ("0", "87", "-1.5"),
            ("120", "119", "-0.5"),
            ("240", "142", "0.5"),
            ("360", "116", "1.5"),
        )
    return (
        ("0", "101", "-2.0"),
        ("100", "128", "-1.0"),
        ("200", "155", "0.0"),
        ("300", "131", "1.0"),
        ("400", "104", "2.0"),
    )


def _write_legacy_tsv(path: Path, *, rows: tuple[tuple[str, str, str], ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
    measurement_runs: list[dict[str, Any]],
    inventory: dict[str, Any],
    operator_review: dict[str, Any],
    operator_review_artifact: dict[str, Any],
) -> dict[str, Any]:
    measurement_review = _measurement_review_model(
        measurement_runs=measurement_runs,
        inventory=inventory,
        operator_review=operator_review,
    )
    record_diagnostics = [
        _record_diagnostics(
            workspace=workspace,
            legacy_run=measurement_run["legacy_run"],
            primary_attach=measurement_run["primary_attach"],
            recorded_reference=measurement_run["recorded_reference"],
        )
        for measurement_run in measurement_runs
    ]
    legacy_runs = [measurement_run["legacy_run"] for measurement_run in measurement_runs]
    primary_attaches = [measurement_run["primary_attach"] for measurement_run in measurement_runs]
    recorded_references = [
        measurement_run["recorded_reference"] for measurement_run in measurement_runs
    ]
    read_views = [measurement_run["read_view"] for measurement_run in measurement_runs]
    user_workflow_runs = [measurement_run["workflow_run"] for measurement_run in measurement_runs]
    return {
        "scenario": "legacy_run_storage_gui",
        "workspace": str(workspace),
        "outputs": {
            "legacy_source_paths": [
                str(measurement_run["legacy_source_path"]) for measurement_run in measurement_runs
            ],
            "normalized_source_paths": [
                str(measurement_run["normalized_source_path"])
                for measurement_run in measurement_runs
            ],
        },
        "user_input": [
            measurement_run["scenario_input"].to_dict() for measurement_run in measurement_runs
        ],
        "generated_ids": [
            measurement_run["scenario_ids"].to_dict() for measurement_run in measurement_runs
        ],
        "workflow": {
            "user_workflow_classifications": [
                workflow_run["workflow"]["classification"] for workflow_run in user_workflow_runs
            ],
            "legacy_record_classifications": [
                legacy_run["workflow"]["classification"] for legacy_run in legacy_runs
            ],
            "primary_attach_classifications": [
                primary_attach["workflow"]["classification"] for primary_attach in primary_attaches
            ],
            "recorded_reference_classifications": [
                recorded_reference["workflow"]["classification"]
                for recorded_reference in recorded_references
            ],
            "inventory_classification": inventory["workflow"]["classification"],
            "read_view_classifications": [
                read_view["workflow"]["classification"] for read_view in read_views
            ],
        },
        "records": {
            "record_ids": [
                measurement_run["scenario_ids"].record_id for measurement_run in measurement_runs
            ],
        },
        "user_workflow_runs": user_workflow_runs,
        "legacy_runs": legacy_runs,
        "primary_attaches": primary_attaches,
        "recorded_references": recorded_references,
        "inventory": inventory,
        "operator_review": operator_review,
        "operator_review_artifact": operator_review_artifact,
        "read_views": read_views,
        "measurement_review": measurement_review,
        "record_diagnostics": record_diagnostics,
    }


def _measurement_review_model(
    *,
    measurement_runs: list[dict[str, Any]],
    inventory: dict[str, Any],
    operator_review: dict[str, Any],
) -> dict[str, Any]:
    entries = {entry["record_id"]: entry for entry in inventory["entries"]}
    recorded_references_by_record = _recorded_references_by_record(operator_review)
    measurements = []
    for measurement_run in measurement_runs:
        legacy_run = measurement_run["legacy_run"]
        primary_attach = measurement_run["primary_attach"]
        read_view = measurement_run["read_view"]
        legacy_request = legacy_run["request"]
        attach_request = primary_attach["request"]
        source_id = attach_request["import_source"]["source_id"]
        attached_to_legacy = source_id == legacy_request["record_id"]
        primary_locator = _first_locator_by_role(legacy_request["locators"], "primary_data")
        legacy_entry = entries[legacy_request["record_id"]]
        preview = read_view["table"]["preview"]
        measurement_id = _slug(
            f"{legacy_request['legacy_system_id']}-{legacy_request['legacy_run_id']}"
        )
        measurements.append(
            {
                "measurement_id": f"meas-{measurement_id}",
                "title": legacy_request.get("label") or legacy_request["legacy_run_id"],
                "kind": "legacy_measurement_with_primary_data",
                "experiment_type": legacy_request.get("experiment_type"),
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
                        "attached_converted_primary_data"
                        if attached_to_legacy
                        else "declared_import_source"
                    ),
                    "normalized_source": attach_request["import_source"]["content_ref"],
                },
                "storage_artifacts": {
                    "record_id": legacy_request["record_id"],
                    "record_dir": legacy_entry["record_dir"],
                    "legacy_receipt_state": legacy_entry["legacy_run"]["state"],
                    "read_model_state": legacy_entry["read_model"]["state"],
                },
                "recorded_references": recorded_references_by_record.get(
                    legacy_request["record_id"], []
                ),
                "next_action": "review_primary_data_preview",
            }
        )
    return {
        "artifact_posture": "scenario_measurement_review_projection",
        "projection_policy": {
            "input_authority": "scenario_outputs_and_storage_inventory",
            "storage_mutation": "not_performed",
            "relationship_inference": "legacy_primary_attach_source_id_only",
            "scopecat_id_generation": "scenario_local_from_legacy_facts",
            "recursive_relation_traversal": "not_performed",
            "final_gui_contract": "not_defined",
        },
        "measurements": measurements,
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


def _recorded_references_by_record(
    operator_review: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    reference_review = operator_review.get("recorded_references", {})
    for entry in reference_review.get("entries", []):
        grouped.setdefault(entry["record_id"], []).extend(entry["references"])
    return grouped


def _record_diagnostics(
    *,
    workspace: Path,
    legacy_run: dict[str, Any],
    primary_attach: dict[str, Any],
    recorded_reference: dict[str, Any],
) -> dict[str, Any]:
    storage_root = workspace / "storage"
    legacy_request = legacy_run["request"]
    attach_request = primary_attach["request"]
    context_request = recorded_reference["request"]
    artifacts = [
        _record_artifact(
            storage_root,
            order=1,
            role="creation_shell",
            label="Created record shell",
            relative_path=legacy_request["creation_manifest_path"],
        ),
        _record_artifact(
            storage_root,
            order=2,
            role="legacy_facts_receipt",
            label="Recorded legacy facts",
            relative_path=legacy_request["legacy_receipt_path"],
        ),
        _record_artifact(
            storage_root,
            order=3,
            role="attached_primary_data",
            label="Attached converted primary data",
            relative_path=attach_request["primary_data_path"],
        ),
        _record_artifact(
            storage_root,
            order=4,
            role="writer_receipt",
            label="Accepted primary data write",
            relative_path=attach_request["writer_receipt_path"],
        ),
        _record_artifact(
            storage_root,
            order=5,
            role="finalization_receipt",
            label="Finalized review state",
            relative_path=attach_request["finalization_receipt_path"],
        ),
        _record_artifact(
            storage_root,
            order=6,
            role="read_model_projection",
            label="Projected review model",
            relative_path=attach_request["read_model_path"],
        ),
        _record_artifact(
            storage_root,
            order=7,
            role="recorded_reference_receipt",
            label="Recorded references",
            relative_path=context_request["reference_receipt_path"],
        ),
    ]
    return {
        "artifact_posture": "scenario_record_artifact_diagnostics",
        "record_id": legacy_request["record_id"],
        "record_dir": legacy_request["record_dir"],
        "diagnostics_policy": {
            "input_authority": "scenario_known_record_local_artifact_paths",
            "storage_mutation": "not_performed",
            "history_semantics": "not_claimed",
            "audit_log_semantics": "not_claimed",
            "complete_update_discovery": "not_performed",
            "final_gui_contract": "not_defined",
        },
        "artifacts": artifacts,
    }


def _record_artifact(
    storage_root: Path,
    *,
    order: int,
    role: str,
    label: str,
    relative_path: str,
) -> dict[str, Any]:
    path = storage_root / relative_path
    if path.is_symlink():
        return {
            "order": order,
            "role": role,
            "label": label,
            "state": "symlink",
            "path": relative_path,
            "size_bytes": None,
            "digest": None,
        }
    if not path.exists():
        return {
            "order": order,
            "role": role,
            "label": label,
            "state": "missing",
            "path": relative_path,
            "size_bytes": None,
            "digest": None,
        }
    content = path.read_bytes()
    return {
        "order": order,
        "role": role,
        "label": label,
        "state": "present",
        "path": relative_path,
        "size_bytes": len(content),
        "digest": f"sha256:{hashlib.sha256(content).hexdigest()}",
    }


def _html_review(summary: dict[str, Any]) -> str:
    measurement_review = summary["measurement_review"]
    inventory_entries = summary["inventory"]["entries"]
    record_diagnostics = summary["record_diagnostics"]
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
    h3 {{
      font-size: 14px;
      margin: 16px 0 8px;
    }}
    h4 {{
      font-size: 13px;
      margin: 12px 0 6px;
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
    <p class="subtitle">Legacy runs recorded, converted to normalized primary data, and shown as user-facing measurements.</p>
    <section class="summary">
      {_status_tile("Measurements", len(measurement_review["measurements"]))}
      {_status_tile("Legacy records", _classification_summary(summary["workflow"]["legacy_record_classifications"]))}
      {_status_tile("Primary attach", _classification_summary(summary["workflow"]["primary_attach_classifications"]))}
      {_status_tile("Recorded references", _classification_summary(summary["workflow"]["recorded_reference_classifications"]))}
      {_status_tile("Inventory", summary["workflow"]["inventory_classification"])}
      {_status_tile("Read views", _classification_summary(summary["workflow"]["read_view_classifications"]))}
    </section>
    <h2>Measurements</h2>
    {_measurement_cards(measurement_review["measurements"])}
    <h2>Recorded References</h2>
    {_recorded_reference_sections(measurement_review["measurements"])}
    <h2>Primary Data Preview</h2>
    {_preview_sections(measurement_review["measurements"])}
    <section class="secondary">
      <h2>Storage Diagnostics</h2>
      <h3>Record Artifacts</h3>
      {_record_artifact_sections(record_diagnostics)}
      <h3>Inventory By Record</h3>
      {_inventory_table(inventory_entries)}
    </section>
    <h2>Generated Files</h2>
    {_generated_files_table(summary["outputs"])}
  </main>
</body>
</html>
"""


def _classification_summary(classifications: list[str]) -> str:
    if not classifications:
        return "none"
    if len(set(classifications)) == 1:
        return f"{len(classifications)} {classifications[0]}"
    counts = {
        classification: classifications.count(classification)
        for classification in sorted(set(classifications))
    }
    return ", ".join(f"{count} {classification}" for classification, count in counts.items())


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
          <dt>Rows</dt><dd>{_escape(primary["row_count"] if primary["row_count"] is not None else "not attached")}</dd>
          <dt>Source</dt><dd>{_escape(conversion["relationship"])}</dd>
          <dt>Legacy locator</dt><dd><code>{_escape(locator.get("value", "not declared"))}</code></dd>
          <dt>Scopecat record</dt><dd>{_escape(storage["record_id"])}</dd>
          <dt>Next action</dt><dd>{_escape(measurement["next_action"])}</dd>
        </dl>
      </article>
    """


def _recorded_reference_sections(measurements: list[dict[str, Any]]) -> str:
    sections = []
    for measurement in measurements:
        sections.append(
            f"<h3>{_escape(measurement['title'])}</h3>"
            + _recorded_reference_table(measurement["recorded_references"])
        )
    return "".join(sections)


def _recorded_reference_table(references: list[dict[str, Any]]) -> str:
    if not references:
        return "<p>No recorded references found.</p>"
    rows = []
    for reference in references:
        rows.append(
            "<tr>"
            f"<td>{_escape(reference['family'])}</td>"
            f"<td>{_escape(reference['role'])}</td>"
            f"<td>{_escape(reference.get('label'))}</td>"
            f"<td>{_escape(reference['reference_kind'])}</td>"
            f"<td><code>{_escape(reference['reference_value'])}</code></td>"
            f"<td>{_escape(reference['state'])}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>Family</th><th>Role</th><th>Label</th><th>Reference</th><th>Value</th><th>State</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _record_artifact_sections(record_diagnostics: list[dict[str, Any]]) -> str:
    sections = []
    for diagnostics in record_diagnostics:
        sections.append(
            f"<h4>{_escape(diagnostics['record_id'])}</h4>"
            + _record_artifacts_table(diagnostics["artifacts"])
        )
    return "".join(sections)


def _record_artifacts_table(artifacts: list[dict[str, Any]]) -> str:
    rows = []
    for artifact in artifacts:
        rows.append(
            "<tr>"
            f"<td>{_escape(artifact['order'])}</td>"
            f"<td>{_escape(artifact['label'])}</td>"
            f"<td>{_escape(artifact['state'])}</td>"
            f"<td>{_escape(artifact['role'])}</td>"
            f"<td><code>{_escape(artifact['path'])}</code></td>"
            f"<td>{_escape(artifact['size_bytes'] if artifact['size_bytes'] is not None else '')}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>#</th><th>Artifact</th><th>State</th><th>Role</th><th>Path</th><th>Bytes</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _preview_sections(measurements: list[dict[str, Any]]) -> str:
    sections = []
    for measurement in measurements:
        primary = measurement["primary_data"]
        sections.append(
            f"<h3>{_escape(measurement['title'])}</h3>"
            + _preview_table(primary["columns"], primary["preview_rows"])
        )
    return "".join(sections)


def _generated_files_table(outputs: dict[str, list[str]]) -> str:
    rows = []
    for label, paths in (
        ("Legacy source", outputs["legacy_source_paths"]),
        ("Normalized source", outputs["normalized_source_paths"]),
    ):
        for path in paths:
            rows.append(f"<tr><th>{_escape(label)}</th><td><code>{_escape(path)}</code></td></tr>")
    return "<table><tbody>" + "".join(rows) + "</tbody></table>"


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
        "<th>Record</th><th>Source</th><th>Lifecycle</th><th>Manifest primary</th>"
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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _workspace_file_ref(workspace: Path, path: Path) -> dict[str, Any]:
    return {
        "relative_path": path.relative_to(workspace).as_posix(),
        "size_bytes": path.stat().st_size,
        "digest": _sha256_file(path),
    }


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
        "measurements": [
            {
                "measurement_id": measurement["measurement_id"],
                "legacy_system_id": measurement["legacy"]["legacy_system_id"],
                "legacy_run_id": measurement["legacy"]["legacy_run_id"],
            }
            for measurement in result.summary["measurement_review"]["measurements"]
        ],
        "diagnostic_records": result.summary["records"],
        "html_review": str(result.html_path),
        "operator_review_html": str(result.operator_review_html_path),
        "scenario_summary": str(result.summary_path),
    }


if __name__ == "__main__":
    raise SystemExit(main())
