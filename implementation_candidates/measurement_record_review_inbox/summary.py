"""Product-shape summary builder for a measurement-record review inbox.

This candidate is deliberately side-effect free. It does not scan storage,
open records, refresh read models, save GUI state, approve follow-up actions,
or mutate measurement records.
"""

from __future__ import annotations

import copy
from typing import Any

from implementation_candidates.contract_primitives import (
    validate_non_negative_integer,
    validate_public_identifier,
    validate_relative_path,
    validate_text,
)

_EXPECTED_POLICY = {
    "input_authority": "operator_review_run_and_saved_receipt_summaries",
    "storage_scan": "not_performed",
    "record_open": "not_performed",
    "record_mutation": "not_performed",
    "read_model_refresh": "not_performed",
    "action_approval": "not_granted",
    "gui_state_persistence": "not_performed",
    "public_export": "not_performed",
}


def build_measurement_record_review_inbox_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a local product-shape inbox summary from explicit review facts."""

    _validate_source(source)
    workspace = source["workspace"]
    fresh_review = _fresh_review_from_source(source)
    saved_summaries = source["saved_receipt_summaries"]
    known_record_ids = _known_record_ids(fresh_review)

    ready = [
        _ready_item(entry)
        for entry in fresh_review["catalog_entries"]
        if entry["review_finding_count"] == 0
    ]
    running = [_running_item(item) for item in fresh_review["running_inspections"]]
    needs_review = [_needs_review_item(item) for item in fresh_review["review_findings"]]
    continue_later = [
        _saved_review_item(item, known_record_ids)
        for item in saved_summaries
        if item["operator_disposition"] == "recorded_for_continuation"
    ]
    reviewed = [
        _saved_review_item(item, known_record_ids)
        for item in saved_summaries
        if item["operator_disposition"] == "recorded_as_reviewed"
    ]

    return {
        "artifact_posture": "internal_validation_summary",
        "review_inbox_policy": copy.deepcopy(_EXPECTED_POLICY),
        "workspace": {
            "workspace_id": workspace["workspace_id"],
            "label": workspace["label"],
        },
        "inbox": {
            "classification": _classification(
                ready=ready,
                running=running,
                needs_review=needs_review,
                continue_later=continue_later,
            ),
            "lane_order": ["continue_later", "needs_review", "running", "ready", "reviewed"],
            "lanes": {
                "continue_later": continue_later,
                "needs_review": needs_review,
                "running": running,
                "ready": ready,
                "reviewed": reviewed,
            },
            "counts": {
                "continue_later": len(continue_later),
                "needs_review": len(needs_review),
                "running": len(running),
                "ready": len(ready),
                "reviewed": len(reviewed),
            },
        },
        "attention": _attention(
            needs_review=needs_review,
            running=running,
            continue_later=continue_later,
        ),
        "does_not_claim": [
            "storage_scan",
            "record_open",
            "record_mutation",
            "read_model_refresh",
            "action_approval",
            "canonical_gui_state",
            "public_export",
        ],
    }


def project_operator_review_run_for_review_inbox(operator_review: dict[str, Any]) -> dict[str, Any]:
    """Project the real operator-review output into the inbox's compact input shape."""

    _validate_operator_review_run(operator_review)
    request = _require_dict(operator_review, "request")
    workflow = _require_dict(operator_review, "workflow")
    catalog = _require_dict(operator_review, "catalog")
    catalog_entries = catalog["entries"]
    running_inspections = operator_review["running_inspections"]
    record_dirs = _record_dirs_by_id(catalog_entries, running_inspections)
    record_ids_by_dir = {record_dir: record_id for record_id, record_dir in record_dirs.items()}
    return {
        "request_id": request["request_id"],
        "classification": workflow["classification"],
        "selected_record_id": request["selected_record_id"],
        "catalog_entries": [
            {
                "record_id": entry["record_id"],
                "record_dir": entry["record_dir"],
                "label": entry["record_id"],
                "lifecycle_state": entry["lifecycle_state"],
                "observed_row_count": entry["primary_data"]["observed_row_count"],
                "review_finding_count": entry["review_finding_count"],
            }
            for entry in catalog_entries
        ],
        "running_inspections": [
            {
                "record_id": _require_dict(item, "record")["record_id"],
                "record_dir": _require_dict(item, "record")["record_dir"],
                "label": _require_dict(item, "record")["record_id"],
                "lifecycle_state": "in_progress",
                "visible_rows_recorded": _require_dict(item, "inspection")["visible_rows_recorded"],
                "review_finding_codes": _require_dict(item, "inspection")["review_finding_codes"],
                "next_action": _require_dict(item, "inspection")["next_action"],
            }
            for item in running_inspections
        ],
        "review_findings": [
            _project_review_finding(finding, record_ids_by_dir)
            for finding in operator_review["review_findings"]
        ],
    }


def _validate_source(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_workspace(source["workspace"])
    fresh = _fresh_review_from_source(source)
    saved = source["saved_receipt_summaries"]
    if not isinstance(saved, list):
        raise ValueError("saved_receipt_summaries must be a list")
    _validate_fresh_review(fresh)
    seen_receipts = set()
    for item in saved:
        receipt_id = validate_public_identifier(item["receipt_id"], "receipt_id")
        if receipt_id in seen_receipts:
            raise ValueError(f"duplicate receipt_id: {receipt_id}")
        seen_receipts.add(receipt_id)
        _validate_saved_summary(item)


def _fresh_review_from_source(source: dict[str, Any]) -> dict[str, Any]:
    if "operator_review" in source:
        return project_operator_review_run_for_review_inbox(source["operator_review"])
    return source["fresh_operator_review"]


def _validate_operator_review_run(operator_review: dict[str, Any]) -> None:
    if operator_review["artifact_posture"] != "local_measurement_record_operator_review":
        raise ValueError("operator_review artifact_posture is unsupported")
    workflow = _require_dict(operator_review, "workflow")
    if workflow["classification"] not in {
        "measurement_record_operator_review_ready",
        "measurement_record_operator_review_needed",
    }:
        raise ValueError("operator_review classification is unsupported")
    request = _require_dict(operator_review, "request")
    validate_public_identifier(request["request_id"], "operator_review request_id")
    _validate_optional_record_id(
        request["selected_record_id"],
        "operator_review selected_record_id",
    )
    catalog = _require_dict(operator_review, "catalog")
    for key in ("entries", "review_findings"):
        if not isinstance(catalog[key], list):
            raise ValueError(f"operator_review catalog {key} must be a list")
    if not isinstance(operator_review["running_inspections"], list):
        raise ValueError("operator_review running_inspections must be a list")
    if not isinstance(operator_review["review_findings"], list):
        raise ValueError("operator_review review_findings must be a list")


def _record_dirs_by_id(
    catalog_entries: list[dict[str, Any]],
    running_inspections: list[dict[str, Any]],
) -> dict[str, str]:
    result = {}
    for entry in catalog_entries:
        record_id = validate_public_identifier(entry["record_id"], "catalog record_id")
        result[record_id] = validate_relative_path(entry["record_dir"], "catalog record_dir")
        _require_dict(entry, "primary_data")
    for item in running_inspections:
        record = _require_dict(item, "record")
        inspection = _require_dict(item, "inspection")
        record_id = validate_public_identifier(record["record_id"], "running record_id")
        result[record_id] = validate_relative_path(record["record_dir"], "running record_dir")
        validate_non_negative_integer(
            inspection["visible_rows_recorded"],
            "running visible_rows_recorded",
        )
        _validate_code_list(inspection["review_finding_codes"], "running finding code")
        validate_text(inspection["next_action"], "running next_action")
    return result


def _project_review_finding(
    finding: dict[str, Any],
    record_ids_by_dir: dict[str, str],
) -> dict[str, Any]:
    target = validate_text(finding["target"], "operator review finding target")
    record_id = _record_id_for_target(target, record_ids_by_dir)
    return {
        "record_id": record_id,
        "label": record_id,
        "code": validate_public_identifier(finding["code"], "operator review finding code"),
        "message": validate_text(finding["message"], "operator review finding message"),
        "source": f"operator_review.{validate_text(finding['source'], 'operator review finding source')}",
        "next_action": "review_measurement_record_operator_findings",
    }


def _record_id_for_target(target: str, record_ids_by_dir: dict[str, str]) -> str:
    for record_dir, record_id in sorted(
        record_ids_by_dir.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if target == record_dir or target.startswith(f"{record_dir}/"):
            return record_id
    raise ValueError("operator review finding target must reference a visible record")


def _require_dict(value: dict[str, Any], field: str) -> dict[str, Any]:
    item = value[field]
    if not isinstance(item, dict):
        raise ValueError(f"{field} must be an object")
    return item


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["review_inbox_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("review inbox policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"review inbox policy {key} must be {expected}")


def _validate_workspace(workspace: dict[str, Any]) -> None:
    validate_public_identifier(workspace["workspace_id"], "workspace_id")
    validate_text(workspace["label"], "workspace label")


def _validate_fresh_review(review: dict[str, Any]) -> None:
    validate_public_identifier(review["request_id"], "fresh review request_id")
    if review["classification"] not in {
        "measurement_record_operator_review_ready",
        "measurement_record_operator_review_needed",
    }:
        raise ValueError("fresh review classification is unsupported")
    _validate_optional_record_id(review["selected_record_id"], "fresh review selected_record_id")
    for key in ("catalog_entries", "running_inspections", "review_findings"):
        if not isinstance(review[key], list):
            raise ValueError(f"fresh review {key} must be a list")

    seen_record_ids = set()
    for entry in review["catalog_entries"]:
        record_id = _validate_record_ref(entry)
        if record_id in seen_record_ids:
            raise ValueError(f"duplicate visible record_id: {record_id}")
        seen_record_ids.add(record_id)
        validate_text(entry["label"], "catalog entry label")
        if entry["lifecycle_state"] not in {"complete", "failed"}:
            raise ValueError("catalog entry lifecycle_state is unsupported")
        validate_non_negative_integer(entry["observed_row_count"], "observed_row_count")
        validate_non_negative_integer(entry["review_finding_count"], "review_finding_count")

    for item in review["running_inspections"]:
        record_id = _validate_record_ref(item)
        if record_id in seen_record_ids:
            raise ValueError(f"duplicate visible record_id: {record_id}")
        seen_record_ids.add(record_id)
        validate_text(item["label"], "running inspection label")
        if item["lifecycle_state"] != "in_progress":
            raise ValueError("running inspection lifecycle_state must be in_progress")
        validate_non_negative_integer(item["visible_rows_recorded"], "visible_rows_recorded")
        validate_text(item["next_action"], "running inspection next_action")
        _validate_code_list(item["review_finding_codes"], "running inspection finding code")

    known = _known_record_ids(review)
    for finding in review["review_findings"]:
        record_id = validate_public_identifier(finding["record_id"], "finding record_id")
        if record_id not in known:
            raise ValueError("review finding must reference a visible record")
        validate_public_identifier(finding["code"], "finding code")
        validate_text(finding["label"], "finding label")
        validate_text(finding["message"], "finding message")
        validate_text(finding["source"], "finding source")
        validate_text(finding["next_action"], "finding next_action")


def _validate_saved_summary(item: dict[str, Any]) -> None:
    validate_public_identifier(item["receipt_id"], "receipt_id")
    validate_relative_path(item["review_receipt_path"], "review_receipt_path")
    if item["operator_disposition"] not in {"recorded_for_continuation", "recorded_as_reviewed"}:
        raise ValueError("operator_disposition is unsupported")
    reason = item.get("operator_reason")
    if reason is not None:
        validate_text(reason, "operator_reason")
    review = item["operator_review"]
    validate_public_identifier(review["request_id"], "receipt review request_id")
    validate_public_identifier(review["selected_record_id"], "selected_record_id")
    validate_text(review["selected_record_source"], "selected_record_source")
    validate_text(review["classification"], "receipt review classification")
    validate_text(review["next_action"], "receipt review next_action")
    _validate_code_list(review["review_finding_codes"], "receipt finding code")


def _known_record_ids(review: dict[str, Any]) -> set[str]:
    return {
        *(entry["record_id"] for entry in review["catalog_entries"]),
        *(item["record_id"] for item in review["running_inspections"]),
    }


def _validate_record_ref(item: dict[str, Any]) -> str:
    record_id = validate_public_identifier(item["record_id"], "record_id")
    validate_relative_path(item["record_dir"], "record_dir")
    return record_id


def _validate_optional_record_id(value: Any, owner: str) -> None:
    if value is None:
        return
    validate_public_identifier(value, owner)


def _validate_code_list(value: Any, owner: str) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{owner} list must be a list")
    for item in value:
        validate_public_identifier(item, owner)


def _ready_item(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": entry["record_id"],
        "record_dir": entry["record_dir"],
        "label": entry["label"],
        "state": entry["lifecycle_state"],
        "source": "fresh_operator_review.catalog",
        "primary_count": entry["observed_row_count"],
        "next_action": "open_record_summary",
    }


def _running_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": item["record_id"],
        "record_dir": item["record_dir"],
        "label": item["label"],
        "state": "running",
        "source": "fresh_operator_review.running_inspection",
        "visible_rows_recorded": item["visible_rows_recorded"],
        "review_finding_codes": list(item["review_finding_codes"]),
        "next_action": item["next_action"],
    }


def _needs_review_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": item["record_id"],
        "label": item["label"],
        "state": "needs_review",
        "source": item["source"],
        "finding_code": item["code"],
        "message": item["message"],
        "next_action": item["next_action"],
    }


def _saved_review_item(item: dict[str, Any], known_record_ids: set[str]) -> dict[str, Any]:
    review = item["operator_review"]
    return {
        "receipt_id": item["receipt_id"],
        "review_receipt_path": item["review_receipt_path"],
        "record_id": review["selected_record_id"],
        "record_visibility": (
            "visible" if review["selected_record_id"] in known_record_ids else "not_visible"
        ),
        "state": item["operator_disposition"],
        "source": "saved_operator_review_receipt_summary",
        "operator_reason": item.get("operator_reason"),
        "review_finding_codes": list(review["review_finding_codes"]),
        "next_action": review["next_action"],
    }


def _classification(
    *,
    ready: list[dict[str, Any]],
    running: list[dict[str, Any]],
    needs_review: list[dict[str, Any]],
    continue_later: list[dict[str, Any]],
) -> str:
    if needs_review or continue_later:
        return "review_inbox_attention"
    if running or ready:
        return "review_inbox_ready"
    return "review_inbox_empty"


def _attention(
    *,
    needs_review: list[dict[str, Any]],
    running: list[dict[str, Any]],
    continue_later: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    attention = []
    if continue_later:
        attention.append(
            {
                "code": "saved_review_continuation_available",
                "count": len(continue_later),
                "does_not_claim": "retry_or_action_authority",
            }
        )
    if needs_review:
        attention.append(
            {
                "code": "records_need_review",
                "count": len(needs_review),
                "does_not_claim": "record_is_invalid_or_repairable",
            }
        )
    if running:
        attention.append(
            {
                "code": "running_records_visible",
                "count": len(running),
                "does_not_claim": "live_monitor_or_subscription_active",
            }
        )
    return attention
