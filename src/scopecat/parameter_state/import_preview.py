"""Structured summary builder for adapter-authored parameter-state import preview.

This module validates a normalized manifest emitted by an external adapter. It
does not parse legacy parameter files or spreadsheets, create managed
parameter state, write files, mutate hardware, infer schemas, run migrations,
open GUIs, or define a stable public API.
"""

from __future__ import annotations

import copy
import re
from pathlib import PurePosixPath
from typing import Any

_MANIFEST_SCHEMA = "scopecat.adapter_parameter_state_import_manifest.v0"

_ADAPTER_AUTHORITY = "external_adapter"
_SOURCE_SYSTEM_KIND = "external_legacy_parameter_sources"
_SOURCE_FORMATS = {"legacy_parameters_json", "xlsx_parameter_table", "project_specific_output"}
_SOURCE_REFERENCE_STATES = {"adapter_declared_available", "unavailable", "redacted"}
_CANDIDATE_STATES = {"preview_ready", "review_required", "blocked_by_adapter_finding"}
_ENTRY_STATES = {"candidate_entry", "skipped_untrusted", "skipped_schema_limited"}
_ENTRY_TRUST = {"adapter_declared_trusted", "adapter_declared_untrusted", "schema_limited"}
_VALUE_SHAPES = {"scalar", "table", "unsupported"}
_FINDING_SEVERITIES = {"info", "review", "block_import"}
_PRIVATE_PATH_MARKERS = tuple(f"/{part}/" for part in ("Users", "private"))
_PRIVATE_TOKEN_MARKERS = {"users", "private"}


def _is_json_scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _path_is_relative(path: str) -> bool:
    parsed = PurePosixPath(path)
    return (
        bool(path)
        and path != "."
        and "\\" not in path
        and not re.match(r"^[A-Za-z]:", path)
        and not parsed.is_absolute()
        and ".." not in parsed.parts
    )


def _validate_redacted_display_path(path: str) -> None:
    if (
        not path
        or path.startswith(("/", "~"))
        or "\\" in path
        or re.match(r"^[A-Za-z]:[\\/]", path)
        or any(marker in path for marker in _PRIVATE_PATH_MARKERS)
        or "redacted" not in path.lower()
    ):
        raise ValueError("legacy source display path must be public-safe and redacted")


def _validate_public_safe_token(value: str, owner: str, *, requires_redacted: bool) -> None:
    if (
        not value
        or value.startswith(("/", "~"))
        or "/" in value
        or "\\" in value
        or re.match(r"^[A-Za-z]:", value)
        or any(marker in value.lower() for marker in _PRIVATE_TOKEN_MARKERS)
        or (requires_redacted and "redacted" not in value.lower())
    ):
        raise ValueError(f"{owner} must be public-safe")


def _validate_adapter(source: dict[str, Any]) -> None:
    adapter = source["adapter"]
    if adapter["parsing_authority"] != _ADAPTER_AUTHORITY:
        raise ValueError("legacy parameter parsing authority must stay external_adapter")
    if adapter["source_system_kind"] != _SOURCE_SYSTEM_KIND:
        raise ValueError("source system kind must stay external legacy parameter sources")


def _validate_source(source_ref: dict[str, Any]) -> None:
    _validate_public_safe_token(
        source_ref["source_id"], "legacy source_id", requires_redacted=False
    )
    _validate_public_safe_token(
        source_ref["external_root_label"],
        "legacy source external_root_label",
        requires_redacted=True,
    )
    _validate_redacted_display_path(source_ref["display_path"])
    if source_ref["source_format"] not in _SOURCE_FORMATS:
        raise ValueError(f"legacy source {source_ref['source_id']} format is unsupported")
    if source_ref["reference_state"] not in _SOURCE_REFERENCE_STATES:
        raise ValueError(f"legacy source {source_ref['source_id']} reference_state is unsupported")
    if source_ref["local_path_redacted"] is not True:
        raise ValueError("legacy source local path must stay redacted")
    if source_ref["reference_state"] != "adapter_declared_available" and not source_ref.get(
        "reason"
    ):
        raise ValueError(f"legacy source {source_ref['source_id']} requires reason")
    if source_ref["reference_state"] == "adapter_declared_available" and source_ref.get("reason"):
        raise ValueError(f"legacy source {source_ref['source_id']} must not carry reason")


def _validate_candidate(source: dict[str, Any]) -> None:
    candidate = source["candidate_parameter_state"]
    if candidate["candidate_state"] not in _CANDIDATE_STATES:
        raise ValueError(f"unsupported candidate_state: {candidate['candidate_state']}")
    if candidate["source_authority"] != "adapter_normalized_manifest":
        raise ValueError("candidate source authority must be adapter_normalized_manifest")
    if candidate["target_authority"] != "scopecat_parameter_state_after_review":
        raise ValueError("candidate target authority must be Scopecat parameter state after review")
    if not candidate["lineage_hint"]["lineage_label"]:
        raise ValueError("candidate lineage hint requires label")
    if candidate["readiness_hint"] not in {
        "seeded_incomplete",
        "partially_calibrated",
        "review_required",
    }:
        raise ValueError("candidate readiness_hint is unsupported")
    if candidate["trust_hint"] not in {
        "trusted_for_declared_scope",
        "not_fully_trusted",
        "review_required",
    }:
        raise ValueError("candidate trust_hint is unsupported")


def _validate_entry_sources(
    entry: dict[str, Any],
    sources: dict[str, dict[str, Any]],
    owner: str,
) -> None:
    if not entry["source_ids"]:
        raise ValueError(f"{owner} requires source_ids")
    for source_id in entry["source_ids"]:
        if source_id not in sources:
            raise ValueError(f"{owner} references missing legacy source")


def _validate_candidate_entry(
    entry: dict[str, Any],
    sources: dict[str, dict[str, Any]],
) -> None:
    if entry["entry_state"] not in _ENTRY_STATES:
        raise ValueError(f"unsupported entry_state: {entry['entry_state']}")
    if entry["trust"] not in _ENTRY_TRUST:
        raise ValueError(f"unsupported entry trust: {entry['trust']}")
    if entry["value_shape"] not in _VALUE_SHAPES:
        raise ValueError(f"unsupported value_shape: {entry['value_shape']}")
    _validate_entry_sources(entry, sources, f"candidate entry {entry['path']}")

    if entry["entry_state"] == "candidate_entry":
        if entry["trust"] != "adapter_declared_trusted":
            raise ValueError("candidate_entry must be adapter-declared trusted")
        if entry["value_shape"] != "scalar":
            raise ValueError("candidate_entry must be scalar in this slice")
        if not _is_json_scalar(entry["value"]):
            raise ValueError("candidate_entry value must be scalar")
        return

    if entry["entry_state"] == "skipped_untrusted":
        if entry["trust"] != "adapter_declared_untrusted":
            raise ValueError("skipped_untrusted entry must be adapter-declared untrusted")
    elif entry["entry_state"] == "skipped_schema_limited":
        if entry["trust"] != "schema_limited":
            raise ValueError("skipped_schema_limited entry must be schema_limited")
        if entry["value_shape"] not in {"table", "unsupported"}:
            raise ValueError("skipped_schema_limited entry must be table or unsupported")
    if not entry.get("reason"):
        raise ValueError(f"skipped entry {entry['path']} requires reason")


def _validate_candidate_entries(source: dict[str, Any], sources: dict[str, dict[str, Any]]) -> None:
    candidate_entries = source["candidate_entries"]
    paths = [entry["path"] for entry in candidate_entries]
    if len(paths) != len(set(paths)):
        raise ValueError("candidate entries contain duplicate parameter path")
    if not any(entry["entry_state"] == "candidate_entry" for entry in candidate_entries):
        raise ValueError("parameter import preview requires at least one candidate entry")
    for entry in candidate_entries:
        _validate_candidate_entry(entry, sources)


def _validate_adapter_findings(source: dict[str, Any]) -> None:
    seen = set()
    for finding in source["adapter_findings"]:
        code = finding["code"]
        if code in seen:
            raise ValueError(f"duplicate adapter finding code: {code}")
        seen.add(code)
        if finding["severity"] not in _FINDING_SEVERITIES:
            raise ValueError(f"adapter finding {code} severity is unsupported")
        if not finding["message"]:
            raise ValueError(f"adapter finding {code} requires message")


def _validate_references(source: dict[str, Any]) -> None:
    if source["manifest_schema"] != _MANIFEST_SCHEMA:
        raise ValueError(f"manifest_schema must be {_MANIFEST_SCHEMA}")
    _validate_adapter(source)
    sources = _records_by_key(source["legacy_sources"], "source_id")
    for source_ref in source["legacy_sources"]:
        _validate_source(source_ref)
    _validate_candidate(source)
    _validate_candidate_entries(source, sources)
    _validate_adapter_findings(source)


def _classification(source: dict[str, Any]) -> str:
    if any(item["severity"] == "block_import" for item in source["adapter_findings"]):
        return "blocked_by_adapter_finding"
    if any(
        item["reference_state"] != "adapter_declared_available" for item in source["legacy_sources"]
    ):
        return "needs_source_review"
    if any(entry["entry_state"] != "candidate_entry" for entry in source["candidate_entries"]):
        return "preview_ready_with_findings"
    return "adapter_parameter_manifest_ready_for_review"


def _adapter_summary(source: dict[str, Any]) -> dict[str, Any]:
    adapter = source["adapter"]
    return {
        "adapter_id": adapter["adapter_id"],
        "name": adapter["name"],
        "version": adapter["version"],
        "source_system_kind": adapter["source_system_kind"],
        "source_system_detail": adapter["source_system_detail"],
        "parsing_authority": adapter["parsing_authority"],
    }


def _source_summary(source_ref: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": source_ref["source_id"],
        "source_format": source_ref["source_format"],
        "external_root_label": source_ref["external_root_label"],
        "display_path": source_ref["display_path"],
        "reference_state": source_ref["reference_state"],
        "source_observation": "adapter_declared_only",
    }


def _candidate_summary(source: dict[str, Any]) -> dict[str, Any]:
    candidate = source["candidate_parameter_state"]
    return {
        "candidate_state_id": candidate["candidate_state_id"],
        "candidate_state": candidate["candidate_state"],
        "source_authority": candidate["source_authority"],
        "target_authority": candidate["target_authority"],
        "lineage_hint": copy.deepcopy(candidate["lineage_hint"]),
        "readiness_hint": candidate["readiness_hint"],
        "trust_hint": candidate["trust_hint"],
    }


def _entry_summary(entry: dict[str, Any]) -> dict[str, Any]:
    output = {
        "path": entry["path"],
        "label": entry["label"],
        "entry_state": entry["entry_state"],
        "trust": entry["trust"],
        "value_shape": entry["value_shape"],
        "source_ids": list(entry["source_ids"]),
    }
    if entry["entry_state"] == "candidate_entry":
        output["value"] = copy.deepcopy(entry["value"])
        output["unit"] = entry["unit"]
    if "reason" in entry:
        output["reason"] = entry["reason"]
    return output


def _entry_state_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts = {state: 0 for state in sorted(_ENTRY_STATES)}
    for entry in entries:
        counts[entry["entry_state"]] += 1
    return {state: count for state, count in counts.items() if count}


def _preview_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for entry in source["candidate_entries"]:
        if entry["entry_state"] == "candidate_entry":
            continue
        findings.append(
            {
                "kind": entry["entry_state"],
                "path": entry["path"],
                "source_ids": list(entry["source_ids"]),
                "reason": entry["reason"],
            }
        )
    return findings


def build_adapter_authored_parameter_state_import_preview_summary(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Build a structured summary from an adapter-authored parameter manifest."""
    _validate_references(source)
    return {
        "manifest_schema": source["manifest_schema"],
        "adapter": _adapter_summary(source),
        "legacy_sources": [_source_summary(source_ref) for source_ref in source["legacy_sources"]],
        "candidate_parameter_state": _candidate_summary(source),
        "entry_state_counts": _entry_state_counts(source["candidate_entries"]),
        "candidate_entries": [_entry_summary(entry) for entry in source["candidate_entries"]],
        "preview_findings": _preview_findings(source),
        "adapter_findings": copy.deepcopy(source["adapter_findings"]),
        "classification": _classification(source),
    }
