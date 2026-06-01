"""Passive GUI-state projection for legacy sidecar post-run review.

This module projects an already-built legacy sidecar post-run review summary
into local GUI-ready state. It does not render a GUI, execute actions, observe
legacy sources, import data, mutate storage, repair references, write
parameters, decide measurement validity, or block runs.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "view_authority": "explicit_legacy_sidecar_review_gui_state",
    "view_posture": "local_review_state_projection",
    "input_source": "legacy_sidecar_post_run_review_summary",
    "available_actions": "labels_only",
    "gui_component_runtime": "not_defined",
    "action_execution": "not_performed",
    "backend_lookup": "not_performed",
    "file_observation": "not_performed",
    "legacy_import_acceptance": "not_performed",
    "storage_mutation": "not_performed",
    "record_write": "not_performed",
    "reference_repair": "not_performed",
    "parameter_write_back": "not_performed",
    "measurement_validity": "not_claimed",
    "run_blocking": "not_claimed",
    "shared_gui_schema": "not_defined",
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

_POST_RUN_CLASSIFICATIONS = {
    "legacy_sidecar_post_run_ready",
    "legacy_sidecar_post_run_failed_needs_review",
    "legacy_sidecar_post_run_partial_needs_review",
    "legacy_sidecar_post_run_locator_unavailable",
    "legacy_sidecar_post_run_needs_locator_review",
    "legacy_sidecar_post_run_needs_attention",
}

_REQUIRED_REVIEW_SECTIONS = {
    "lifecycle",
    "legacy_locators",
    "primary_data",
    "supporting_evidence",
}

_LOCATOR_ATTENTION_CLASSIFICATIONS = {
    "legacy_sidecar_post_run_locator_unavailable",
    "legacy_sidecar_post_run_needs_locator_review",
}

_RUN_ATTENTION_CLASSIFICATIONS = {
    "legacy_sidecar_post_run_failed_needs_review",
    "legacy_sidecar_post_run_partial_needs_review",
}


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["gui_state_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("legacy sidecar GUI-state policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"legacy sidecar GUI-state policy {key} must be {expected}")


def _validate_post_run_review_summary(source: dict[str, Any]) -> None:
    summary = source["legacy_sidecar_post_run_review_summary"]
    policy = summary["sidecar_post_run_review_policy"]
    for key, expected in _POST_RUN_POLICY_EXPECTATIONS.items():
        if policy[key] != expected:
            raise ValueError(f"post-run review policy {key} must be {expected}")
    if summary["classification"] not in _POST_RUN_CLASSIFICATIONS:
        raise ValueError("unsupported legacy sidecar post-run review classification")
    sections = summary["review_sections"]
    if set(sections) != _REQUIRED_REVIEW_SECTIONS:
        raise ValueError("post-run review sections must match expected shape")
    measurement_id = summary["source_sidecar"]["measurement_id"]
    if not measurement_id:
        raise ValueError("source sidecar measurement_id is required")
    if sections["lifecycle"]["measurement_id"] != measurement_id:
        raise ValueError("lifecycle measurement_id must match source sidecar")
    if summary["review_finding_count"] != len(summary["review_findings"]):
        raise ValueError("review_finding_count must match review_findings")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_post_run_review_summary(source)


def _classification(post_run_classification: str, finding_count: int) -> str:
    if post_run_classification in _LOCATOR_ATTENTION_CLASSIFICATIONS:
        return "legacy_sidecar_gui_needs_locator_attention"
    if post_run_classification in _RUN_ATTENTION_CLASSIFICATIONS:
        return "legacy_sidecar_gui_needs_run_attention"
    if finding_count:
        return "legacy_sidecar_gui_needs_attention"
    return "legacy_sidecar_gui_ready"


def _lifecycle_card(summary: dict[str, Any]) -> dict[str, Any]:
    section = summary["review_sections"]["lifecycle"]
    lifecycle = section["lifecycle"]
    return {
        "card": "lifecycle",
        "measurement_id": section["measurement_id"],
        "label": section["label"],
        "experiment_type": section["experiment_type"],
        "lifecycle_state": lifecycle["state"],
        "started_at": lifecycle.get("started_at"),
        "ended_at": lifecycle.get("ended_at"),
        "final_recorded_points": lifecycle.get("final_recorded_points"),
        "sidecar_classification": section["sidecar_classification"],
        "does_not_claim": "measurement_validity_or_run_success",
    }


def _locator_card(summary: dict[str, Any]) -> dict[str, Any]:
    section = summary["review_sections"]["legacy_locators"]
    targets = section["targets"]
    return {
        "card": "legacy_locators",
        "classification": section["classification"],
        "target_count": section["target_count"],
        "targets_with_available_locators": sum(
            1 for target in targets if target["counts"]["available_locator_count"]
        ),
        "targets_needing_locator_review": [
            target["target_id"]
            for target in targets
            if target["classification"] != "locator_declared_sufficient_for_review"
        ],
        "locator_finding_count": len(section["locator_findings"]),
        "does_not_claim": "locator_openability_or_reference_repair",
    }


def _primary_data_card(summary: dict[str, Any]) -> dict[str, Any]:
    section = summary["review_sections"]["primary_data"]
    preview_states = sorted(
        {
            ref.get("declared_preview", {}).get("status", "preview_not_declared")
            for ref in section["primary_data_refs"]
        }
    )
    return {
        "card": "primary_data",
        "primary_data_ref_count": section["primary_data_ref_count"],
        "declared_preview_states": preview_states,
        "does_not_claim": "payload_import_or_normalized_primary_data",
    }


def _supporting_evidence_card(summary: dict[str, Any]) -> dict[str, Any]:
    section = summary["review_sections"]["supporting_evidence"]
    lifecycle_stages = sorted(
        {ref.get("lifecycle_stage", "unspecified") for ref in section["supporting_evidence_refs"]}
    )
    return {
        "card": "supporting_evidence",
        "supporting_evidence_ref_count": section["supporting_evidence_ref_count"],
        "evidence_kind_counts": copy.deepcopy(section["evidence_kind_counts"]),
        "lifecycle_stages": lifecycle_stages,
        "does_not_claim": "payload_import_or_context_authority",
    }


def _review_cards(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _lifecycle_card(summary),
        _locator_card(summary),
        _primary_data_card(summary),
        _supporting_evidence_card(summary),
    ]


def _action(
    action_id: str,
    label: str,
    target_section: str,
    *,
    enabled: bool = True,
    does_not_claim: str,
) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "label": label,
        "target_section": target_section,
        "enabled": enabled,
        "execution": "not_performed",
        "does_not_claim": does_not_claim,
    }


def _has_available_locator_kind(summary: dict[str, Any], locator_kind: str) -> bool:
    for target in summary["review_sections"]["legacy_locators"]["targets"]:
        for locator in target["locators"]:
            if (
                locator["kind"] == locator_kind
                and locator["reference_state"] == "declared_available"
            ):
                return True
    return False


def _available_review_actions(summary: dict[str, Any]) -> list[dict[str, Any]]:
    classification = summary["classification"]
    actions = [
        _action(
            "inspect_lifecycle",
            "Inspect lifecycle",
            "lifecycle",
            does_not_claim="measurement_validity_or_run_success",
        ),
        _action(
            "inspect_legacy_locators",
            "Inspect legacy locators",
            "legacy_locators",
            does_not_claim="backend_lookup_or_reference_repair",
        ),
        _action(
            "view_supporting_evidence",
            "View supporting evidence references",
            "supporting_evidence",
            enabled=bool(
                summary["review_sections"]["supporting_evidence"]["supporting_evidence_ref_count"]
            ),
            does_not_claim="payload_import_or_artifact_observation",
        ),
    ]
    if summary["review_sections"]["primary_data"]["primary_data_ref_count"]:
        actions.append(
            _action(
                "start_adapter_import_review",
                "Start adapter import review",
                "primary_data",
                does_not_claim="legacy_import_acceptance_or_adapter_execution",
            )
        )
    if _has_available_locator_kind(summary, "legacy_path"):
        actions.append(
            _action(
                "observe_file_backed_locator",
                "Observe file-backed locator",
                "legacy_locators",
                does_not_claim="file_observation_performed",
            )
        )
    if classification in _LOCATOR_ATTENTION_CLASSIFICATIONS:
        actions.append(
            _action(
                "add_or_update_locator_note",
                "Add or update locator note",
                "legacy_locators",
                does_not_claim="reference_repair_or_backend_discovery",
            )
        )
    if summary["review_findings"]:
        actions.append(
            _action(
                "review_findings",
                "Review findings",
                "review_findings",
                does_not_claim="approval_gate_or_run_blocking",
            )
        )
    return actions


def _visible_findings(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "code": finding["code"],
            "severity": finding["severity"],
            "source_section": finding["source_section"],
            "basis": finding["basis"],
            "does_not_claim": finding["does_not_claim"],
        }
        for finding in summary["review_findings"]
    ]


def _attention(summary: dict[str, Any]) -> list[dict[str, str]]:
    attention = [
        {
            "code": "legacy_sidecar_gui_state_is_passive",
            "severity": "info",
            "basis": "The projection exposes cards and action labels over a prior post-run review.",
            "does_not_claim": "gui_component_or_workflow_contract",
        },
        {
            "code": "gui_actions_are_labels_only",
            "severity": "review",
            "basis": "Available actions name possible next reviews but are not executed here.",
            "does_not_claim": "approval_gate_or_run_blocking",
        },
        {
            "code": "legacy_sources_are_not_observed",
            "severity": "review",
            "basis": "The view state does not open files, query backends, import data, or repair references.",
            "does_not_claim": "locator_openability_or_import_acceptance",
        },
    ]
    if summary["classification"] in _LOCATOR_ATTENTION_CLASSIFICATIONS:
        attention.append(
            {
                "code": "locator_attention_visible_only",
                "severity": "review",
                "basis": "Locator issues are displayed for review without automatic lookup or repair.",
                "does_not_claim": "reference_repair",
            }
        )
    return attention


def build_legacy_sidecar_review_gui_state_summary(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Build a passive GUI-ready projection over a sidecar post-run review."""
    _validate_references(source)
    review = source["legacy_sidecar_post_run_review_summary"]
    return {
        "gui_state_policy": copy.deepcopy(source["gui_state_policy"]),
        "classification": _classification(review["classification"], review["review_finding_count"]),
        "source_review": {
            "measurement_id": review["source_sidecar"]["measurement_id"],
            "post_run_classification": review["classification"],
            "sidecar_classification": review["source_sidecar"]["sidecar_classification"],
            "locator_review_classification": review["source_sidecar"][
                "locator_review_classification"
            ],
            "review_finding_count": review["review_finding_count"],
        },
        "selected_measurement": {
            "measurement_id": review["review_sections"]["lifecycle"]["measurement_id"],
            "label": review["review_sections"]["lifecycle"]["label"],
            "target": copy.deepcopy(review["review_sections"]["lifecycle"]["target"]),
        },
        "review_cards": _review_cards(review),
        "visible_findings": _visible_findings(review),
        "available_review_actions": _available_review_actions(review),
        "action_posture": "labels_only_not_executed",
        "view_effects": {
            "gui_component_runtime": "not_defined",
            "action_execution": "not_performed",
            "backend_lookup": "not_performed",
            "file_observation": "not_performed",
            "legacy_import_acceptance": "not_performed",
            "storage_mutation": "not_performed",
            "record_write": "not_performed",
            "reference_repair": "not_performed",
            "parameter_write_back": "not_performed",
            "measurement_validity": "not_claimed",
            "run_blocking": "not_claimed",
        },
        "attention": _attention(review),
    }
