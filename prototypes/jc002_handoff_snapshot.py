#!/usr/bin/env python3
"""Fixture-sized JC-002 handoff snapshot reader prototype.

This prototype validates an already-created JC-002 handoff snapshot. It verifies
included artifacts and exposes notebook-ready run and group objects. The CLI can
write fixture smoke-test summaries and plots to a caller-provided directory. It
does not export from a control computer, decide redaction policy, execute user
code, inspect hardware, or access a network.
"""

from __future__ import annotations

import argparse
import copy
import csv
import datetime as dt
import hashlib
import html
import json
import math
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
    "calibration_or_correction_reference",
    "internal_verification_reference",
    "user_attached_derived_input",
}
REFERENCE_ROLES = {"calibration_or_correction_reference", "internal_verification_reference"}
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
ADVANCED_INCLUDED_ROLES = {
    "calibration_or_correction_reference",
    "internal_verification_reference",
}
REQUIRED_SAFETY_EVIDENCE_KEYS = {
    "source_mutation",
    "code_execution_during_export",
    "notebook_execution_during_export",
    "generated_artifacts_during_export",
    "network_or_cloud_dependency",
    "instrument_or_setup_access",
}
TOP_LEVEL_KEYS = {
    "snapshot_id",
    "created_at",
    "producer",
    "source_system",
    "redaction_status",
    "selection",
    "runs",
    "artifacts",
    "safety_evidence",
}
RUN_KEYS = {
    "public_run_id",
    "source_id",
    "acquisition_time",
    "measurement_label",
    "condition_label",
    "original_path_evidence",
    "sample_label",
    "device_label",
    "important_parameters",
    "primary_artifact_id",
    "required_sidecar_artifact_ids",
}
BASE_ARTIFACT_KEYS = {"artifact_id", "role", "handling", "source_run_relation"}
INCLUDED_PAYLOAD_KEYS = {"path", "size_bytes", "sha256"}
INCLUDED_ARTIFACT_ROLE_KEYS = {
    "primary_data": {"axes", "values", "shape"},
    "required_read_sidecar": {"applies_to_artifact_id"},
    "handoff_context": set(),
    "calibration_or_correction_reference": {"warning"},
    "internal_verification_reference": {"warning"},
    "user_attached_derived_input": {"processed_status", "human_production_note"},
}
REFERENCED_ARTIFACT_ROLE_KEYS = {
    "calibration_or_correction_reference": {"warning"},
    "internal_verification_reference": {"warning"},
}
EXCLUDED_ARTIFACT_ROLE_KEYS = {
    "analysis_output": {"reference"},
    "report_artifact": {"reference"},
    "internal_verification_reference": {"reference", "warning"},
    "unknown": {"reference"},
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


def reject_json_constant(value: str) -> None:
    raise ValueError(f"unsupported JSON constant {value}")


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle, parse_constant=reject_json_constant)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise HandoffSnapshotError(f"{label} could not be read as JSON") from exc
    if not isinstance(payload, dict):
        raise HandoffSnapshotError(f"{label} must contain a JSON object")
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
        if value.get("status") == "redacted":
            return None
        return value.get("value")
    return value


def markdown_text(value: Any) -> str:
    text = "" if value is None else str(value)
    replacements = {
        "\\": r"\\",
        "`": r"\`",
        "*": r"\*",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "[": r"\[",
        "]": r"\]",
        "(": r"\(",
        ")": r"\)",
        "#": r"\#",
        "+": r"\+",
        "-": r"\-",
        ".": r"\.",
        "!": r"\!",
        "<": "&lt;",
        ">": "&gt;",
    }
    return "".join(replacements.get(character, character) for character in text)


def markdown_value(value: Any) -> str:
    if isinstance(value, str):
        return markdown_text(value)
    return markdown_text(json.dumps(value, sort_keys=True))


def validate_status_object(value: Any, label: str, extra_keys: set[str] | None = None) -> None:
    payload = require_dict(value, label)
    allowed_keys = {"status", "value"} | (extra_keys or set())
    unknown_keys = set(payload) - allowed_keys
    if unknown_keys:
        raise HandoffSnapshotError(f"{label} has unknown fields")
    status = payload.get("status")
    if status not in VALUE_STATUSES:
        raise HandoffSnapshotError(f"{label} has invalid status")
    has_value = "value" in payload
    has_non_null_value = has_value and payload["value"] is not None
    if status == "provided" and not has_value:
        raise HandoffSnapshotError(f"{label} status provided requires value")
    if status == "provided" and not has_non_null_value:
        raise HandoffSnapshotError(f"{label} status provided requires value")
    if status == "redacted" and has_value:
        raise HandoffSnapshotError(f"{label} status redacted must not carry value")
    if status in STATUSES_WITHOUT_VALUE and has_value:
        raise HandoffSnapshotError(f"{label} status {status} must not carry value")


def validate_exact_keys(
    value: dict[str, Any],
    required_keys: set[str],
    label: str,
    optional_keys: set[str] | None = None,
) -> None:
    allowed_keys = required_keys | (optional_keys or set())
    if required_keys - set(value):
        return
    unknown_keys = set(value) - allowed_keys
    if unknown_keys:
        raise HandoffSnapshotError(f"{label} has invalid fields")


def validate_text_status_object(value: Any, label: str) -> None:
    validate_status_object(value, label)
    payload = require_dict(value, label)
    if "value" in payload and payload["value"] is not None:
        text = payload.get("value")
        if not isinstance(text, str) or not text:
            raise HandoffSnapshotError(f"{label} requires text value")


def validate_text_or_status(value: Any, label: str) -> None:
    if isinstance(value, dict):
        validate_text_status_object(value, label)
        return
    if not isinstance(value, str) or not value:
        raise HandoffSnapshotError(f"{label} requires text")


def validate_source_id_value(value: Any, label: str) -> None:
    if isinstance(value, dict):
        validate_text_status_object(value, label)
        return
    if not isinstance(value, str) or not value:
        raise HandoffSnapshotError(f"{label} requires text")


def status_or_text_value(value: Any) -> Any:
    if isinstance(value, dict):
        return status_value(value)
    return value


def is_non_bool_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_sha256(value: Any, label: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise HandoffSnapshotError(f"{label} requires sha256")


def validate_timestamp_text(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise HandoffSnapshotError(f"{label} requires timestamp")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T[^Z+-]+(?:Z|[+-]\d{2}:\d{2})", value):
        raise HandoffSnapshotError(f"{label} requires timestamp")
    timestamp = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = dt.datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise HandoffSnapshotError(f"{label} requires timestamp") from exc
    if parsed.tzinfo is None:
        raise HandoffSnapshotError(f"{label} requires timestamp")


def validate_timestamp_status_object(value: Any, label: str) -> None:
    validate_text_status_object(value, label)
    payload = require_dict(value, label)
    if "value" in payload and payload["value"] is not None:
        validate_timestamp_text(payload["value"], label)


def validate_text_field(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise HandoffSnapshotError(f"{label} must be text")


def validate_scalar_value(value: Any, label: str) -> None:
    if not isinstance(value, (str, int, float, bool)) or value is None:
        raise HandoffSnapshotError(f"{label} requires scalar value")
    if isinstance(value, float) and not math.isfinite(value):
        raise HandoffSnapshotError(f"{label} requires scalar value")


def public_copy(value: Any) -> Any:
    return copy.deepcopy(value)


def artifact_record(artifact: dict[str, Any]) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=str(artifact.get("artifact_id", "")),
        role=str(artifact.get("role", "")),
        handling=str(artifact.get("handling", "")),
        path=artifact.get("path") if isinstance(artifact.get("path"), str) else None,
        reference=artifact.get("reference") if isinstance(artifact.get("reference"), str) else None,
    )


def artifact_summary_record(artifact: dict[str, Any]) -> dict[str, Any]:
    record = artifact_record(artifact).__dict__
    if artifact.get("handling") != "included":
        record["path"] = None
    record["source_run_relation"] = public_copy(artifact["source_run_relation"])
    if artifact.get("handling") in {"referenced", "excluded"} and artifact.get("reference"):
        record["reference"] = artifact["reference"]
    if artifact.get("warning"):
        record["warning"] = artifact["warning"]
    if artifact.get("handling") == "included":
        record["size_bytes"] = artifact["size_bytes"]
        record["sha256"] = artifact["sha256"]
    if artifact.get("role") == "required_read_sidecar":
        record["applies_to_artifact_id"] = artifact["applies_to_artifact_id"]
    if artifact.get("role") == "user_attached_derived_input":
        record["processed_status"] = artifact["processed_status"]
        record["human_production_note"] = artifact["human_production_note"]
    if artifact.get("handling") == "excluded":
        record["reason"] = artifact["exclusion_reason"]
    return record


class HandoffSnapshot:
    """Read-only view over one fixture-sized JC-002 handoff snapshot."""

    def __init__(self, root: Path, manifest: dict[str, Any]):
        self.root = root
        self.manifest = manifest
        self.runs = require_list(manifest.get("runs"), "runs")
        self.artifacts = require_list(manifest.get("artifacts"), "artifacts")
        for artifact in self.artifacts:
            artifact_dict = require_dict(artifact, "artifact")
            artifact_id = artifact_dict.get("artifact_id")
            if not isinstance(artifact_id, str) or not artifact_id:
                raise HandoffSnapshotError("artifact requires artifact_id")
        for run in self.runs:
            run_dict = require_dict(run, "run")
            run_id = run_dict.get("public_run_id")
            if not isinstance(run_id, str) or not run_id:
                raise HandoffSnapshotError("run requires public_run_id")
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
        snapshot_root = Path(root).resolve()
        manifest_path = snapshot_root / MANIFEST_NAME
        if not manifest_path.exists():
            raise HandoffSnapshotError(f"missing {MANIFEST_NAME}")
        if manifest_path.is_symlink():
            raise HandoffSnapshotError(f"{MANIFEST_NAME} must not be a symlink")
        return cls(snapshot_root, read_json(manifest_path, MANIFEST_NAME))

    def snapshot_path(self, raw_path: str, label: str) -> Path:
        if "\\" in raw_path:
            raise HandoffSnapshotError(f"{label} must use portable relative path")
        if re.match(r"^[A-Za-z]:", raw_path):
            raise HandoffSnapshotError(f"{label} must not use Windows drive path")
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
        missing = sorted(TOP_LEVEL_KEYS - self.manifest.keys())
        if missing:
            raise HandoffSnapshotError(f"missing manifest keys: {', '.join(missing)}")
        validate_exact_keys(self.manifest, TOP_LEVEL_KEYS, "manifest")

        if not isinstance(self.manifest["snapshot_id"], str) or not self.manifest["snapshot_id"]:
            raise HandoffSnapshotError("snapshot_id must be a non-empty string")
        validate_timestamp_text(self.manifest["created_at"], "created_at")
        producer = require_dict(self.manifest["producer"], "producer")
        validate_exact_keys(producer, {"name", "version"}, "producer")
        if not isinstance(producer.get("name"), str) or not producer["name"]:
            raise HandoffSnapshotError("producer requires name")
        if not isinstance(producer.get("version"), str) or not producer["version"]:
            raise HandoffSnapshotError("producer requires version")

        if len(self.artifacts_by_id) != len(self.artifacts):
            raise HandoffSnapshotError("artifact IDs must be unique")
        if len(self.runs_by_id) != len(self.runs):
            raise HandoffSnapshotError("public run IDs must be unique")
        if not self.runs:
            raise HandoffSnapshotError("snapshot requires at least one run")

        selection = require_dict(self.manifest["selection"], "selection")
        validate_exact_keys(
            selection,
            {"selected_by", "selected_reason", "group_title", "group_order", "per_run_notes"},
            "selection",
        )
        validate_text_status_object(selection.get("selected_by"), "selection.selected_by")
        validate_text_status_object(selection.get("selected_reason"), "selection.selected_reason")
        if not isinstance(selection.get("group_title"), str) or not selection["group_title"]:
            raise HandoffSnapshotError("selection requires group_title")
        group_order = require_list(selection.get("group_order"), "selection.group_order")
        if any(not isinstance(run_id, str) or not run_id for run_id in group_order):
            raise HandoffSnapshotError("selection.group_order must use run IDs")
        if len(set(group_order)) != len(group_order):
            raise HandoffSnapshotError("selection.group_order must not contain duplicates")
        if set(group_order) != set(self.runs_by_id):
            raise HandoffSnapshotError("selection.group_order must match selected runs")
        per_run_notes = require_dict(selection.get("per_run_notes"), "selection.per_run_notes")
        if set(per_run_notes) != set(group_order):
            raise HandoffSnapshotError("selection.per_run_notes must match group order")
        for run_id, note in per_run_notes.items():
            validate_text_status_object(note, f"selection.per_run_notes.{run_id}")

        source_system = require_dict(self.manifest["source_system"], "source_system")
        validate_exact_keys(
            source_system,
            {"type", "station_id", "control_computer"},
            "source_system",
        )
        if not isinstance(source_system.get("type"), str) or not source_system["type"]:
            raise HandoffSnapshotError("source_system requires type")
        validate_text_status_object(source_system.get("station_id"), "source_system.station_id")
        validate_text_status_object(
            source_system.get("control_computer"), "source_system.control_computer"
        )
        require_dict(self.manifest["redaction_status"], "redaction_status")

        for run in self.runs:
            self._validate_run_artifact_ids(run)
        self._validate_unique_primary_artifacts()
        for artifact in self.artifacts:
            self._validate_artifact(artifact)
        for run in self.runs:
            self._validate_run(run)
        self._validate_unique_concrete_source_ids()
        self._validate_primary_data_ownership()
        self._validate_safety()

    def _validate_run(self, run: dict[str, Any]) -> None:
        run_id = run.get("public_run_id")
        if not isinstance(run_id, str) or not run_id:
            raise HandoffSnapshotError("run requires public_run_id")
        validate_exact_keys(run, RUN_KEYS, f"run {run_id}")
        source_id = require_dict(run.get("source_id"), f"run {run_id} source_id")
        validate_exact_keys(source_id, {"namespace", "local_id"}, f"run {run_id} source_id")
        validate_source_id_value(source_id.get("namespace"), f"run {run_id} source_id namespace")
        validate_source_id_value(source_id.get("local_id"), f"run {run_id} source_id local_id")
        source_system = require_dict(self.manifest["source_system"], "source_system")
        station_id = require_dict(source_system.get("station_id"), "source_system.station_id")
        station_value = status_value(station_id)
        source_system_type = source_system["type"]
        source_namespace = status_or_text_value(source_id.get("namespace"))
        allowed_namespaces = {source_system_type}
        if isinstance(station_value, str):
            allowed_namespaces.add(station_value)
        if isinstance(source_namespace, str) and source_namespace not in allowed_namespaces:
            raise HandoffSnapshotError(f"run {run_id} source_id namespace mismatch")
        if not isinstance(run.get("condition_label"), str) or not run["condition_label"]:
            raise HandoffSnapshotError(f"run {run_id} requires condition_label")
        for key in (
            "measurement_label",
            "original_path_evidence",
            "sample_label",
            "device_label",
        ):
            validate_text_status_object(run.get(key), f"run {run_id} {key}")
        validate_timestamp_status_object(
            run.get("acquisition_time"), f"run {run_id} acquisition_time"
        )
        parameter_names: set[str] = set()
        for parameter in require_list(
            run.get("important_parameters"), f"run {run_id} important_parameters"
        ):
            parameter_dict = require_dict(parameter, f"run {run_id} parameter")
            parameter_name = parameter_dict.get("name")
            if not isinstance(parameter_name, str) or not parameter_name:
                raise HandoffSnapshotError(f"run {run_id} parameter requires name")
            if parameter_name in parameter_names:
                raise HandoffSnapshotError(f"run {run_id} parameter names must be unique")
            parameter_names.add(parameter_name)
            if "unit" in parameter_dict and (
                not isinstance(parameter_dict.get("unit"), str) or not parameter_dict["unit"]
            ):
                raise HandoffSnapshotError(f"run {run_id} parameter {parameter_name} unit mismatch")
            if parameter_dict.get("status") == "provided":
                validate_scalar_value(
                    parameter_dict.get("value"),
                    f"run {run_id} parameter {parameter_name}",
                )
            validate_status_object(
                parameter_dict,
                f"run {run_id} parameter {parameter_name}",
                extra_keys={"name", "unit"},
            )
        primary_artifact_id = run["primary_artifact_id"]
        primary = self.artifacts_by_id.get(primary_artifact_id)
        if primary is None:
            raise HandoffSnapshotError(f"run {run_id} primary artifact is missing")
        if primary.get("role") != "primary_data":
            raise HandoffSnapshotError(f"run {run_id} primary artifact must be primary_data")
        if primary.get("handling") != "included":
            raise HandoffSnapshotError(f"run {run_id} primary artifact must be included")
        if run_id not in primary.get("source_run_relation", []):
            raise HandoffSnapshotError(f"run {run_id} primary artifact relation is missing")
        expected_primary_runs = sorted(
            candidate["public_run_id"]
            for candidate in self.runs
            if candidate.get("primary_artifact_id") == primary["artifact_id"]
        )
        if sorted(primary.get("source_run_relation", [])) != expected_primary_runs:
            raise HandoffSnapshotError(f"run {run_id} primary artifact relation mismatch")
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
            if run_id not in artifact.get("source_run_relation", []):
                raise HandoffSnapshotError(f"run {run_id} sidecar {sidecar_id} relation mismatch")
            self._validate_sidecar_content(artifact, primary)

    def _validate_run_artifact_ids(self, run: dict[str, Any]) -> None:
        run_id = run.get("public_run_id")
        primary_artifact_id = run.get("primary_artifact_id")
        if not isinstance(primary_artifact_id, str) or not primary_artifact_id:
            raise HandoffSnapshotError(f"run {run_id} requires primary_artifact_id")
        sidecar_ids = require_list(
            run.get("required_sidecar_artifact_ids"), f"run {run_id} required sidecars"
        )
        for sidecar_id in sidecar_ids:
            if not isinstance(sidecar_id, str) or not sidecar_id:
                raise HandoffSnapshotError(f"run {run_id} required sidecars must use IDs")
        if len(set(sidecar_ids)) != len(sidecar_ids):
            raise HandoffSnapshotError(f"run {run_id} required sidecars has duplicates")

    def _validate_unique_primary_artifacts(self) -> None:
        primary_ids = [run["primary_artifact_id"] for run in self.runs]
        if len(set(primary_ids)) != len(primary_ids):
            raise HandoffSnapshotError("selected runs must use distinct primary artifacts")

    def _validate_unique_concrete_source_ids(self) -> None:
        concrete_source_ids: set[tuple[str, str]] = set()
        for run in self.runs:
            source_id = require_dict(run.get("source_id"), "run source_id")
            namespace = status_or_text_value(source_id.get("namespace"))
            local_id = status_or_text_value(source_id.get("local_id"))
            if not isinstance(namespace, str) or not isinstance(local_id, str):
                continue
            source_key = (namespace, local_id)
            if source_key in concrete_source_ids:
                raise HandoffSnapshotError("selected runs must use distinct source IDs")
            concrete_source_ids.add(source_key)

    def _validate_artifact(self, artifact: dict[str, Any]) -> None:
        record = artifact_record(artifact)
        if not record.artifact_id:
            raise HandoffSnapshotError("artifact requires artifact_id")
        if record.role not in ALLOWED_ROLES:
            raise HandoffSnapshotError(f"artifact {record.artifact_id} has unknown role")
        if record.handling not in ALLOWED_HANDLINGS:
            raise HandoffSnapshotError(f"artifact {record.artifact_id} has unknown handling")
        required_keys = set(BASE_ARTIFACT_KEYS)
        optional_keys: set[str] = set()
        if record.handling == "included":
            required_keys |= INCLUDED_PAYLOAD_KEYS
            optional_keys |= INCLUDED_ARTIFACT_ROLE_KEYS.get(record.role, set())
            if record.role in ADVANCED_INCLUDED_ROLES:
                required_keys.add("warning")
        elif record.handling == "referenced":
            self._reject_non_included_payload_fields(artifact)
            required_keys.add("reference")
            optional_keys |= REFERENCED_ARTIFACT_ROLE_KEYS.get(record.role, set())
        else:
            self._reject_non_included_payload_fields(artifact)
            required_keys.add("exclusion_reason")
            optional_keys |= EXCLUDED_ARTIFACT_ROLE_KEYS.get(record.role, set())
        validate_exact_keys(
            artifact,
            required_keys,
            f"artifact {record.artifact_id}",
            optional_keys=optional_keys,
        )
        if "warning" in artifact and (
            not isinstance(artifact.get("warning"), str) or not artifact["warning"]
        ):
            raise HandoffSnapshotError(f"artifact {record.artifact_id} warning must be text")
        if "reference" in artifact:
            validate_text_field(
                artifact.get("reference"),
                f"artifact {record.artifact_id} reference",
            )

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
            if not is_non_bool_int(artifact.get("size_bytes")):
                raise HandoffSnapshotError(f"included artifact {record.artifact_id} size mismatch")
            validate_sha256(artifact.get("sha256"), f"included artifact {record.artifact_id}")
            self._validated_included_artifact_path(artifact)
            self._validate_source_run_relation(artifact)
            if record.role == "required_read_sidecar":
                applies_to = artifact.get("applies_to_artifact_id")
                validate_text_field(
                    applies_to,
                    f"sidecar {record.artifact_id} applies_to_artifact_id",
                )
                self._validate_required_sidecar_artifact(artifact)
            if record.role == "primary_data":
                self._validate_primary_data_artifact(artifact)
            if record.role == "user_attached_derived_input":
                processed_status = artifact.get("processed_status")
                if not isinstance(processed_status, str) or not processed_status:
                    raise HandoffSnapshotError(
                        f"derived input {record.artifact_id} requires processed_status"
                    )
                human_production_note = artifact.get("human_production_note")
                if not isinstance(human_production_note, str) or not human_production_note:
                    raise HandoffSnapshotError(
                        f"derived input {record.artifact_id} requires human_production_note"
                    )
            if record.role in ADVANCED_INCLUDED_ROLES and "warning" not in artifact:
                raise HandoffSnapshotError(f"artifact {record.artifact_id} requires warning")
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
            validate_text_field(
                artifact.get("exclusion_reason"),
                f"excluded artifact {record.artifact_id} reason",
            )
            self._validate_source_run_relation(artifact)

    def _reject_non_included_payload_fields(self, artifact: dict[str, Any]) -> None:
        artifact_id = artifact.get("artifact_id")
        for key in ("path", "size_bytes", "sha256"):
            if key in artifact:
                raise HandoffSnapshotError(f"artifact {artifact_id} {key} requires inclusion")

    def _validate_source_run_relation(self, artifact: dict[str, Any]) -> None:
        relations = require_list(
            artifact.get("source_run_relation"),
            f"artifact {artifact.get('artifact_id')} source_run_relation",
        )
        if not relations:
            raise HandoffSnapshotError(
                f"artifact {artifact.get('artifact_id')} source_run_relation is empty"
            )
        for run_id in relations:
            if not isinstance(run_id, str) or not run_id:
                raise HandoffSnapshotError(
                    f"artifact {artifact.get('artifact_id')} source_run_relation must use run IDs"
                )
        if len(set(relations)) != len(relations):
            raise HandoffSnapshotError(
                f"artifact {artifact.get('artifact_id')} source_run_relation has duplicates"
            )
        unknown_runs = sorted(run_id for run_id in relations if run_id not in self.runs_by_id)
        if unknown_runs:
            raise HandoffSnapshotError(
                f"artifact {artifact.get('artifact_id')} relation references unknown run"
            )

    def _validated_included_artifact_path(self, artifact: dict[str, Any]) -> Path:
        artifact_id = artifact["artifact_id"]
        artifact_path = self.snapshot_path(artifact["path"], f"artifact {artifact_id} path")
        if not artifact_path.is_file():
            raise HandoffSnapshotError(f"included artifact {artifact_id} is missing")
        if artifact_path.stat().st_size != artifact.get("size_bytes"):
            raise HandoffSnapshotError(f"included artifact {artifact_id} size mismatch")
        if file_sha256(artifact_path) != artifact.get("sha256"):
            raise HandoffSnapshotError(f"included artifact {artifact_id} checksum mismatch")
        return artifact_path

    def _validate_required_sidecar_artifact(self, artifact: dict[str, Any]) -> None:
        artifact_id = artifact["artifact_id"]
        primary_id = artifact.get("applies_to_artifact_id")
        validate_text_field(primary_id, f"sidecar {artifact_id} applies_to_artifact_id")
        primary = self.artifacts_by_id.get(primary_id)
        if primary is None or primary.get("role") != "primary_data":
            raise HandoffSnapshotError(f"sidecar {artifact_id} relation mismatch")
        self._validate_source_run_relation(primary)
        self._validate_source_run_relation(artifact)
        primary_relations = primary["source_run_relation"]
        primary_runs = set(primary_relations)
        sidecar_runs = set(artifact["source_run_relation"])
        if sidecar_runs != primary_runs:
            raise HandoffSnapshotError(f"sidecar {artifact_id} relation mismatch")
        for run_id in sorted(primary_runs):
            run = self.runs_by_id[run_id]
            if artifact_id not in run.get("required_sidecar_artifact_ids", []):
                raise HandoffSnapshotError(f"sidecar {artifact_id} is not required by {run_id}")

    def _validate_primary_data_artifact(self, artifact: dict[str, Any]) -> None:
        rows, fieldnames = self._read_csv_rows(artifact)
        if not rows:
            raise HandoffSnapshotError(f"artifact {artifact['artifact_id']} requires data rows")
        axes = require_list(artifact.get("axes"), f"artifact {artifact['artifact_id']} axes")
        values = require_list(artifact.get("values"), f"artifact {artifact['artifact_id']} values")
        shape = require_list(artifact.get("shape"), f"artifact {artifact['artifact_id']} shape")
        if len(shape) != 2 or not is_non_bool_int(shape[0]) or not is_non_bool_int(shape[1]):
            raise HandoffSnapshotError(f"artifact {artifact['artifact_id']} shape mismatch")
        if shape != [len(rows), len(fieldnames)]:
            raise HandoffSnapshotError(f"artifact {artifact['artifact_id']} shape mismatch")
        if len(axes) != 1 or len(values) != 1:
            raise HandoffSnapshotError(
                f"artifact {artifact['artifact_id']} requires one axis and one value"
            )
        declared_columns: list[str] = []
        for label, entries in (("axis", axes), ("value", values)):
            if not entries:
                raise HandoffSnapshotError(
                    f"artifact {artifact['artifact_id']} requires {label} metadata"
                )
            for entry in entries:
                entry_dict = require_dict(entry, f"artifact {artifact['artifact_id']} {label}")
                validate_exact_keys(
                    entry_dict,
                    {"column", "name", "unit"},
                    f"artifact {artifact['artifact_id']} {label}",
                )
                column = entry_dict.get("column")
                if not isinstance(column, str) or column not in fieldnames:
                    raise HandoffSnapshotError(
                        f"artifact {artifact['artifact_id']} {label} column mismatch"
                    )
                name = entry_dict.get("name")
                unit = entry_dict.get("unit")
                if not isinstance(name, str) or not name:
                    raise HandoffSnapshotError(
                        f"artifact {artifact['artifact_id']} {label} requires name"
                    )
                if not isinstance(unit, str) or not unit:
                    raise HandoffSnapshotError(
                        f"artifact {artifact['artifact_id']} {label} requires unit"
                    )
                declared_columns.append(column)
        if len(set(declared_columns)) != len(declared_columns):
            raise HandoffSnapshotError(f"artifact {artifact['artifact_id']} column mismatch")
        declared_column_set = set(declared_columns)
        if not declared_column_set.issubset(set(fieldnames)):
            raise HandoffSnapshotError(f"artifact {artifact['artifact_id']} column mismatch")
        if set(fieldnames) != declared_column_set:
            raise HandoffSnapshotError(f"artifact {artifact['artifact_id']} has undeclared columns")

    def _validate_primary_data_ownership(self) -> None:
        runs_by_primary: dict[str, list[str]] = {}
        for run in self.runs:
            runs_by_primary.setdefault(run["primary_artifact_id"], []).append(run["public_run_id"])
        for artifact in self.artifacts:
            if artifact.get("role") != "primary_data" or artifact.get("handling") != "included":
                continue
            artifact_id = artifact["artifact_id"]
            expected_runs = sorted(runs_by_primary.get(artifact_id, []))
            if not expected_runs:
                raise HandoffSnapshotError(
                    f"primary artifact {artifact_id} is not selected by any run"
                )
            if sorted(artifact.get("source_run_relation", [])) != expected_runs:
                raise HandoffSnapshotError(f"primary artifact {artifact_id} relation mismatch")

    def _validate_sidecar_content(
        self, sidecar_artifact: dict[str, Any], primary_artifact: dict[str, Any]
    ) -> None:
        sidecar = self._load_sidecar(sidecar_artifact["artifact_id"])
        allowed_sidecar_keys = {"sidecar_id", "applies_to_artifact_id", "columns"}
        if set(sidecar) != allowed_sidecar_keys:
            raise HandoffSnapshotError(f"sidecar {sidecar_artifact['artifact_id']} schema mismatch")
        if sidecar.get("sidecar_id") != sidecar_artifact["artifact_id"]:
            raise HandoffSnapshotError(f"sidecar {sidecar_artifact['artifact_id']} ID mismatch")
        if sidecar.get("applies_to_artifact_id") != primary_artifact["artifact_id"]:
            raise HandoffSnapshotError(
                f"sidecar {sidecar_artifact['artifact_id']} content relation mismatch"
            )
        sidecar_column_entries = [
            require_dict(column, "sidecar column")
            for column in require_list(sidecar.get("columns"), "sidecar columns")
        ]
        sidecar_column_names = [column.get("name") for column in sidecar_column_entries]
        if any(not isinstance(name, str) or not name for name in sidecar_column_names):
            raise HandoffSnapshotError(
                f"sidecar {sidecar_artifact['artifact_id']} requires columns"
            )
        if len(set(sidecar_column_names)) != len(sidecar_column_names):
            raise HandoffSnapshotError(
                f"sidecar {sidecar_artifact['artifact_id']} has duplicate columns"
            )
        primary_columns: set[str] = set()
        for entries in (primary_artifact.get("axes", []), primary_artifact.get("values", [])):
            for entry in entries:
                entry_dict = require_dict(
                    entry, f"artifact {primary_artifact['artifact_id']} metadata"
                )
                column = entry_dict.get("column")
                if not isinstance(column, str) or not column:
                    raise HandoffSnapshotError(
                        f"artifact {primary_artifact['artifact_id']} metadata column mismatch"
                    )
                primary_columns.add(column)
        if set(sidecar_column_names) != primary_columns:
            raise HandoffSnapshotError(f"sidecar {sidecar_artifact['artifact_id']} column mismatch")
        for column in sidecar_column_entries:
            if set(column) != {"name", "quantity", "unit", "axis"}:
                raise HandoffSnapshotError(
                    f"sidecar {sidecar_artifact['artifact_id']} column schema mismatch"
                )
            if not isinstance(column.get("quantity"), str) or not column["quantity"]:
                raise HandoffSnapshotError(
                    f"sidecar {sidecar_artifact['artifact_id']} column quantity mismatch"
                )
            if not isinstance(column.get("unit"), str) or not column["unit"]:
                raise HandoffSnapshotError(
                    f"sidecar {sidecar_artifact['artifact_id']} column unit mismatch"
                )
            if column.get("axis") not in {"x", "y"}:
                raise HandoffSnapshotError(
                    f"sidecar {sidecar_artifact['artifact_id']} column axis mismatch"
                )
        sidecar_columns = {column["name"]: column for column in sidecar_column_entries}
        for label, entries in (
            ("axis", primary_artifact.get("axes", [])),
            ("value", primary_artifact.get("values", [])),
        ):
            expected_axis = "x" if label == "axis" else "y"
            for entry in entries:
                self._validate_sidecar_column(
                    sidecar_artifact,
                    primary_artifact,
                    require_dict(entry, f"artifact {primary_artifact['artifact_id']} metadata"),
                    sidecar_columns,
                    expected_axis,
                )

    def _validate_sidecar_column(
        self,
        sidecar_artifact: dict[str, Any],
        primary_artifact: dict[str, Any],
        entry_dict: dict[str, Any],
        sidecar_columns: dict[str, dict[str, Any]],
        expected_axis: str,
    ) -> None:
        column = entry_dict.get("column")
        if not isinstance(column, str) or not column:
            raise HandoffSnapshotError(
                f"artifact {primary_artifact['artifact_id']} metadata column mismatch"
            )
        if column not in sidecar_columns:
            raise HandoffSnapshotError(
                f"sidecar {sidecar_artifact['artifact_id']} does not cover primary columns"
            )
        sidecar_column = sidecar_columns[column]
        if sidecar_column.get("quantity") != entry_dict.get("name"):
            raise HandoffSnapshotError(
                f"sidecar {sidecar_artifact['artifact_id']} column quantity mismatch"
            )
        if sidecar_column.get("unit") != entry_dict.get("unit"):
            raise HandoffSnapshotError(
                f"sidecar {sidecar_artifact['artifact_id']} column unit mismatch"
            )
        if sidecar_column.get("axis") != expected_axis:
            raise HandoffSnapshotError(
                f"sidecar {sidecar_artifact['artifact_id']} column axis mismatch"
            )

    def _validate_safety(self) -> None:
        safety = require_dict(self.manifest["safety_evidence"], "safety_evidence")
        missing = sorted(REQUIRED_SAFETY_EVIDENCE_KEYS - safety.keys())
        if missing:
            raise HandoffSnapshotError(f"missing safety evidence: {', '.join(missing)}")
        for key, value in safety.items():
            if key not in REQUIRED_SAFETY_EVIDENCE_KEYS:
                raise HandoffSnapshotError(f"unknown safety evidence {key}")
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
            "source_id": public_copy(run["source_id"]),
            "condition_label": run["condition_label"],
            "acquisition_time": public_copy(run["acquisition_time"]),
            "measurement_label": status_value(run["measurement_label"]),
            "measurement_label_status": public_copy(run["measurement_label"]),
            "original_path_evidence": public_copy(run["original_path_evidence"]),
            "sample_label": public_copy(run["sample_label"]),
            "device_label": public_copy(run["device_label"]),
            "important_parameters": public_copy(run["important_parameters"]),
            "per_run_note": self.per_run_note(run_id),
            "data": rows,
            "axes": public_copy(primary["axes"]),
            "values": public_copy(primary["values"]),
            "shape": public_copy(primary["shape"]),
            "sidecars": public_copy(sidecars),
            "derived_inputs": self.derived_inputs_for_run(run_id),
            "warnings": self.run_warnings(run),
        }

    def load_group(self) -> dict[str, Any]:
        selection = require_dict(self.manifest["selection"], "selection")
        run_ids = require_list(selection["group_order"], "selection.group_order")
        loaded_runs = [self.load_run(run_id) for run_id in run_ids]
        per_run_notes = require_dict(selection["per_run_notes"], "selection.per_run_notes")
        return {
            "snapshot_id": self.manifest["snapshot_id"],
            "group_title": selection["group_title"],
            "selected_reason": status_value(selection["selected_reason"]),
            "run_order": public_copy(run_ids),
            "per_run_notes": public_copy(per_run_notes),
            "runs": loaded_runs,
            "derived_inputs": self.derived_inputs_for_run_group(run_ids),
            "shared_context": self.shared_context(),
        }

    def per_run_note(self, run_id: str) -> dict[str, Any]:
        selection = require_dict(self.manifest["selection"], "selection")
        notes = require_dict(selection["per_run_notes"], "selection.per_run_notes")
        return public_copy(require_dict(notes[run_id], f"selection.per_run_notes.{run_id}"))

    def derived_inputs_for_run(self, run_id: str) -> list[dict[str, Any]]:
        derived_inputs: list[dict[str, Any]] = []
        for artifact in self.artifacts:
            if (
                artifact.get("role") == "user_attached_derived_input"
                and artifact.get("handling") == "included"
                and run_id in artifact.get("source_run_relation", [])
            ):
                self._validated_included_artifact_path(artifact)
                derived_inputs.append(artifact_summary_record(artifact))
        return derived_inputs

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
            "source_system": public_copy(self.manifest["source_system"]),
        }

    def _read_primary_csv(self, artifact: dict[str, Any]) -> list[dict[str, float]]:
        rows, _fieldnames = self._read_csv_rows(artifact)
        return rows

    def _read_csv_rows(self, artifact: dict[str, Any]) -> tuple[list[dict[str, float]], list[str]]:
        artifact_path = self._validated_included_artifact_path(artifact)
        try:
            with artifact_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
                fieldnames = reader.fieldnames or []
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            raise HandoffSnapshotError(
                f"artifact {artifact['artifact_id']} could not be read as CSV"
            ) from exc
        if len(set(fieldnames)) != len(fieldnames):
            raise HandoffSnapshotError(f"artifact {artifact['artifact_id']} has duplicate columns")
        if any(not fieldname for fieldname in fieldnames):
            raise HandoffSnapshotError(f"artifact {artifact['artifact_id']} requires column names")
        parsed_rows: list[dict[str, float]] = []
        for row_index, row in enumerate(rows, start=1):
            parsed_row: dict[str, float] = {}
            for key, value in row.items():
                try:
                    parsed_value = float(value)
                except (TypeError, ValueError) as exc:
                    raise HandoffSnapshotError(
                        f"artifact {artifact['artifact_id']} row {row_index} column {key} "
                        "must be numeric"
                    ) from exc
                if not math.isfinite(parsed_value):
                    raise HandoffSnapshotError(
                        f"artifact {artifact['artifact_id']} row {row_index} column {key} "
                        "must be finite"
                    )
                parsed_row[key] = parsed_value
            parsed_rows.append(parsed_row)
        return parsed_rows, fieldnames

    def _load_sidecar(self, sidecar_id: str) -> dict[str, Any]:
        artifact = self.artifacts_by_id[sidecar_id]
        path = self._validated_included_artifact_path(artifact)
        return read_json(path, f"artifact {sidecar_id}")

    def missing_and_redacted_fields(self) -> list[dict[str, str]]:
        fields: list[dict[str, str]] = []
        source_system = require_dict(self.manifest["source_system"], "source_system")
        for key in ("station_id", "control_computer"):
            status = status_label(source_system.get(key))
            if status in MISSING_STATUSES:
                fields.append({"path": f"source_system.{key}", "status": status})
        for run in self.runs:
            run_id = run["public_run_id"]
            for key, value in run.items():
                status = status_label(value)
                if status in MISSING_STATUSES:
                    fields.append({"path": f"runs.{run_id}.{key}", "status": status})
            source_id = require_dict(run.get("source_id"), f"run {run_id} source_id")
            for key in ("namespace", "local_id"):
                status = status_label(source_id.get(key))
                if status in MISSING_STATUSES:
                    fields.append({"path": f"runs.{run_id}.source_id.{key}", "status": status})
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
        per_run_notes = require_dict(selection["per_run_notes"], "selection.per_run_notes")
        for run_id, note in per_run_notes.items():
            status = status_label(note)
            if status in MISSING_STATUSES:
                fields.append({"path": f"selection.per_run_notes.{run_id}", "status": status})
        return sorted(fields, key=lambda item: item["path"])

    def redaction_status(self) -> dict[str, Any]:
        return public_copy(self.manifest["redaction_status"])

    def summary(self) -> dict[str, Any]:
        self._validate_included_artifacts()
        missing_fields = self.missing_and_redacted_fields()
        selection = require_dict(self.manifest["selection"], "selection")
        run_order = require_list(selection["group_order"], "selection.group_order")
        included = [
            artifact_summary_record(artifact)
            for artifact in self.artifacts
            if artifact["handling"] == "included"
        ]
        referenced = [
            artifact_summary_record(artifact)
            for artifact in self.artifacts
            if artifact["handling"] == "referenced"
        ]
        excluded = [
            artifact_summary_record(artifact)
            for artifact in self.artifacts
            if artifact["handling"] == "excluded"
        ]
        return {
            "identity": {
                "snapshot_id": self.manifest["snapshot_id"],
                "created_at": self.manifest["created_at"],
                "producer": public_copy(self.manifest["producer"]),
                "source_system": public_copy(self.manifest["source_system"]),
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
            "selection": public_copy(self.manifest["selection"]),
            "runs": [
                {
                    "run_id": run["public_run_id"],
                    "source_namespace": status_or_text_value(run["source_id"]["namespace"]),
                    "source_local_id": status_or_text_value(run["source_id"]["local_id"]),
                    "source_id": public_copy(run["source_id"]),
                    "condition_label": run["condition_label"],
                    "acquisition_time": public_copy(run["acquisition_time"]),
                    "measurement_label": status_value(run["measurement_label"]),
                    "measurement_label_status": public_copy(run["measurement_label"]),
                    "original_path_evidence": public_copy(run["original_path_evidence"]),
                    "sample_label": public_copy(run["sample_label"]),
                    "device_label": public_copy(run["device_label"]),
                    "important_parameters": public_copy(run["important_parameters"]),
                    "warnings": self.run_warnings(run),
                }
                for run in [self.runs_by_id[run_id] for run_id in run_order]
            ],
            "artifacts": {
                "included": included,
                "referenced": referenced,
                "excluded": excluded,
            },
            "missing_fields": public_copy(missing_fields),
            "redaction_status": self.redaction_status(),
            "safety_evidence": public_copy(self.manifest["safety_evidence"]),
        }

    def _validate_included_artifacts(self) -> None:
        for artifact in self.artifacts:
            if artifact.get("handling") == "included":
                self._validated_included_artifact_path(artifact)


def render_markdown(summary: dict[str, Any]) -> str:
    identity = summary["identity"]
    redaction_status = summary["redaction_status"]
    lines = [
        "# JC-002 Handoff Snapshot Summary",
        "",
        "## Identity",
        "",
        f"- Snapshot: `{markdown_text(identity['snapshot_id'])}`",
        f"- Created: `{markdown_text(identity['created_at'])}`",
        f"- Source type: `{markdown_text(identity['source_system']['type'])}`",
        "",
        "## Can Open",
        "",
        f"- Status: {summary['can_open']['status']}",
        f"- Included artifacts: {summary['can_open']['included_artifact_count']}",
        f"- Required sidecars: {summary['can_open']['required_sidecar_count']}",
        "",
        "## Selection",
        "",
        f"- Group: {markdown_text(summary['selection']['group_title'])}",
        f"- Reason: {markdown_text(status_value(summary['selection']['selected_reason']))}",
        f"- Order: {markdown_text(', '.join(summary['selection']['group_order']))}",
        "",
        "## Runs",
        "",
    ]
    for run in summary["runs"]:
        warning_text = ", ".join(run["warnings"]) if run["warnings"] else "none"
        lines.append(
            f"- `{markdown_text(run['run_id'])}`: {markdown_text(run['condition_label'])}, "
            f"{markdown_text(run['measurement_label'])}; warnings: {markdown_text(warning_text)}"
        )

    lines.extend(["", "## Artifacts", ""])
    for section_name in ("included", "referenced", "excluded"):
        artifacts = summary["artifacts"][section_name]
        lines.append(f"- {section_name.title()}: {len(artifacts)}")
        for artifact in artifacts:
            details = [
                f"role: {artifact['role']}",
                f"runs: {', '.join(artifact['source_run_relation'])}",
            ]
            if artifact.get("size_bytes") is not None:
                details.append(f"size: {artifact['size_bytes']} bytes")
            if artifact.get("sha256"):
                details.append(f"sha256: {artifact['sha256']}")
            if artifact.get("reference"):
                details.append(f"reference: {artifact['reference']}")
            if artifact.get("warning"):
                details.append(f"warning: {artifact['warning']}")
            if artifact.get("processed_status"):
                details.append(f"processed: {artifact['processed_status']}")
            if artifact.get("human_production_note"):
                details.append(f"note: {artifact['human_production_note']}")
            if artifact.get("reason"):
                details.append(f"reason: {artifact['reason']}")
            lines.append(
                f"  - `{markdown_text(artifact['artifact_id'])}` "
                f"({markdown_text('; '.join(details))})"
            )

    lines.extend(["", "## Missing And Redacted", ""])
    if summary["missing_fields"]:
        for field in summary["missing_fields"]:
            lines.append(f"- `{markdown_text(field['path'])}`: {markdown_text(field['status'])}")
    else:
        lines.append("- none")

    lines.extend(["", "## Exclusions", ""])
    for artifact in summary["artifacts"]["excluded"]:
        lines.append(
            f"- `{markdown_text(artifact['artifact_id'])}` "
            f"({markdown_text(artifact['role'])}): {markdown_text(artifact['reason'])}"
        )

    lines.extend(
        [
            "",
            "## Redaction Status",
            "",
        ]
    )
    for key in sorted(redaction_status):
        lines.append(f"- `{markdown_text(key)}`: {markdown_value(redaction_status[key])}")
    lines.extend(["", "## Safety", ""])
    for key, value in summary["safety_evidence"].items():
        lines.append(f"- {markdown_text(key)}: {markdown_text(value)}")
    return "\n".join(lines) + "\n"


def build_plot_spec(group: dict[str, Any], run_id: str | None = None) -> dict[str, Any]:
    selected_runs = group["runs"]
    if run_id is not None:
        selected_runs = [run for run in selected_runs if run["run_id"] == run_id]
        if not selected_runs:
            raise HandoffSnapshotError(f"unknown run for plot: {run_id}")

    first_run = selected_runs[0]
    x_meta = first_run["axes"][0]
    y_meta = first_run["values"][0]
    for run in selected_runs[1:]:
        if (
            run["axes"][0]["name"] != x_meta["name"]
            or run["axes"][0]["unit"] != x_meta["unit"]
            or run["values"][0]["name"] != y_meta["name"]
            or run["values"][0]["unit"] != y_meta["unit"]
        ):
            raise HandoffSnapshotError("group plot requires matching axis and value metadata")
    x_label = f"{x_meta['name']} ({x_meta['unit']})"
    y_label = f"{y_meta['name']} ({y_meta['unit']})"
    return {
        "title": group["group_title"],
        "x_label": x_label,
        "y_label": y_label,
        "series": [
            {
                "label": run["condition_label"],
                "x": [row[run["axes"][0]["column"]] for row in run["data"]],
                "y": [row[run["values"][0]["column"]] for row in run["data"]],
            }
            for run in selected_runs
        ],
    }


def mock_plotter_svg(plot_spec: dict[str, Any]) -> str:
    colors = ["#1f77b4", "#d62728", "#2ca02c"]
    plotted_series: list[tuple[dict[str, Any], list[tuple[float, float]]]] = []
    all_x_values: list[float] = []
    all_y_values: list[float] = []
    for series in require_list(plot_spec.get("series"), "plot_spec.series"):
        series_dict = require_dict(series, "plot series")
        x_values = require_list(series_dict.get("x"), "plot series x")
        y_values = require_list(series_dict.get("y"), "plot series y")
        if len(x_values) != len(y_values):
            raise HandoffSnapshotError("mock plotter series x and y lengths must match")
        points: list[tuple[float, float]] = []
        for x_value, y_value in zip(x_values, y_values):
            if (
                not isinstance(x_value, (int, float))
                or not isinstance(y_value, (int, float))
                or not math.isfinite(x_value)
                or not math.isfinite(y_value)
            ):
                raise HandoffSnapshotError("mock plotter values must be finite numbers")
            x_float = float(x_value)
            y_float = float(y_value)
            points.append((x_float, y_float))
            all_x_values.append(x_float)
            all_y_values.append(y_float)
        plotted_series.append((series_dict, points))
    if not all_x_values:
        raise HandoffSnapshotError("mock plotter requires x/y pairs")

    x_min = min(all_x_values)
    x_max = max(all_x_values)
    y_min = min(all_y_values)
    y_max = max(all_y_values)
    x_span = x_max - x_min
    y_span = y_max - y_min

    def plot_x(value: float) -> float:
        if x_span == 0:
            return 320.0
        return 48.0 + ((value - x_min) / x_span) * 544.0

    def plot_y(value: float) -> float:
        if y_span == 0:
            return 180.0
        return 312.0 - ((value - y_min) / y_span) * 264.0

    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">',
        '<rect width="640" height="360" fill="white"/>',
        (
            '<text x="48" y="28" font-family="sans-serif" font-size="16">'
            f"{html.escape(plot_spec['title'])}</text>"
        ),
        '<line x1="48" y1="312" x2="592" y2="312" stroke="#222"/>',
        '<line x1="48" y1="48" x2="48" y2="312" stroke="#222"/>',
        (
            '<text x="300" y="346" font-family="sans-serif" font-size="12">'
            f"{html.escape(plot_spec['x_label'])}</text>"
        ),
        (
            '<text x="8" y="190" font-family="sans-serif" font-size="12" '
            f'transform="rotate(-90 8 190)">{html.escape(plot_spec["y_label"])}</text>'
        ),
    ]
    for index, (series, points) in enumerate(plotted_series):
        point_text = " ".join(
            f"{plot_x(x_value):.1f},{plot_y(y_value):.1f}" for x_value, y_value in points
        )
        color = colors[index % len(colors)]
        label_y = 56 + index * 18
        lines.append(
            f'<polyline points="{point_text}" fill="none" stroke="{color}" stroke-width="2"/>'
        )
        lines.append(
            f'<text x="500" y="{label_y}" font-family="sans-serif" font-size="12" '
            f'fill="{color}">{html.escape(series["label"])}</text>'
        )
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def render_mock_plot_svg(group: dict[str, Any], run_id: str | None = None) -> str:
    return mock_plotter_svg(build_plot_spec(group, run_id=run_id))


def write_generated_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_outputs(snapshot: HandoffSnapshot, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = snapshot.summary()
    group = snapshot.load_group()

    summary_json = out_dir / "handoff-summary.json"
    summary_md = out_dir / "handoff-summary.md"
    group_json = out_dir / "reader-group.json"
    single_plot = out_dir / "single-run-plot.svg"
    group_plot = out_dir / "group-sanity-plot.svg"

    write_generated_text(summary_json, json.dumps(summary, indent=2, sort_keys=True))
    write_generated_text(summary_md, render_markdown(summary))
    write_generated_text(group_json, json.dumps(group, indent=2, sort_keys=True))
    write_generated_text(
        single_plot,
        render_mock_plot_svg(group, run_id=group["run_order"][0]),
    )
    write_generated_text(group_plot, render_mock_plot_svg(group))
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
            print(path.relative_to(args.out_dir))
    else:
        summary = snapshot.summary()
        print(render_markdown(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
