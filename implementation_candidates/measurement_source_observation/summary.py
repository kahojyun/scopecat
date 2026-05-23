"""Read-only measurement source observation implementation candidate.

This module observes one explicitly declared primary-data file under a
caller-provided storage root. It validates digest, size, and row-count facts
without mutating storage, inferring schemas, accepting imports, writing export
packages, scanning storage roots, or defining GUI behavior.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Any

_EXPECTED_POLICY = {
    "observation_authority": "explicit_observation_request",
    "storage_root_authority": "caller_provided_storage_root_plus_declared_relative_paths",
    "source_observation": "explicit_primary_data_file_only",
    "checksum_algorithm": "sha256",
    "storage_mutation": "not_performed",
    "schema_inference": "not_performed",
    "import_acceptance": "not_performed",
    "export_package_writing": "not_performed",
    "hardware_control": "not_performed",
    "live_service": "not_defined",
    "gui_workflow": "not_defined",
    "shared_measurement_schema": "not_defined",
}

_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PRIMARY_DATA_FORMATS = {"csv_table"}


def _path_is_relative(path: str) -> bool:
    parsed = PurePosixPath(path)
    raw_parts = path.split("/")
    return (
        bool(path)
        and path != "."
        and "\\" not in path
        and not re.match(r"^[A-Za-z]:", path)
        and not parsed.is_absolute()
        and not any(part in {"", ".", ".."} for part in raw_parts)
    )


def _validate_relative_path(path: str, owner: str) -> None:
    if not _path_is_relative(path):
        raise ValueError(f"{owner} path must be relative")


def _validate_positive_int(value: Any, owner: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{owner} must be an integer")
    if value <= 0:
        raise ValueError(f"{owner} must be positive")


def _validate_nonnegative_int(value: Any, owner: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{owner} must be an integer")
    if value < 0:
        raise ValueError(f"{owner} must not be negative")


def _relative_parts(relative_path: str) -> tuple[str, ...]:
    return PurePosixPath(relative_path).parts


def _path_under(root: Path, relative_path: str) -> Path:
    return root.joinpath(*_relative_parts(relative_path))


def _existing_root(root: Path, label: str) -> Path:
    if root.is_symlink():
        raise ValueError(f"measurement source observation {label} root must not be a symlink")
    if not root.is_dir():
        raise ValueError(
            f"measurement source observation {label} root must be an existing directory"
        )
    return root.resolve()


def _ensure_no_symlink_parents(root: Path, relative_path: str) -> None:
    current = root
    for part in _relative_parts(relative_path)[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError("measurement source observation parent is a symlink")
        if current.exists() and not current.is_dir():
            raise ValueError("measurement source observation parent is not a directory")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["source_observation_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("expected measurement source observation policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"measurement source observation policy {key} must be {expected}")


def _validate_preview_metadata(source: dict[str, Any]) -> None:
    preview = source["declared_preview_metadata"]
    primary_data_path = source["observation_request"]["primary_data_path"]
    if preview["metadata_authority"] != "storage_manifest_declared":
        raise ValueError("preview metadata authority must stay storage_manifest_declared")
    if preview["status"] != "preview_ready":
        raise ValueError("source observation fixture currently requires preview_ready metadata")
    declared_columns = preview["declared_columns"]
    declared_names = {column["name"] for column in declared_columns}
    if len(declared_names) != len(declared_columns):
        raise ValueError("declared preview columns must have unique names")
    axis_order = preview["data_shape"]["axis_order"]
    if any(axis not in declared_names for axis in axis_order):
        raise ValueError("preview axis order must reference declared columns")
    for candidate in preview["plot_candidates"]:
        if candidate["source"] != primary_data_path:
            raise ValueError("plot candidate source must match observed primary data path")
        if candidate["x"] not in declared_names or candidate["y"] not in declared_names:
            raise ValueError("plot candidate axes must reference declared columns")


def _validate_observation_request(source: dict[str, Any]) -> None:
    request = source["observation_request"]
    if request["primary_data_format"] not in _PRIMARY_DATA_FORMATS:
        raise ValueError("measurement source observation primary data format is unsupported")
    _validate_relative_path(request["primary_data_path"], "observation request primary_data_path")
    if not _SHA256_DIGEST.fullmatch(request["expected_digest"]):
        raise ValueError("expected primary data digest must be a sha256-prefixed hex digest")
    _validate_nonnegative_int(request["expected_size_bytes"], "expected_size_bytes")
    _validate_nonnegative_int(request["expected_rows_recorded"], "expected_rows_recorded")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_observation_request(source)
    _validate_preview_metadata(source)


def _sha256_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _csv_row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = sum(1 for _row in csv.reader(handle))
    if rows == 0:
        return 0
    return rows - 1


def _observe_primary_data(source: dict[str, Any], storage_root: Path) -> dict[str, Any]:
    request = source["observation_request"]
    primary_data_path = request["primary_data_path"]
    _ensure_no_symlink_parents(storage_root, primary_data_path)
    target = _path_under(storage_root, primary_data_path)
    if target.is_symlink():
        raise ValueError("measurement source observation target is a symlink")
    if not target.is_file():
        return {
            "path": primary_data_path,
            "status": "unavailable",
            "format": request["primary_data_format"],
            "expected_digest": request["expected_digest"],
            "observed_digest": None,
            "expected_size_bytes": request["expected_size_bytes"],
            "observed_size_bytes": None,
            "expected_rows_recorded": request["expected_rows_recorded"],
            "observed_rows_recorded": None,
        }

    return {
        "path": primary_data_path,
        "status": "observed",
        "format": request["primary_data_format"],
        "expected_digest": request["expected_digest"],
        "observed_digest": _sha256_digest(target),
        "expected_size_bytes": request["expected_size_bytes"],
        "observed_size_bytes": target.stat().st_size,
        "expected_rows_recorded": request["expected_rows_recorded"],
        "observed_rows_recorded": _csv_row_count(target),
    }


def _finding(code: str, basis: str, does_not_claim: str) -> dict[str, str]:
    return {
        "code": code,
        "severity": "review",
        "basis": basis,
        "does_not_claim": does_not_claim,
    }


def _findings(observed: dict[str, Any]) -> list[dict[str, str]]:
    if observed["status"] == "unavailable":
        return [
            _finding(
                "primary_data_unavailable",
                "Declared primary data file could not be observed under the caller root.",
                "repair_or_import_acceptance",
            )
        ]

    findings = []
    if observed["observed_digest"] != observed["expected_digest"]:
        findings.append(
            _finding(
                "primary_data_digest_mismatch",
                "Observed sha256 digest differs from the declared primary-data digest.",
                "cause_attribution_or_repair",
            )
        )
    if observed["observed_size_bytes"] != observed["expected_size_bytes"]:
        findings.append(
            _finding(
                "primary_data_size_mismatch",
                "Observed byte size differs from the declared primary-data size.",
                "cause_attribution_or_repair",
            )
        )
    if observed["observed_rows_recorded"] != observed["expected_rows_recorded"]:
        findings.append(
            _finding(
                "primary_data_row_count_mismatch",
                "Observed CSV row count differs from the declared row count.",
                "schema_inference_or_scientific_validation",
            )
        )
    return findings


def _classification(observed: dict[str, Any], findings: list[dict[str, str]]) -> str:
    if observed["status"] == "unavailable":
        return "source_unavailable_for_review"
    if findings:
        return "source_observed_with_mismatch"
    return "source_observed_matches_declared_facts"


def _preview_summary(source: dict[str, Any]) -> dict[str, Any]:
    preview = source["declared_preview_metadata"]
    return {
        "status": preview["status"],
        "metadata_authority": preview["metadata_authority"],
        "shape_kind": preview["data_shape"]["kind"],
        "axis_order": list(preview["data_shape"]["axis_order"]),
        "declared_roles": copy.deepcopy(preview["declared_columns"]),
        "plot_candidates": copy.deepcopy(preview["plot_candidates"]),
        "warnings": [],
    }


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "source_file_observed",
            "severity": "review",
            "basis": "Only the explicitly declared primary-data file is observed.",
            "does_not_claim": "storage_root_scan_or_recursive_validation",
        },
        {
            "code": "checksum_validation_performed",
            "severity": "info",
            "basis": "Observed sha256 and size facts are compared with declared facts.",
            "does_not_claim": "package_integrity_contract",
        },
        {
            "code": "schema_inference_not_performed",
            "severity": "review",
            "basis": "CSV rows are counted, but columns and scientific semantics are not inferred.",
            "does_not_claim": "automatic_schema_detection",
        },
        {
            "code": "storage_mutation_not_performed",
            "severity": "review",
            "basis": "The observer reads declared data and does not write, repair, import, or export.",
            "does_not_claim": "storage_writer_or_import_acceptance",
        },
        {
            "code": "hardware_control_not_performed",
            "severity": "review",
            "basis": "The observer validates stored file facts without controlling instruments.",
            "does_not_claim": "instrument_command_or_safety_authority",
        },
    ]


def observe_measurement_source(source: dict[str, Any], *, storage_root: Path) -> dict[str, Any]:
    """Observe one declared primary-data file under a caller-provided storage root."""
    _validate_references(source)
    storage_root_resolved = _existing_root(storage_root, "storage")
    observed = _observe_primary_data(source, storage_root_resolved)
    findings = _findings(observed)

    record = source["measurement_record"]
    request = source["observation_request"]
    return {
        "source_observation_policy": copy.deepcopy(source["source_observation_policy"]),
        "measurement_record": {
            "measurement_record_id": record["measurement_record_id"],
            "label": record["label"],
            "experiment_type": record["experiment_type"],
            "target": record["target"],
            "source_kind": record["source_kind"],
            "expected_points": record["expected_points"],
            "classification": _classification(observed, findings),
        },
        "observation_request": {
            "request_id": request["request_id"],
            "primary_data_path": request["primary_data_path"],
            "primary_data_format": request["primary_data_format"],
            "expected_digest": request["expected_digest"],
            "expected_size_bytes": request["expected_size_bytes"],
            "expected_rows_recorded": request["expected_rows_recorded"],
        },
        "observed_primary_data": observed,
        "review_findings": findings,
        "preview": _preview_summary(source),
        "attention": _attention(),
    }
