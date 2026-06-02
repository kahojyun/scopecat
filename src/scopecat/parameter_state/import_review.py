"""Structured summary builder for adapter parameter import review commit.

This module consumes an adapter-authored parameter import preview manifest and
an explicit review decision. It is deliberately side-effect free: it does not
parse legacy files, write managed storage, mutate external files, run schema
migrations, write hardware, open GUIs, or define a shared domain model.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from scopecat.parameter_state.import_preview import (
    build_adapter_authored_parameter_state_import_preview_summary,
)

_EXPECTED_POLICY = {
    "input_authority": "validated_adapter_preview",
    "review_required": "explicit_human_acceptance",
    "managed_parameter_state_creation": "summary_only_not_written",
    "legacy_source_parsing": "not_performed_by_scopecat",
    "schema_migration": "not_performed",
    "external_file_authority": "not_claimed",
    "hardware_write_back": "not_performed",
    "storage_mutation": "not_performed",
    "gui_workflow": "not_defined",
}

_REVIEW_STATUSES = {"accepted"}
_MANAGED_STATE_KINDS = {"seed_snapshot", "committed_snapshot"}
_READINESS = {"seeded_incomplete", "partially_calibrated"}
_TRUST_STATUS = {"trusted_for_declared_scope", "not_fully_trusted"}


@dataclass(frozen=True, init=False)
class AdapterParameterImportReviewCommitRequest:
    """Typed route-local request for adapter import review/commit."""

    _source: dict[str, Any] = field(repr=False)
    _preview_summary: dict[str, Any] = field(repr=False)

    def __init__(self, *, source: dict[str, Any]) -> None:
        preview_summary = build_adapter_authored_parameter_state_import_preview_summary(
            source["adapter_preview_manifest"]
        )
        _validate_references(source, preview_summary)
        object.__setattr__(self, "_source", copy.deepcopy(source))
        object.__setattr__(self, "_preview_summary", copy.deepcopy(preview_summary))

    @classmethod
    def from_dict(cls, source: dict[str, Any]) -> AdapterParameterImportReviewCommitRequest:
        return cls(source=source)

    @property
    def source(self) -> dict[str, Any]:
        return copy.deepcopy(self._source)

    @property
    def preview_summary(self) -> dict[str, Any]:
        return copy.deepcopy(self._preview_summary)

    @property
    def review_id(self) -> str:
        return self._source["review"]["review_id"]


@dataclass(frozen=True, init=False)
class AdapterParameterImportReviewCommitResult:
    """Typed route-local summary result for accepted adapter import review."""

    _summary: dict[str, Any] = field(repr=False)

    def __init__(self, *, summary: dict[str, Any]) -> None:
        object.__setattr__(self, "_summary", copy.deepcopy(summary))

    @property
    def state_id(self) -> str:
        return self._summary["managed_parameter_state"]["state_id"]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._summary)


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["adapter_parameter_import_review_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("adapter parameter import review policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"adapter parameter import review policy {key} must be {expected}")


def _candidate_entries_by_path(preview_summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(preview_summary["candidate_entries"], "path")


def _validate_review(
    review: dict[str, Any],
    preview_summary: dict[str, Any],
) -> None:
    if review["review_status"] not in _REVIEW_STATUSES:
        raise ValueError("adapter parameter import review must be accepted")
    if not review["accepted_by_role"]:
        raise ValueError("adapter parameter import review requires accepted_by_role")
    if (
        review["preview_candidate_state_id"]
        != preview_summary["candidate_parameter_state"]["candidate_state_id"]
    ):
        raise ValueError("review preview candidate state does not match preview summary")
    if review["reviewed_preview_classification"] != preview_summary["classification"]:
        raise ValueError("reviewed preview classification does not match preview summary")

    entries = _candidate_entries_by_path(preview_summary)
    accepted_paths = review["accepted_entry_paths"]
    if not accepted_paths:
        raise ValueError("adapter parameter import review requires accepted entry paths")
    if len(accepted_paths) != len(set(accepted_paths)):
        raise ValueError("adapter parameter import review contains duplicate accepted entry path")
    for path in accepted_paths:
        entry = entries.get(path)
        if entry is None:
            raise ValueError("adapter parameter import review accepts missing preview entry")
        if entry["entry_state"] != "candidate_entry":
            raise ValueError("adapter parameter import review can accept candidate entries only")

    rejected_paths = review.get("rejected_or_deferred_entry_paths", [])
    if len(rejected_paths) != len(set(rejected_paths)):
        raise ValueError("adapter parameter import review contains duplicate rejected entry path")
    for path in rejected_paths:
        if path not in entries:
            raise ValueError("adapter parameter import review rejects missing preview entry")
        if path in accepted_paths:
            raise ValueError("adapter parameter import review cannot both accept and reject entry")


def _validate_managed_state(
    managed_state: dict[str, Any],
    review: dict[str, Any],
    preview_summary: dict[str, Any],
) -> None:
    if managed_state["source_preview_candidate_state_id"] != review["preview_candidate_state_id"]:
        raise ValueError("managed parameter state must reference reviewed preview candidate")
    if managed_state["created_by_review_id"] != review["review_id"]:
        raise ValueError("managed parameter state must reference creating review")
    if managed_state["state_kind"] not in _MANAGED_STATE_KINDS:
        raise ValueError(f"unsupported managed parameter state kind: {managed_state['state_kind']}")
    if managed_state["readiness"] not in _READINESS:
        raise ValueError("managed parameter state readiness is unsupported")
    if managed_state["trust_status"] not in _TRUST_STATUS:
        raise ValueError("managed parameter state trust_status is unsupported")

    preview_hint = preview_summary["candidate_parameter_state"]["lineage_hint"]
    if managed_state["lineage"]["lineage_label"] != preview_hint["lineage_label"]:
        raise ValueError("managed parameter state lineage label must come from preview hint")
    if managed_state["lineage"]["lineage_purpose"] != preview_hint["lineage_purpose"]:
        raise ValueError("managed parameter state lineage purpose must come from preview hint")
    if managed_state["lineage"]["target_scope"] != preview_hint["target_scope"]:
        raise ValueError("managed parameter state target scope must come from preview hint")

    entries = _candidate_entries_by_path(preview_summary)
    managed_paths = [entry["path"] for entry in managed_state["entries"]]
    if len(managed_paths) != len(set(managed_paths)):
        raise ValueError("managed parameter state contains duplicate entry path")
    if set(managed_paths) != set(review["accepted_entry_paths"]):
        raise ValueError("managed parameter state entries must match accepted entry paths")

    for entry in managed_state["entries"]:
        source_entry = entries[entry["path"]]
        if entry["value"] != source_entry["value"]:
            raise ValueError("managed parameter state entry value must come from preview")
        if entry["unit"] != source_entry["unit"]:
            raise ValueError("managed parameter state entry unit must come from preview")
        if entry["source_ids"] != source_entry["source_ids"]:
            raise ValueError("managed parameter state entry sources must come from preview")
        if entry["trust"] != "review_accepted":
            raise ValueError("managed parameter state entry trust must be review_accepted")

    trusted_paths = managed_state["trusted_entry_paths"]
    if len(trusted_paths) != len(set(trusted_paths)):
        raise ValueError("managed parameter state contains duplicate trusted entry path")
    if set(trusted_paths) != set(managed_paths):
        raise ValueError("managed parameter state trusted paths must match managed entries")


def _validate_side_effects(source: dict[str, Any]) -> None:
    side_effects = source["side_effect_claims"]
    for key in (
        "legacy_source_parsing",
        "schema_migration",
        "hardware_write_back",
        "storage_mutation",
    ):
        if side_effects[key] != "not_performed":
            raise ValueError(f"side effect claim {key} must be not_performed")
    if side_effects["external_file_authority"] != "not_claimed":
        raise ValueError("side effect claim external_file_authority must be not_claimed")


def _validate_references(source: dict[str, Any], preview_summary: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_review(source["review"], preview_summary)
    _validate_managed_state(source["managed_parameter_state"], source["review"], preview_summary)
    _validate_side_effects(source)


def _accepted_entry_summary(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": entry["path"],
        "label": entry["label"],
        "value": copy.deepcopy(entry["value"]),
        "unit": entry["unit"],
        "trust": entry["trust"],
        "source_ids": list(entry["source_ids"]),
    }


def _managed_state_summary(managed_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "state_id": managed_state["state_id"],
        "state_kind": managed_state["state_kind"],
        "state_label": managed_state["state_label"],
        "lineage": copy.deepcopy(managed_state["lineage"]),
        "source_preview_candidate_state_id": managed_state["source_preview_candidate_state_id"],
        "created_by_review_id": managed_state["created_by_review_id"],
        "readiness": managed_state["readiness"],
        "trust_status": managed_state["trust_status"],
        "trusted_entry_paths": list(managed_state["trusted_entry_paths"]),
        "entries": [_accepted_entry_summary(entry) for entry in managed_state["entries"]],
    }


def _excluded_preview_findings(
    review: dict[str, Any],
    preview_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    accepted_paths = set(review["accepted_entry_paths"])
    findings = []
    for entry in preview_summary["candidate_entries"]:
        if entry["path"] in accepted_paths:
            continue
        findings.append(
            {
                "path": entry["path"],
                "entry_state": entry["entry_state"],
                "source_ids": list(entry["source_ids"]),
                "disposition": "not_committed_to_managed_parameter_state",
                "reason": entry.get("reason", "not accepted by review"),
            }
        )
    return findings


def _provenance_summary(preview_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "adapter_id": preview_summary["adapter"]["adapter_id"],
        "adapter_name": preview_summary["adapter"]["name"],
        "source_system_kind": preview_summary["adapter"]["source_system_kind"],
        "legacy_sources": copy.deepcopy(preview_summary["legacy_sources"]),
        "source_observation": "adapter_declared_only",
    }


def build_adapter_parameter_import_review_commit_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a structured adapter parameter import review/commit summary."""
    request_model = AdapterParameterImportReviewCommitRequest.from_dict(source)
    source = request_model.source
    preview_summary = request_model.preview_summary
    review = source["review"]
    summary = {
        "policy": copy.deepcopy(source["adapter_parameter_import_review_policy"]),
        "preview_summary": {
            "manifest_schema": preview_summary["manifest_schema"],
            "classification": preview_summary["classification"],
            "candidate_state_id": preview_summary["candidate_parameter_state"][
                "candidate_state_id"
            ],
            "entry_state_counts": copy.deepcopy(preview_summary["entry_state_counts"]),
        },
        "review": {
            "review_id": review["review_id"],
            "review_status": review["review_status"],
            "accepted_at": review["accepted_at"],
            "accepted_by_role": review["accepted_by_role"],
            "accepted_entry_paths": list(review["accepted_entry_paths"]),
            "rejected_or_deferred_entry_paths": list(
                review.get("rejected_or_deferred_entry_paths", [])
            ),
        },
        "managed_parameter_state": _managed_state_summary(source["managed_parameter_state"]),
        "provenance": _provenance_summary(preview_summary),
        "excluded_preview_entries": _excluded_preview_findings(review, preview_summary),
        "side_effects": copy.deepcopy(source["side_effect_claims"]),
    }
    return AdapterParameterImportReviewCommitResult(summary=summary).to_dict()
