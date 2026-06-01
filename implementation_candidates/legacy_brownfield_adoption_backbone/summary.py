"""Post-run-first brownfield adoption backbone for legacy runs.

This module composes already-built legacy sidecar/review/receipt summaries into
one route-level adoption summary. It validates continuity across the existing
pieces while keeping execution, observation, import, storage writes, reference
repair, parameter write-back, measurement-validity decisions, and GUI behavior
outside this candidate.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "adoption_authority": "explicit_legacy_brownfield_adoption_backbone",
    "adoption_mode": "post_run_first",
    "during_run_compatibility": "declared_lifecycle_events_only",
    "execution_owner": "external_legacy_system",
    "input_source": "prior_legacy_sidecar_review_and_receipt_summaries",
    "fresh_observation": "not_performed",
    "new_storage_mutation": "not_performed",
    "primary_data_import": "not_performed",
    "legacy_payload_import": "not_performed",
    "legacy_source_parsing": "not_performed_by_scopecat",
    "reference_repair": "not_performed",
    "parameter_write_back": "not_performed",
    "measurement_validity": "not_claimed",
    "gui_workflow": "not_defined",
    "shared_workflow_schema": "not_defined",
}

_SIDECAR_POLICY_EXPECTATIONS = {
    "sidecar_authority": "declared_legacy_runtime_boundary",
    "legacy_runtime_execution": "external_unchanged",
    "manifest_posture": "local_review_summary",
    "primary_data_observation": "not_performed",
    "context_payload_import": "not_performed",
    "legacy_import_acceptance": "not_performed",
    "storage_mutation": "not_performed",
    "hardware_control": "not_performed",
    "parameter_write_back": "not_performed",
    "schema_inference": "not_performed",
    "gui_workflow": "not_defined",
}

_POST_RUN_POLICY_EXPECTATIONS = {
    "review_authority": "explicit_legacy_sidecar_post_run_review",
    "fresh_observation": "not_performed",
    "primary_data_import": "not_performed",
    "storage_mutation": "not_performed",
    "record_write": "not_performed",
    "reference_repair": "not_performed",
    "parameter_write_back": "not_performed",
    "measurement_validity": "not_claimed",
    "gui_workflow": "not_defined",
}

_LOCATOR_REVIEW_POLICY_EXPECTATIONS = {
    "review_authority": "explicit_legacy_locator_observation_review_bundle",
    "locator_observation_handling": "prior_summary_only",
    "fresh_file_observation": "not_performed",
    "backend_lookup": "not_performed",
    "data_observation": "not_performed",
    "legacy_source_parsing": "not_performed_by_scopecat",
    "legacy_import_acceptance": "not_performed",
    "storage_mutation": "not_performed",
    "record_write": "not_performed",
    "reference_repair": "not_performed",
    "parameter_write_back": "not_performed",
    "measurement_validity": "not_claimed",
}

_APPEND_INTENT_POLICY_EXPECTATIONS = {
    "intent_authority": "explicit_reviewed_legacy_sidecar_append_intent",
    "approval_required": "explicit_operator_approval",
    "append_target": "existing_measurement_record_review_evidence",
    "fact_posture": "review_debug_evidence",
    "storage_mutation": "not_performed",
    "record_write": "not_performed",
    "primary_data_import": "not_performed",
    "legacy_source_parsing": "not_performed_by_scopecat",
    "reference_repair": "not_performed",
    "parameter_write_back": "not_performed",
    "measurement_validity": "not_claimed",
}

_RECEIPT_POLICY_EXPECTATIONS = {
    "write_authority": "approved_reviewed_legacy_sidecar_append_intent",
    "append_behavior": "write_review_evidence_receipt",
    "storage_mutation": "write_review_evidence_receipt",
    "record_write": "append_review_evidence_receipt",
    "manifest_update": "not_performed",
    "primary_data_import": "not_performed",
    "legacy_payload_import": "not_performed",
    "legacy_source_parsing": "not_performed_by_scopecat",
    "reference_repair": "not_performed",
    "parameter_write_back": "not_performed",
    "measurement_validity": "not_claimed",
}

_READ_POLICY_EXPECTATIONS = {
    "read_authority": "explicit_legacy_evidence_receipt_read_view",
    "storage_scan": "not_performed",
    "storage_mutation": "not_performed",
    "record_write": "not_performed",
    "primary_data_read": "not_performed",
    "primary_data_import": "not_performed",
    "legacy_payload_import": "not_performed",
    "legacy_source_parsing": "not_performed_by_scopecat",
    "reference_repair": "not_performed",
    "parameter_write_back": "not_performed",
    "measurement_validity": "not_claimed",
}

_READY_STATES = {
    "legacy_sidecar_ready_for_review",
    "legacy_sidecar_post_run_ready",
    "legacy_locator_observation_review_ready",
    "reviewed_legacy_sidecar_append_intent_ready",
    "reviewed_legacy_sidecar_evidence_receipt_written",
    "legacy_evidence_receipt_read_view_ready",
}


def _validate_expected_values(
    policy: dict[str, Any], expectations: dict[str, str], owner: str
) -> None:
    for key, expected in expectations.items():
        if policy.get(key) != expected:
            raise ValueError(f"{owner} policy {key} must be {expected}")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["adoption_backbone_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("legacy brownfield adoption policy must match expected shape")
    _validate_expected_values(policy, _EXPECTED_POLICY, "legacy brownfield adoption")


def _measurement_ids(source: dict[str, Any]) -> dict[str, str]:
    sidecar = source["legacy_run_sidecar_summary"]
    post_run = source["legacy_sidecar_post_run_review_summary"]
    locator = source["legacy_locator_observation_review_bundle_summary"]
    append_intent = source["reviewed_legacy_sidecar_append_intent_summary"]
    receipt = source["reviewed_legacy_sidecar_evidence_append_receipt_summary"]
    read_view = source["legacy_evidence_receipt_read_view_summary"]
    return {
        "sidecar": sidecar["measurement_record"]["measurement_id"],
        "post_run": post_run["source_sidecar"]["measurement_id"],
        "locator_review": locator["source_review"]["measurement_id"],
        "append_intent_source": append_intent["source_review"]["measurement_id"],
        "append_intent": append_intent["append_intent"]["measurement_id"],
        "receipt_source": receipt["source_intent"]["measurement_id"],
        "receipt_write": receipt["write_request"]["measurement_id"],
        "receipt_record": receipt["current_record"]["measurement_record_id"],
        "read_record": read_view["record"]["measurement_record_id"],
        "read_request": read_view["read_request"]["measurement_id"],
    }


def _validate_measurement_continuity(source: dict[str, Any]) -> str:
    ids = _measurement_ids(source)
    unique_ids = set(ids.values())
    if len(unique_ids) != 1:
        mismatched = ", ".join(f"{key}={value}" for key, value in sorted(ids.items()))
        raise ValueError(f"measurement_id continuity mismatch: {mismatched}")
    return next(iter(unique_ids))


def _validate_request_continuity(source: dict[str, Any]) -> None:
    append_intent = source["reviewed_legacy_sidecar_append_intent_summary"]["append_intent"]
    receipt = source["reviewed_legacy_sidecar_evidence_append_receipt_summary"]
    read_view = source["legacy_evidence_receipt_read_view_summary"]
    if receipt["source_intent"]["request_id"] != append_intent["request_id"]:
        raise ValueError("receipt source intent request_id must match append intent")
    if receipt["write_request"]["append_intent_request_id"] != append_intent["request_id"]:
        raise ValueError("receipt write append_intent_request_id must match append intent")
    receipt_paths = read_view["read_request"]["receipt_paths"]
    receipt_path = receipt["write_request"]["receipt_path"]
    if receipt_path not in receipt_paths:
        raise ValueError("read view must include the written review-evidence receipt path")
    receipt_ids = {
        item.get("receipt_id")
        for item in read_view["receipt_view"]["receipts"]
        if item["receipt_path"] == receipt_path
    }
    if receipt["write_request"]["receipt_id"] not in receipt_ids:
        raise ValueError("read view receipt_id must match written review-evidence receipt")


def _validate_sidecar_events(sidecar: dict[str, Any], measurement_id: str) -> None:
    events = sidecar["sidecar_events"]
    if not events:
        raise ValueError("sidecar events are required for lifecycle compatibility review")
    for event in events:
        if event["measurement_id"] != measurement_id:
            raise ValueError("sidecar event measurement_id must match adoption measurement")


def _validate_source(source: dict[str, Any]) -> str:
    _validate_policy(source)
    sidecar = source["legacy_run_sidecar_summary"]
    post_run = source["legacy_sidecar_post_run_review_summary"]
    locator = source["legacy_locator_observation_review_bundle_summary"]
    append_intent = source["reviewed_legacy_sidecar_append_intent_summary"]
    receipt = source["reviewed_legacy_sidecar_evidence_append_receipt_summary"]
    read_view = source["legacy_evidence_receipt_read_view_summary"]

    _validate_expected_values(sidecar["sidecar_policy"], _SIDECAR_POLICY_EXPECTATIONS, "sidecar")
    _validate_expected_values(
        post_run["sidecar_post_run_review_policy"],
        _POST_RUN_POLICY_EXPECTATIONS,
        "post-run review",
    )
    _validate_expected_values(
        locator["locator_observation_review_policy"],
        _LOCATOR_REVIEW_POLICY_EXPECTATIONS,
        "locator observation review",
    )
    _validate_expected_values(
        append_intent["append_intent_policy"],
        _APPEND_INTENT_POLICY_EXPECTATIONS,
        "append intent",
    )
    _validate_expected_values(
        receipt["evidence_append_receipt_policy"],
        _RECEIPT_POLICY_EXPECTATIONS,
        "evidence append receipt",
    )
    _validate_expected_values(
        read_view["evidence_receipt_read_policy"],
        _READ_POLICY_EXPECTATIONS,
        "evidence receipt read view",
    )

    measurement_id = _validate_measurement_continuity(source)
    _validate_request_continuity(source)
    _validate_sidecar_events(sidecar, measurement_id)
    return measurement_id


def _stage(name: str, classification: str, *, mutation: str) -> dict[str, str]:
    state = "ready" if classification in _READY_STATES else "needs_review"
    return {
        "stage": name,
        "classification": classification,
        "state": state,
        "mutation": mutation,
    }


def _adoption_stages(source: dict[str, Any]) -> list[dict[str, str]]:
    sidecar = source["legacy_run_sidecar_summary"]
    post_run = source["legacy_sidecar_post_run_review_summary"]
    locator = source["legacy_locator_observation_review_bundle_summary"]
    append_intent = source["reviewed_legacy_sidecar_append_intent_summary"]
    receipt = source["reviewed_legacy_sidecar_evidence_append_receipt_summary"]
    read_view = source["legacy_evidence_receipt_read_view_summary"]
    return [
        _stage(
            "legacy_sidecar_declared",
            sidecar["measurement_record"]["classification"],
            mutation="none",
        ),
        _stage("post_run_review", post_run["classification"], mutation="none"),
        _stage("locator_observation_review", locator["classification"], mutation="none"),
        _stage("approved_append_intent", append_intent["classification"], mutation="none"),
        _stage(
            "review_evidence_receipt", receipt["classification"], mutation="prior_receipt_write"
        ),
        _stage("receipt_read_view", read_view["classification"], mutation="none"),
    ]


def _classification(stages: list[dict[str, str]], read_view: dict[str, Any]) -> str:
    if read_view["review_finding_count"]:
        return "legacy_brownfield_adoption_readback_needs_review"
    if all(stage["state"] == "ready" for stage in stages):
        return "legacy_brownfield_adoption_ready_for_review_evidence_readback"
    return "legacy_brownfield_adoption_needs_review"


def _review_finding_count(source: dict[str, Any]) -> int:
    return sum(
        int(source[key]["review_finding_count"])
        for key in (
            "legacy_sidecar_post_run_review_summary",
            "legacy_locator_observation_review_bundle_summary",
            "legacy_evidence_receipt_read_view_summary",
        )
    ) + len(source["reviewed_legacy_sidecar_append_intent_summary"]["review_findings"])


def _context_posture(sidecar: dict[str, Any]) -> dict[str, Any]:
    return {
        "context_ref_count": sidecar["run_start_context"]["context_ref_count"],
        "selected_context_count": sidecar["run_start_context"]["selected_context_count"],
        "unavailable_required_context_count": sidecar["run_start_context"][
            "unavailable_required_context_count"
        ],
        "context_handling": "optional_reference_links_unless_declared_required",
        "canonical_context_claim": "not_made_by_legacy_backbone",
    }


def _during_run_compatibility(sidecar: dict[str, Any]) -> dict[str, Any]:
    event_types = [event["event_type"] for event in sidecar["sidecar_events"]]
    during_evidence = [
        ref["evidence_id"]
        for ref in sidecar["supporting_evidence_refs"]
        if ref["lifecycle_stage"] == "during_run"
    ]
    return {
        "current_ingestion": "post_run_batch_declared_events",
        "future_compatible_ingestion": "during_run_incremental_event_append",
        "event_count": len(event_types),
        "event_types": event_types,
        "during_run_evidence_ref_count": len(during_evidence),
        "during_run_evidence_ids": during_evidence,
        "runner_control": "not_claimed",
    }


def _effects() -> dict[str, str]:
    return {
        "fresh_observation": "not_performed",
        "new_storage_mutation": "not_performed",
        "primary_data_import": "not_performed",
        "legacy_payload_import": "not_performed",
        "legacy_source_parsing": "not_performed_by_scopecat",
        "reference_repair": "not_performed",
        "parameter_write_back": "not_performed",
        "measurement_validity": "not_claimed",
        "gui_workflow": "not_defined",
    }


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "post_run_first_adoption",
            "severity": "info",
            "basis": "The backbone can be reviewed after an externally executed legacy run.",
            "does_not_claim": "live_sidecar_writer_or_runner_hook",
        },
        {
            "code": "during_run_compatible_events",
            "severity": "review",
            "basis": "Lifecycle events are declared facts that could later be emitted incrementally.",
            "does_not_claim": "real_time_monitoring_or_runner_control",
        },
        {
            "code": "legacy_payloads_remain_external",
            "severity": "review",
            "basis": "Primary data and supporting evidence stay as references or review evidence.",
            "does_not_claim": "legacy_import_or_preview_verification",
        },
        {
            "code": "receipt_is_review_evidence",
            "severity": "review",
            "basis": "The carried receipt records reviewed facts without replacing manifests.",
            "does_not_claim": "canonical_record_merge_or_read_model_refresh",
        },
    ]


def build_legacy_brownfield_adoption_backbone_summary(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Build a post-run-first brownfield adoption summary from prior summaries."""
    measurement_id = _validate_source(source)
    sidecar = source["legacy_run_sidecar_summary"]
    read_view = source["legacy_evidence_receipt_read_view_summary"]
    stages = _adoption_stages(source)
    return {
        "adoption_backbone_policy": copy.deepcopy(source["adoption_backbone_policy"]),
        "classification": _classification(stages, read_view),
        "measurement_id": measurement_id,
        "adoption_mode": {
            "primary_mode": "post_run_first",
            "during_run_compatible": True,
            "legacy_execution_owner": "external_legacy_system",
        },
        "stage_count": len(stages),
        "adoption_stages": stages,
        "context_posture": _context_posture(sidecar),
        "during_run_compatibility": _during_run_compatibility(sidecar),
        "receipt_readback": {
            "record_id": read_view["record"]["measurement_record_id"],
            "requested_receipt_count": read_view["receipt_view"]["requested_receipt_count"],
            "observed_receipt_count": read_view["receipt_view"]["observed_receipt_count"],
            "status_counts": copy.deepcopy(read_view["receipt_view"]["status_counts"]),
        },
        "review_finding_count": _review_finding_count(source),
        "effects": _effects(),
        "attention": _attention(),
    }
