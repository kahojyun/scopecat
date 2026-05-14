#!/usr/bin/env python3
"""Fixture-sized JC-002 handoff snapshot reader prototype.

This prototype validates a public-safe synthetic handoff snapshot. It reads an
already-created snapshot, verifies included artifacts, exposes notebook-ready
run and group objects, and renders local summary or plot outputs outside the
snapshot directory. It does not export from a control computer, execute user
code, inspect hardware, access a network, or generate artifacts inside the
snapshot.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MANIFEST_NAME = "snapshot-manifest.json"

INCLUDED_ROLES = {
    "primary_data",
    "required_read_sidecar",
    "handoff_context",
    "user_attached_derived_input",
}
REFERENCE_ROLES = {"calibration_or_correction_reference"}
EXCLUDED_ROLES = {
    "analysis_output",
    "report_artifact",
    "internal_verification_reference",
    "unknown",
}
ALLOWED_ROLES = INCLUDED_ROLES | REFERENCE_ROLES | EXCLUDED_ROLES
ALLOWED_HANDLINGS = {"included", "referenced", "excluded"}
MISSING_STATUSES = {"not_provided", "unknown", "not_applicable", "redacted"}
VALUE_STATUSES = {"provided", "not_provided", "unknown", "not_applicable", "redacted"}
STATUSES_WITHOUT_VALUE = {"not_provided", "unknown", "not_applicable"}

REDACTION_PATTERNS = {
    "private absolute path": re.compile(r"(/Users/|/home/|[A-Za-z]:\\)"),
    "internal network address": re.compile(
        r"\b(10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+)\b"
    ),
    "instrument address": re.compile(r"\b(GPIB|TCPIP|USB\d*::|ASRL\d*::)", re.IGNORECASE),
    "likely username path": re.compile(r"\b(kahoj|alice|bob|charlie)\b", re.IGNORECASE),
}


class HandoffSnapshotError(RuntimeError):
    """Prototype-scoped snapshot validation or read error."""


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    role: str
    handling: str
    path: str | None
    reference: str | None


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise HandoffSnapshotError(f"{path} must contain a JSON object")
    return payload


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HandoffSnapshotError(f"{label} must be an object")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise HandoffSnapshotError(f"{label} must be a list")
    return value


def status_label(value: Any) -> str | None:
    if isinstance(value, dict) and isinstance(value.get("status"), str):
        return value["status"]
    return None


def status_value(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("value")
    return value


def validate_status_object(value: Any, label: str) -> None:
    payload = require_dict(value, label)
    status = payload.get("status")
    if status not in VALUE_STATUSES:
        raise HandoffSnapshotError(f"{label} has invalid status")
    has_value = "value" in payload and payload["value"] is not None
    if status == "provided" and not has_value:
        raise HandoffSnapshotError(f"{label} status provided requires value")
    if status in STATUSES_WITHOUT_VALUE and has_value:
        raise HandoffSnapshotError(f"{label} status {status} must not carry value")
    if status == "redacted" and has_value:
        redacted_value = payload["value"]
        if not isinstance(redacted_value, str) or not redacted_value.startswith("redacted"):
            raise HandoffSnapshotError(f"{label} redacted value must use redacted marker")


def artifact_record(artifact: dict[str, Any]) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=str(artifact.get("artifact_id", "")),
        role=str(artifact.get("role", "")),
        handling=str(artifact.get("handling", "")),
        path=artifact.get("path") if isinstance(artifact.get("path"), str) else None,
        reference=artifact.get("reference") if isinstance(artifact.get("reference"), str) else None,
    )


class HandoffSnapshot:
    """Read-only view over one fixture-sized JC-002 handoff snapshot."""

    def __init__(self, root: Path, manifest: dict[str, Any]):
        self.root = root
        self.manifest = manifest
        self.runs = require_list(manifest.get("runs"), "runs")
        self.artifacts = require_list(manifest.get("artifacts"), "artifacts")
        self.artifacts_by_id = {
            require_dict(artifact, "artifact")["artifact_id"]: require_dict(artifact, "artifact")
            for artifact in self.artifacts
        }
        self.runs_by_id = {
            require_dict(run, "run")["public_run_id"]: require_dict(run, "run") for run in self.runs
        }
        self.validate()

    @classmethod
    def open(cls, root: Path | str) -> "HandoffSnapshot":
        snapshot_root = Path(root)
        manifest_path = snapshot_root / MANIFEST_NAME
        if not manifest_path.exists():
            raise HandoffSnapshotError(f"missing {MANIFEST_NAME}")
        return cls(snapshot_root, read_json(manifest_path))

    def snapshot_path(self, raw_path: str, label: str) -> Path:
        if "\\" in raw_path:
            raise HandoffSnapshotError(f"{label} must use portable relative path")
        if re.match(r"^[A-Za-z]:[/\\]", raw_path):
            raise HandoffSnapshotError(f"{label} must not be an absolute path")
        relative_path = Path(raw_path)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise HandoffSnapshotError(f"{label} must stay inside snapshot")
        root = self.root.resolve()
        candidate = (root / relative_path).resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise HandoffSnapshotError(f"{label} must stay inside snapshot") from exc
        return candidate

    def validate(self) -> None:
        required_top_level = {
            "snapshot_id",
            "created_at",
            "producer",
            "source_system",
            "redaction_policy",
            "selection",
            "runs",
            "artifacts",
            "safety_evidence",
        }
        missing = sorted(required_top_level - self.manifest.keys())
        if missing:
            raise HandoffSnapshotError(f"missing manifest keys: {', '.join(missing)}")

        if len(self.artifacts_by_id) != len(self.artifacts):
            raise HandoffSnapshotError("artifact IDs must be unique")
        if len(self.runs_by_id) != len(self.runs):
            raise HandoffSnapshotError("public run IDs must be unique")

        selection = require_dict(self.manifest["selection"], "selection")
        validate_status_object(selection.get("selected_by"), "selection.selected_by")
        validate_status_object(selection.get("selected_reason"), "selection.selected_reason")
        group_order = require_list(selection.get("group_order"), "selection.group_order")
        if group_order != list(self.runs_by_id.keys()):
            raise HandoffSnapshotError("selection.group_order must match run order")

        source_system = require_dict(self.manifest["source_system"], "source_system")
        validate_status_object(source_system.get("station_id"), "source_system.station_id")
        validate_status_object(
            source_system.get("control_computer"), "source_system.control_computer"
        )

        for run in self.runs:
            self._validate_run(run)
        for artifact in self.artifacts:
            self._validate_artifact(artifact)
        self._validate_safety()

    def _validate_run(self, run: dict[str, Any]) -> None:
        run_id = run.get("public_run_id")
        if not isinstance(run_id, str) or not run_id:
            raise HandoffSnapshotError("run requires public_run_id")
        source_id = require_dict(run.get("source_id"), f"run {run_id} source_id")
        if not isinstance(source_id.get("namespace"), str) or not source_id["namespace"]:
            raise HandoffSnapshotError(f"run {run_id} source_id requires namespace")
        if not isinstance(source_id.get("local_id"), str) or not source_id["local_id"]:
            raise HandoffSnapshotError(f"run {run_id} source_id requires local_id")
        for key in (
            "acquisition_time",
            "measurement_label",
            "original_path_evidence",
            "sample_label",
            "device_label",
        ):
            validate_status_object(run.get(key), f"run {run_id} {key}")
        for parameter in require_list(
            run.get("important_parameters"), f"run {run_id} important_parameters"
        ):
            parameter_name = parameter.get("name")
            if not isinstance(parameter_name, str) or not parameter_name:
                raise HandoffSnapshotError(f"run {run_id} parameter requires name")
            validate_status_object(parameter, f"run {run_id} parameter {parameter_name}")
        primary = self.artifacts_by_id.get(run.get("primary_artifact_id"))
        if primary is None:
            raise HandoffSnapshotError(f"run {run_id} primary artifact is missing")
        if primary.get("role") != "primary_data":
            raise HandoffSnapshotError(f"run {run_id} primary artifact must be primary_data")
        if primary.get("handling") != "included":
            raise HandoffSnapshotError(f"run {run_id} primary artifact must be included")
        if run_id not in primary.get("source_run_relation", []):
            raise HandoffSnapshotError(f"run {run_id} primary artifact relation is missing")
        for sidecar_id in require_list(
            run.get("required_sidecar_artifact_ids"), f"run {run_id} required sidecars"
        ):
            artifact = self.artifacts_by_id.get(sidecar_id)
            if artifact is None or artifact.get("role") != "required_read_sidecar":
                raise HandoffSnapshotError(f"run {run_id} sidecar {sidecar_id} is missing")
            if artifact.get("handling") != "included":
                raise HandoffSnapshotError(f"run {run_id} sidecar {sidecar_id} must be included")
            if artifact.get("applies_to_artifact_id") != primary["artifact_id"]:
                raise HandoffSnapshotError(f"run {run_id} sidecar {sidecar_id} relation mismatch")
            self._validate_sidecar_content(artifact, primary)

    def _validate_artifact(self, artifact: dict[str, Any]) -> None:
        record = artifact_record(artifact)
        if not record.artifact_id:
            raise HandoffSnapshotError("artifact requires artifact_id")
        if record.role not in ALLOWED_ROLES:
            raise HandoffSnapshotError(f"artifact {record.artifact_id} has unknown role")
        if record.handling not in ALLOWED_HANDLINGS:
            raise HandoffSnapshotError(f"artifact {record.artifact_id} has unknown handling")

        if record.handling == "included":
            if record.role not in INCLUDED_ROLES:
                raise HandoffSnapshotError(
                    f"artifact {record.artifact_id} role {record.role} "
                    "cannot be included by default"
                )
            if record.path is None:
                raise HandoffSnapshotError(f"included artifact {record.artifact_id} requires path")
            artifact_path = self.snapshot_path(record.path, f"artifact {record.artifact_id} path")
            if not artifact_path.is_file():
                raise HandoffSnapshotError(f"included artifact {record.artifact_id} is missing")
            if artifact_path.stat().st_size != artifact.get("size_bytes"):
                raise HandoffSnapshotError(f"included artifact {record.artifact_id} size mismatch")
            if file_sha256(artifact_path) != artifact.get("sha256"):
                raise HandoffSnapshotError(
                    f"included artifact {record.artifact_id} checksum mismatch"
                )
            self._validate_source_run_relation(artifact)
            if record.role == "primary_data":
                self._validate_primary_data_artifact(artifact)
            if record.role == "user_attached_derived_input":
                if not artifact.get("processed_status"):
                    raise HandoffSnapshotError(
                        f"derived input {record.artifact_id} requires processed_status"
                    )
                if not artifact.get("human_production_note"):
                    raise HandoffSnapshotError(
                        f"derived input {record.artifact_id} requires human_production_note"
                    )
        elif record.handling == "referenced":
            if record.role not in REFERENCE_ROLES:
                raise HandoffSnapshotError(
                    f"artifact {record.artifact_id} role {record.role} cannot be reference-only"
                )
            if not record.reference:
                raise HandoffSnapshotError(
                    f"referenced artifact {record.artifact_id} requires reference"
                )
            self._validate_source_run_relation(artifact)
        else:
            if record.role not in EXCLUDED_ROLES:
                raise HandoffSnapshotError(
                    f"artifact {record.artifact_id} role {record.role} cannot be excluded here"
                )
            if not artifact.get("exclusion_reason"):
                raise HandoffSnapshotError(
                    f"excluded artifact {record.artifact_id} requires reason"
                )
            self._validate_source_run_relation(artifact)

    def _validate_source_run_relation(self, artifact: dict[str, Any]) -> None:
        relations = require_list(
            artifact.get("source_run_relation"),
            f"artifact {artifact.get('artifact_id')} source_run_relation",
        )
        if not relations:
            raise HandoffSnapshotError(
                f"artifact {artifact.get('artifact_id')} source_run_relation is empty"
            )
        unknown_runs = sorted(run_id for run_id in relations if run_id not in self.runs_by_id)
        if unknown_runs:
            raise HandoffSnapshotError(
                f"artifact {artifact.get('artifact_id')} relation references unknown run"
            )

    def _validate_primary_data_artifact(self, artifact: dict[str, Any]) -> None:
        rows, fieldnames = self._read_csv_rows(artifact)
        axes = require_list(artifact.get("axes"), f"artifact {artifact['artifact_id']} axes")
        values = require_list(artifact.get("values"), f"artifact {artifact['artifact_id']} values")
        shape = require_list(artifact.get("shape"), f"artifact {artifact['artifact_id']} shape")
        if shape != [len(rows), len(fieldnames)]:
            raise HandoffSnapshotError(f"artifact {artifact['artifact_id']} shape mismatch")
        declared_columns: set[str] = set()
        for label, entries in (("axis", axes), ("value", values)):
            if not entries:
                raise HandoffSnapshotError(
                    f"artifact {artifact['artifact_id']} requires {label} metadata"
                )
            for entry in entries:
                entry_dict = require_dict(entry, f"artifact {artifact['artifact_id']} {label}")
                column = entry_dict.get("column")
                if not isinstance(column, str) or column not in fieldnames:
                    raise HandoffSnapshotError(
                        f"artifact {artifact['artifact_id']} {label} column mismatch"
                    )
                if not entry_dict.get("name") or not entry_dict.get("unit"):
                    raise HandoffSnapshotError(
                        f"artifact {artifact['artifact_id']} {label} requires name and unit"
                    )
                declared_columns.add(column)
        if not declared_columns.issubset(set(fieldnames)):
            raise HandoffSnapshotError(f"artifact {artifact['artifact_id']} column mismatch")

    def _validate_sidecar_content(
        self, sidecar_artifact: dict[str, Any], primary_artifact: dict[str, Any]
    ) -> None:
        sidecar = self._load_sidecar(sidecar_artifact["artifact_id"])
        if sidecar.get("applies_to_artifact_id") != primary_artifact["artifact_id"]:
            raise HandoffSnapshotError(
                f"sidecar {sidecar_artifact['artifact_id']} content relation mismatch"
            )
        sidecar_columns = {
            require_dict(column, "sidecar column").get("name")
            for column in require_list(sidecar.get("columns"), "sidecar columns")
        }
        required_columns = {
            entry["column"]
            for entry in primary_artifact.get("axes", []) + primary_artifact.get("values", [])
        }
        if not required_columns.issubset(sidecar_columns):
            raise HandoffSnapshotError(
                f"sidecar {sidecar_artifact['artifact_id']} does not cover primary columns"
            )

    def _validate_safety(self) -> None:
        safety = require_dict(self.manifest["safety_evidence"], "safety_evidence")
        for key, value in safety.items():
            if value is not False:
                raise HandoffSnapshotError(f"safety evidence {key} must be false in this fixture")

    def load_run(self, run_id: str) -> dict[str, Any]:
        run = self.runs_by_id.get(run_id)
        if run is None:
            raise HandoffSnapshotError(f"unknown run {run_id}")
        primary = self.artifacts_by_id[run["primary_artifact_id"]]
        rows = self._read_primary_csv(primary)
        sidecars = [
            self._load_sidecar(sidecar_id)
            for sidecar_id in run.get("required_sidecar_artifact_ids", [])
        ]
        return {
            "run_id": run_id,
            "source_id": run["source_id"],
            "condition_label": run["condition_label"],
            "measurement_label": status_value(run["measurement_label"]),
            "data": rows,
            "axes": primary["axes"],
            "values": primary["values"],
            "shape": primary["shape"],
            "sidecars": sidecars,
            "derived_inputs": self.derived_inputs_for_run(run_id),
            "warnings": self.run_warnings(run),
        }

    def load_group(self) -> dict[str, Any]:
        selection = require_dict(self.manifest["selection"], "selection")
        run_ids = require_list(selection["group_order"], "selection.group_order")
        loaded_runs = [self.load_run(run_id) for run_id in run_ids]
        return {
            "snapshot_id": self.manifest["snapshot_id"],
            "group_title": selection["group_title"],
            "selected_reason": status_value(selection["selected_reason"]),
            "run_order": run_ids,
            "runs": loaded_runs,
            "derived_inputs": self.derived_inputs_for_run_group(run_ids),
            "shared_context": self.shared_context(),
        }

    def derived_inputs_for_run(self, run_id: str) -> list[dict[str, Any]]:
        return [
            self._load_included_json_artifact(artifact)
            | {
                "artifact_id": artifact["artifact_id"],
                "role": artifact["role"],
                "source_run_relation": artifact["source_run_relation"],
                "processed_status": artifact["processed_status"],
                "human_production_note": artifact["human_production_note"],
            }
            for artifact in self.artifacts
            if artifact.get("role") == "user_attached_derived_input"
            and artifact.get("handling") == "included"
            and run_id in artifact.get("source_run_relation", [])
        ]

    def derived_inputs_for_run_group(self, run_ids: list[str]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        derived_inputs: list[dict[str, Any]] = []
        for run_id in run_ids:
            for derived_input in self.derived_inputs_for_run(run_id):
                if derived_input["artifact_id"] not in seen:
                    seen.add(derived_input["artifact_id"])
                    derived_inputs.append(derived_input)
        return derived_inputs

    def run_warnings(self, run: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        for key in ("sample_label", "device_label", "acquisition_time", "measurement_label"):
            status = status_label(run.get(key))
            if status in MISSING_STATUSES:
                warnings.append(f"{key}:{status}")
        for parameter in run.get("important_parameters", []):
            status = parameter.get("status")
            if status in MISSING_STATUSES:
                warnings.append(f"important_parameters.{parameter.get('name')}:{status}")
        return warnings

    def shared_context(self) -> dict[str, Any]:
        return {
            "source_system": self.manifest["source_system"],
            "redaction_profile": self.manifest["redaction_policy"]["profile"],
        }

    def _read_primary_csv(self, artifact: dict[str, Any]) -> list[dict[str, float]]:
        rows, _fieldnames = self._read_csv_rows(artifact)
        return rows

    def _read_csv_rows(self, artifact: dict[str, Any]) -> tuple[list[dict[str, float]], list[str]]:
        artifact_path = self.snapshot_path(
            artifact["path"], f"artifact {artifact['artifact_id']} path"
        )
        with artifact_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            fieldnames = reader.fieldnames or []
        parsed_rows: list[dict[str, float]] = []
        for row in rows:
            parsed_rows.append({key: float(value) for key, value in row.items()})
        return parsed_rows, fieldnames

    def _load_sidecar(self, sidecar_id: str) -> dict[str, Any]:
        artifact = self.artifacts_by_id[sidecar_id]
        path = self.snapshot_path(artifact["path"], f"artifact {sidecar_id} path")
        return read_json(path)

    def _load_included_json_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        path = self.snapshot_path(artifact["path"], f"artifact {artifact['artifact_id']} path")
        return read_json(path)

    def missing_and_redacted_fields(self) -> list[dict[str, str]]:
        fields: list[dict[str, str]] = []
        for run in self.runs:
            run_id = run["public_run_id"]
            for key, value in run.items():
                status = status_label(value)
                if status in MISSING_STATUSES:
                    fields.append({"path": f"runs.{run_id}.{key}", "status": status})
            for parameter in run.get("important_parameters", []):
                status = parameter.get("status")
                if status in MISSING_STATUSES:
                    fields.append(
                        {
                            "path": f"runs.{run_id}.important_parameters.{parameter.get('name')}",
                            "status": status,
                        }
                    )
        selection = require_dict(self.manifest["selection"], "selection")
        for key, value in selection.items():
            status = status_label(value)
            if status in MISSING_STATUSES:
                fields.append({"path": f"selection.{key}", "status": status})
        return sorted(fields, key=lambda item: item["path"])

    def redaction_audit(self) -> dict[str, Any]:
        scanned: dict[str, str] = {
            MANIFEST_NAME: json.dumps(self.manifest, sort_keys=True),
        }
        for artifact in self.artifacts:
            if artifact.get("handling") == "included" and isinstance(artifact.get("path"), str):
                path = self.snapshot_path(
                    artifact["path"], f"artifact {artifact['artifact_id']} path"
                )
                scanned[artifact["path"]] = path.read_text(encoding="utf-8")

        findings: list[dict[str, str]] = []
        for source, text in scanned.items():
            for label, pattern in REDACTION_PATTERNS.items():
                if pattern.search(text):
                    findings.append({"source": source, "kind": label})
        return {
            "status": "pass" if not findings else "fail",
            "findings": findings,
            "scanned_sources": sorted(scanned),
        }

    def summary(self) -> dict[str, Any]:
        missing_fields = self.missing_and_redacted_fields()
        redaction_audit = self.redaction_audit()
        included = [
            artifact_record(artifact)
            for artifact in self.artifacts
            if artifact["handling"] == "included"
        ]
        referenced = [
            artifact_record(artifact)
            for artifact in self.artifacts
            if artifact["handling"] == "referenced"
        ]
        excluded = [artifact for artifact in self.artifacts if artifact["handling"] == "excluded"]
        return {
            "identity": {
                "snapshot_id": self.manifest["snapshot_id"],
                "created_at": self.manifest["created_at"],
                "producer": self.manifest["producer"],
                "source_system": self.manifest["source_system"],
            },
            "can_open": {
                "status": "pass",
                "included_artifact_count": len(included),
                "required_sidecar_count": len(
                    [
                        artifact
                        for artifact in self.artifacts
                        if artifact["role"] == "required_read_sidecar"
                    ]
                ),
            },
            "selection": self.manifest["selection"],
            "runs": [
                {
                    "run_id": run["public_run_id"],
                    "source_namespace": run["source_id"]["namespace"],
                    "source_local_id": run["source_id"]["local_id"],
                    "condition_label": run["condition_label"],
                    "measurement_label": status_value(run["measurement_label"]),
                    "warnings": self.run_warnings(run),
                }
                for run in self.runs
            ],
            "artifacts": {
                "included": [record.__dict__ for record in included],
                "referenced": [record.__dict__ for record in referenced],
                "excluded": [
                    {
                        "artifact_id": artifact["artifact_id"],
                        "role": artifact["role"],
                        "reason": artifact["exclusion_reason"],
                    }
                    for artifact in excluded
                ],
            },
            "missing_fields": missing_fields,
            "redaction": redaction_audit,
            "safety_evidence": self.manifest["safety_evidence"],
            "shareability": {
                "status": "public-safe" if redaction_audit["status"] == "pass" else "blocked",
                "reason": "redaction audit passed"
                if redaction_audit["status"] == "pass"
                else "redaction audit found sensitive text",
            },
        }


def render_markdown(summary: dict[str, Any]) -> str:
    identity = summary["identity"]
    lines = [
        "# JC-002 Handoff Snapshot Summary",
        "",
        "## Identity",
        "",
        f"- Snapshot: `{identity['snapshot_id']}`",
        f"- Created: `{identity['created_at']}`",
        f"- Source type: `{identity['source_system']['type']}`",
        "",
        "## Can Open",
        "",
        f"- Status: {summary['can_open']['status']}",
        f"- Included artifacts: {summary['can_open']['included_artifact_count']}",
        f"- Required sidecars: {summary['can_open']['required_sidecar_count']}",
        "",
        "## Selection",
        "",
        f"- Group: {summary['selection']['group_title']}",
        f"- Reason: {status_value(summary['selection']['selected_reason'])}",
        f"- Order: {', '.join(summary['selection']['group_order'])}",
        "",
        "## Runs",
        "",
    ]
    for run in summary["runs"]:
        warning_text = ", ".join(run["warnings"]) if run["warnings"] else "none"
        lines.append(
            f"- `{run['run_id']}`: {run['condition_label']}, "
            f"{run['measurement_label']}; warnings: {warning_text}"
        )

    lines.extend(["", "## Artifacts", ""])
    for section_name in ("included", "referenced", "excluded"):
        lines.append(f"- {section_name.title()}: {len(summary['artifacts'][section_name])}")

    lines.extend(["", "## Missing And Redacted", ""])
    if summary["missing_fields"]:
        for field in summary["missing_fields"]:
            lines.append(f"- `{field['path']}`: {field['status']}")
    else:
        lines.append("- none")

    lines.extend(["", "## Exclusions", ""])
    for artifact in summary["artifacts"]["excluded"]:
        lines.append(f"- `{artifact['artifact_id']}` ({artifact['role']}): {artifact['reason']}")

    lines.extend(
        [
            "",
            "## Redaction",
            "",
            f"- Status: {summary['redaction']['status']}",
            f"- Scanned sources: {', '.join(summary['redaction']['scanned_sources'])}",
            "",
            "## Safety",
            "",
        ]
    )
    for key, value in summary["safety_evidence"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Shareability",
            "",
            f"- Status: {summary['shareability']['status']}",
            f"- Reason: {summary['shareability']['reason']}",
        ]
    )
    return "\n".join(lines) + "\n"


def render_svg_plot(group: dict[str, Any], output_path: Path, run_id: str | None = None) -> None:
    selected_runs = group["runs"]
    if run_id is not None:
        selected_runs = [run for run in selected_runs if run["run_id"] == run_id]
        if not selected_runs:
            raise HandoffSnapshotError(f"unknown run for plot: {run_id}")

    width = 640
    height = 360
    margin = 48
    first_run = selected_runs[0]
    x_meta = first_run["axes"][0]
    y_meta = first_run["values"][0]
    x_column = x_meta["column"]
    y_column = y_meta["column"]
    x_label = f"{x_meta['name']} ({x_meta['unit']})"
    y_label = f"{y_meta['name']} ({y_meta['unit']})"
    all_x = [row[x_column] for run in selected_runs for row in run["data"]]
    all_y = [row[y_column] for run in selected_runs for row in run["data"]]
    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    y_pad = max((max_y - min_y) * 0.1, 0.01)
    min_y -= y_pad
    max_y += y_pad

    def point(row: dict[str, float]) -> tuple[float, float]:
        x = margin + (row[x_column] - min_x) / (max_x - min_x) * (width - 2 * margin)
        y = height - margin - (row[y_column] - min_y) / (max_y - min_y) * (height - 2 * margin)
        return x, y

    colors = ["#1f77b4", "#d62728", "#2ca02c"]
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">',
        '<rect width="640" height="360" fill="white"/>',
        (
            '<text x="48" y="28" font-family="sans-serif" font-size="16">'
            f"{html.escape(group['group_title'])}</text>"
        ),
        '<line x1="48" y1="312" x2="592" y2="312" stroke="#222"/>',
        '<line x1="48" y1="48" x2="48" y2="312" stroke="#222"/>',
        (
            '<text x="300" y="346" font-family="sans-serif" font-size="12">'
            f"{html.escape(x_label)}</text>"
        ),
        (
            '<text x="8" y="190" font-family="sans-serif" font-size="12" '
            f'transform="rotate(-90 8 190)">{html.escape(y_label)}</text>'
        ),
    ]
    for index, run in enumerate(selected_runs):
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in (point(row) for row in run["data"]))
        color = colors[index % len(colors)]
        label_y = 56 + index * 18
        lines.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"/>')
        lines.append(
            f'<text x="500" y="{label_y}" font-family="sans-serif" font-size="12" '
            f'fill="{color}">{html.escape(run["condition_label"])}</text>'
        )
    lines.append("</svg>")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_outputs(snapshot: HandoffSnapshot, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = snapshot.summary()
    group = snapshot.load_group()

    summary_json = out_dir / "handoff-summary.json"
    summary_md = out_dir / "handoff-summary.md"
    group_json = out_dir / "reader-group.json"
    single_plot = out_dir / "single-run-plot.svg"
    group_plot = out_dir / "group-sanity-plot.svg"

    summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    summary_md.write_text(render_markdown(summary), encoding="utf-8")
    group_json.write_text(json.dumps(group, indent=2, sort_keys=True), encoding="utf-8")
    render_svg_plot(group, single_plot, run_id=group["run_order"][0])
    render_svg_plot(group, group_plot)
    return [summary_json, summary_md, group_json, single_plot, group_plot]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args(argv)

    snapshot = HandoffSnapshot.open(args.snapshot)
    if args.out_dir:
        outputs = write_outputs(snapshot, args.out_dir)
        for path in outputs:
            print(path)
    else:
        print(render_markdown(snapshot.summary()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
