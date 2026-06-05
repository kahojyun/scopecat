"""Read-only opener for directory-shaped handoff packages."""

from __future__ import annotations

import csv
import json
import os
import stat
from pathlib import Path
from typing import Any

from scopecat.handoff._contracts import (
    relative_path_parts as _relative_parts,
)
from scopecat.handoff._contracts import (
    validate_public_identifier,
)
from scopecat.handoff._declared_preview import coerce_handoff_package_preview_metadata
from scopecat.handoff._manifest_preview import (
    HandoffManifestMeasurement,
    HandoffManifestPreviewMetadata,
    preview_handoff_manifest,
)
from scopecat.handoff.package import (
    HandoffFinding,
    HandoffLinkedContext,
    HandoffMeasurement,
    HandoffPackage,
)
from scopecat.handoff.tables import HandoffTable

_MANIFEST_NAME = "package-manifest.json"


def _existing_package_dir(package_dir: Path) -> Path:
    if package_dir.is_symlink():
        raise ValueError("handoff package opener package directory must not be a symlink")
    if not package_dir.is_dir():
        raise ValueError("handoff package opener requires an existing package directory")
    return package_dir.resolve()


def _path_under(root: Path, relative_path: str) -> Path:
    return root.joinpath(*_relative_parts(relative_path, "handoff package member path"))


def _ensure_no_symlink_parents(root: Path, relative_path: str, owner: str) -> None:
    current = root
    for part in _relative_parts(relative_path, owner)[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{owner} parent must not be a symlink")
        if current.exists() and not current.is_dir():
            raise ValueError(f"{owner} parent must be a directory")


def _read_regular_package_file(package_dir: Path, relative_path: str, owner: str) -> bytes:
    _ensure_no_symlink_parents(package_dir, relative_path, owner)
    target = _path_under(package_dir, relative_path)
    if target.is_symlink():
        raise ValueError(f"{owner} must not be a symlink")
    try:
        with target.open("rb") as handle:
            file_stat = os.fstat(handle.fileno())
            if not stat.S_ISREG(file_stat.st_mode):
                raise ValueError(f"{owner} must be a regular file")
            return handle.read()
    except FileNotFoundError as exc:
        raise ValueError(f"{owner} is unavailable") from exc
    except OSError as exc:
        raise ValueError(f"{owner} is unavailable") from exc


def _load_manifest(package_dir: Path) -> dict[str, Any]:
    content = _read_regular_package_file(
        package_dir,
        _MANIFEST_NAME,
        "handoff package manifest",
    )
    try:
        manifest = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("handoff package manifest must be valid JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("handoff package manifest must be a JSON object")
    return manifest


def _validate_package_dir_identity(package_dir: Path, package_id: str) -> None:
    validate_public_identifier(package_id, "handoff package package_id")
    if package_dir.name != package_id:
        raise ValueError("handoff package directory name must match package_id")


def _load_csv_rows(
    content: bytes,
    preview: HandoffManifestPreviewMetadata,
) -> tuple[list[str], list[dict[str, str]]]:
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("handoff package primary data must be utf-8 CSV") from exc

    reader = csv.DictReader(decoded.splitlines())
    if not reader.fieldnames:
        raise ValueError("handoff package primary data requires a CSV header")

    declared_names = list(preview.declared_column_names)
    fieldnames = list(reader.fieldnames)
    if any(name == "" for name in fieldnames):
        raise ValueError("handoff package primary data requires non-empty CSV headers")
    if len(set(fieldnames)) != len(fieldnames):
        raise ValueError("handoff package primary data requires unique CSV headers")
    missing = [name for name in declared_names if name not in fieldnames]
    if missing:
        raise ValueError("handoff package primary data is missing declared preview columns")
    rows = []
    for row in reader:
        if None in row:
            raise ValueError("handoff package primary data rows must match the CSV header")
        if any(row[name] is None for name in fieldnames):
            raise ValueError("handoff package primary data rows must match the CSV header")
        rows.append({name: row[name] for name in fieldnames})
    return fieldnames, rows


def _preview_rows(rows: list[dict[str, str]], declared_names: list[str]) -> list[dict[str, str]]:
    return [{name: row[name] for name in declared_names} for row in rows[:5]]


def _findings_for_measurement(
    *,
    measurement_record_id: str,
    linked_context: tuple[HandoffLinkedContext, ...],
    package_findings: tuple[HandoffFinding, ...],
) -> tuple[HandoffFinding, ...]:
    linked_context_ids = {
        item.link_id
        for item in linked_context
        if measurement_record_id in item.linked_measurement_record_ids
    }
    findings = []
    seen = set()
    for finding in package_findings:
        is_direct = finding.measurement_record_id == measurement_record_id
        is_linked_context = (
            finding.subject_type == "linked_context" and finding.subject_id in linked_context_ids
        )
        if not is_direct and not is_linked_context:
            continue
        key = (
            finding.code,
            finding.subject_type,
            finding.subject_id,
            finding.measurement_record_id,
        )
        if key in seen:
            continue
        seen.add(key)
        findings.append(finding)
    return tuple(findings)


def _require_all_measurements_preview_ready(
    measurements: tuple[HandoffManifestMeasurement, ...],
) -> None:
    for measurement in measurements:
        if measurement.preview_metadata.status != "preview_ready":
            raise ValueError("handoff package opener requires preview_ready metadata")


def _opened_measurement(
    package_dir: Path,
    measurement: HandoffManifestMeasurement,
    *,
    linked_context: tuple[HandoffLinkedContext, ...],
    package_findings: tuple[HandoffFinding, ...],
) -> HandoffMeasurement:
    preview = measurement.preview_metadata
    primary = measurement.primary_data
    content = _read_regular_package_file(
        package_dir,
        primary.package_path,
        "handoff package primary data",
    )
    columns, rows = _load_csv_rows(content, preview)
    declared_names = list(preview.declared_column_names)
    measurement_id = measurement.measurement_record_id
    return HandoffMeasurement(
        measurement_record_id=measurement_id,
        legacy_data_id=measurement.legacy_data_id,
        label=measurement.label,
        experiment_type=measurement.experiment_type,
        target=measurement.target,
        primary_package_path=primary.package_path,
        primary_format=primary.format,
        declared_digest=primary.digest,
        declared_size_bytes=primary.size_bytes,
        observed_size_bytes=len(content),
        declared_preview_metadata=coerce_handoff_package_preview_metadata(
            {
                "status": preview.status,
                "metadata_authority": preview.metadata_authority,
                "declared_columns": list(preview.declared_columns),
            },
            primary_path=primary.package_path,
            owner="handoff opened package preview",
        ),
        primary_table=HandoffTable.from_records(columns, rows),
        preview_table=HandoffTable.from_records(
            declared_names, _preview_rows(rows, declared_names)
        ),
        linked_context=tuple(
            item for item in linked_context if measurement_id in item.linked_measurement_record_ids
        ),
        findings=_findings_for_measurement(
            measurement_record_id=measurement_id,
            linked_context=linked_context,
            package_findings=package_findings,
        ),
    )


def open_handoff_package(package_dir: Path) -> HandoffPackage:
    """Open a directory-shaped handoff package for read-only declared preview use."""

    package_dir = _existing_package_dir(package_dir)
    manifest = _load_manifest(package_dir)
    preview = preview_handoff_manifest(manifest)
    _validate_package_dir_identity(package_dir, preview.package_id)
    _require_all_measurements_preview_ready(preview.measurements)
    linked_context = tuple(
        HandoffLinkedContext(
            link_id=item.link_id,
            kind=item.kind,
            label=item.label,
            package_state=item.package_state,
            materialization=(
                "packaged_payload" if item.package_state == "packaged" else "reference_only"
            ),
            linked_measurement_record_ids=item.linked_measurement_record_ids,
            package_path=item.package_path,
            declared_digest=item.digest,
            declared_size_bytes=item.size_bytes,
            context_reference=item.context_reference,
        )
        for item in preview.linked_context
    )
    findings = preview.findings
    measurements = [
        _opened_measurement(
            package_dir,
            measurement,
            linked_context=linked_context,
            package_findings=findings,
        )
        for measurement in preview.measurements
    ]
    return HandoffPackage(
        package_id=preview.package_id,
        display_name=preview.display_name,
        created_by=preview.created_by,
        source_export_summary_id=preview.source_export_summary_id,
        preview_classification=preview.classification,
        measurements=tuple(measurements),
        linked_context=linked_context,
        findings=findings,
        manifest_path=_MANIFEST_NAME,
    )
