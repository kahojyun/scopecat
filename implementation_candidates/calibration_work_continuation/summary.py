"""Structured summary builder for calibration work continuation.

This module is an experimental production-shaped boundary. It is deliberately
side-effect free: it does not execute calibration code, read source files, fit
data, apply parameter writes, schedule work, retry steps, or control hardware.
"""

from __future__ import annotations

from typing import Any


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _observed_record_groups(source: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    observed = source["observed_records"]
    return {
        "measurements": list(observed.get("measurements", [])),
        "parameter_snapshots": list(observed.get("parameter_snapshots", [])),
        "fit_previews": list(observed.get("fit_previews", [])),
        "proposed_writes": list(observed.get("proposed_writes", [])),
        "applied_writes": list(observed.get("applied_writes", [])),
    }


def _related_record_ids(
    records: list[dict[str, Any]], step_id: str, relation_key: str
) -> list[str]:
    return [record["record_id"] for record in records if record.get(relation_key) == step_id]


def _review_by_step(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source.get("known_review_state", []), "related_step")


def _blocking_by_step(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source.get("known_blocking", []), "blocked_step")


def _planned_steps_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["declared_step_plan"], "planned_step_id")


def _fit_previews_by_record_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(_observed_record_groups(source)["fit_previews"], "record_id")


def _proposed_writes_for_step(source: dict[str, Any], step_id: str) -> list[dict[str, Any]]:
    return [
        record
        for record in _observed_record_groups(source)["proposed_writes"]
        if record["related_step"] == step_id
    ]


def _validate_references(source: dict[str, Any]) -> None:
    steps = _planned_steps_by_id(source)
    reviews = _records_by_key(source.get("known_review_state", []), "review_id")
    fit_previews = _fit_previews_by_record_id(source)
    output_ids = {
        record["record_id"]
        for records in _observed_record_groups(source).values()
        for record in records
        if "record_id" in record
    }

    for review in source.get("known_review_state", []):
        related_step = review["related_step"]
        if related_step not in steps:
            raise ValueError(f"review references missing step: {related_step}")
        reason_source = review["reason_source"]
        if reason_source not in fit_previews:
            raise ValueError(f"review references missing reason_source: {reason_source}")
        fit_preview = fit_previews[reason_source]
        if fit_preview["related_step"] != related_step:
            raise ValueError("review reason_source belongs to a different step")
        if (
            fit_preview["status"] == "failed_quality_review"
            and fit_preview["quality_score"] >= fit_preview["quality_threshold"]
        ):
            raise ValueError("failed quality review source is not below threshold")
        if not _proposed_writes_for_step(source, related_step):
            raise ValueError("review step has no proposed write to review")

    for block in source.get("known_blocking", []):
        blocked_step = block["blocked_step"]
        if blocked_step not in steps:
            raise ValueError(f"blocking references missing step: {blocked_step}")
        for blocked_by in block["blocked_by"]:
            if not blocked_by.startswith("review:"):
                raise ValueError(f"unsupported blocking reference: {blocked_by}")
            review_id = blocked_by.removeprefix("review:")
            if review_id not in reviews:
                raise ValueError(f"blocking references missing review: {review_id}")

    for proposed_write in _observed_record_groups(source)["proposed_writes"]:
        related_step = proposed_write["related_step"]
        if related_step not in steps:
            raise ValueError(f"proposed write references missing step: {related_step}")
        if proposed_write["current_value_source"] not in output_ids:
            raise ValueError("proposed write references missing current_value_source")
        if proposed_write["proposed_value_source"] not in output_ids:
            raise ValueError("proposed write references missing proposed_value_source")

    for applied_write in _observed_record_groups(source)["applied_writes"]:
        related_step = applied_write["related_step"]
        if related_step not in steps:
            raise ValueError(f"applied write references missing step: {related_step}")


def _outputs_for_step(source: dict[str, Any], step_id: str) -> list[str]:
    records = _observed_record_groups(source)
    outputs = []
    outputs.extend(_related_record_ids(records["measurements"], step_id, "produced_by_step"))
    outputs.extend(_related_record_ids(records["parameter_snapshots"], step_id, "related_step"))
    outputs.extend(_related_record_ids(records["fit_previews"], step_id, "related_step"))
    outputs.extend(_related_record_ids(records["proposed_writes"], step_id, "related_step"))
    return outputs


def _step_lifecycle(source: dict[str, Any], step_id: str) -> tuple[str, str, list[str] | None]:
    review = _review_by_step(source)
    blocking = _blocking_by_step(source)
    records = _observed_record_groups(source)

    if step_id in blocking:
        return (
            "blocked",
            "assembled_from_known_blocking",
            list(blocking[step_id]["blocked_by"]),
        )
    if step_id in review:
        return "review_needed", "assembled_from_known_review_state", None
    if any(
        record.get("produced_by_step") == step_id and record.get("status") == "completed"
        for record in records["measurements"]
    ):
        return "completed", "assembled_from_observed_records", None
    return "pending", "assembled_from_declared_step_plan", None


def _step_summary(source: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
    step_id = step["planned_step_id"]
    lifecycle_state, lifecycle_source, blocked_by = _step_lifecycle(source, step_id)
    output = {
        "step_id": step_id,
        "order": step["order"],
        "label": step["label"],
        "target": step["target"],
        "purpose": step["purpose"],
        "user_authored_entrypoint": step["user_authored_entrypoint"],
        "lifecycle_state": lifecycle_state,
        "continuation_policy": step["continuation_policy"],
        "outputs": _outputs_for_step(source, step_id),
        "plan_source": "fixture_declared",
        "lifecycle_source": lifecycle_source,
    }
    if blocked_by is not None:
        output["blocked_by"] = blocked_by
    return output


def _measurement_output(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "output_id": record["record_id"],
        "kind": "measurement_reference",
        "measurement_id": record["measurement_id"],
        "legacy_data_id": record["legacy_data_id"],
        "label": record["label"],
        "path": record["path"],
        "authority": record["authority"],
    }


def _snapshot_output(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "output_id": record["record_id"],
        "kind": "parameter_snapshot",
        "label": record["label"],
        "path": record["path"],
        "authority": record["authority"],
    }


def _fit_preview_output(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "output_id": record["record_id"],
        "kind": "fit_preview",
        "label": record["label"],
        "path": record["path"],
        "status": record["status"],
        "quality_score": record["quality_score"],
        "quality_threshold": record["quality_threshold"],
        "durable_analysis_result": record["durable_analysis_result"],
        "authority": record["authority"],
    }


def _outputs_summary(source: dict[str, Any]) -> list[dict[str, Any]]:
    records = _observed_record_groups(source)
    outputs = []
    outputs.extend(_measurement_output(record) for record in records["measurements"])
    outputs.extend(_snapshot_output(record) for record in records["parameter_snapshots"])
    outputs.extend(_fit_preview_output(record) for record in records["fit_previews"])
    return outputs


def _records_for_review(source: dict[str, Any], related_step: str) -> list[str]:
    records = _observed_record_groups(source)
    known = []
    known.extend(_related_record_ids(records["measurements"], related_step, "produced_by_step"))
    known.extend(_related_record_ids(records["fit_previews"], related_step, "related_step"))
    known.extend(_related_record_ids(records["parameter_snapshots"], related_step, "related_step"))
    return known


def _review_reason(source: dict[str, Any], review: dict[str, Any]) -> str:
    fit_preview = _records_by_key(_observed_record_groups(source)["fit_previews"], "record_id").get(
        review["reason_source"]
    )
    if fit_preview and fit_preview["status"] == "failed_quality_review":
        return "Fit quality is below the fixture-declared threshold."
    return "Review is required by fixture-declared state."


def _review_gate_summary(source: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    return {
        "review_id": review["review_id"],
        "step_id": review["related_step"],
        "status": review["status"],
        "reason": _review_reason(source, review),
        "known": _records_for_review(source, review["related_step"]),
        "missing_or_unverified": list(review["missing_or_unverified"]),
        "requested_decision": review["requested_decision"],
        "source": review["authority"],
    }


def _review_gates_summary(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [_review_gate_summary(source, review) for review in source.get("known_review_state", [])]


def _review_id_for_step(source: dict[str, Any], step_id: str) -> str | None:
    review = _review_by_step(source).get(step_id)
    if review is None:
        return None
    return review["review_id"]


def _declared_write_summary(source: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    review_id = _review_id_for_step(source, record["related_step"])
    output = {
        "write_id": record["write_id"],
        "step_id": record["related_step"],
        "status": record["status"],
        "parameter_path": record["parameter_path"],
        "current_value": record["current_value"],
        "current_value_source": record["current_value_source"],
        "proposed_value": record["proposed_value"],
        "proposed_value_source": record["proposed_value_source"],
        "unit": record["unit"],
        "authority": record["authority"],
    }
    if review_id is not None:
        output["requires_review"] = review_id
    return output


def _declared_writes_summary(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _declared_write_summary(source, record)
        for record in _observed_record_groups(source)["proposed_writes"]
    ]


def _applied_write_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "write_id": record["write_id"],
        "step_id": record["related_step"],
        "status": record["status"],
        "parameter_path": record["parameter_path"],
        "applied_value": record["applied_value"],
        "unit": record["unit"],
        "authority": record["authority"],
    }


def _applied_writes_summary(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _applied_write_summary(record)
        for record in _observed_record_groups(source)["applied_writes"]
    ]


def _step_label(source: dict[str, Any], step_id: str) -> str:
    return _planned_steps_by_id(source)[step_id]["label"]


def _step_target(source: dict[str, Any], step_id: str) -> str:
    return _planned_steps_by_id(source)[step_id]["target"]


def _require_unique_action_ids(actions: list[dict[str, Any]]) -> None:
    action_ids = [action["action_id"] for action in actions]
    duplicates = {action_id for action_id in action_ids if action_ids.count(action_id) > 1}
    if duplicates:
        raise ValueError(f"duplicate requested action id: {sorted(duplicates)[0]}")


def _requested_next_actions(source: dict[str, Any]) -> list[dict[str, Any]]:
    actions = []
    for review in source.get("known_review_state", []):
        related_step = review["related_step"]
        review_id = review["review_id"]
        step_label = _step_label(source, related_step)
        step_target = _step_target(source, related_step)
        actions.extend(
            [
                {
                    "action_id": f"review-{review_id}",
                    "label": f"Review {step_label} and choose: accept value, rerun, or skip target",
                    "kind": "manual_review",
                    "available": True,
                },
                {
                    "action_id": f"rerun-{related_step}",
                    "label": f"Rerun {step_label}",
                    "kind": "manual_continuation_choice",
                    "available": True,
                },
                {
                    "action_id": f"skip-{step_target}-for-{review_id}",
                    "label": f"Skip {step_target} for this calibration episode",
                    "kind": "manual_continuation_choice",
                    "available": True,
                    "requires_review": review_id,
                },
            ]
        )

        for proposed_write in _proposed_writes_for_step(source, related_step):
            actions.insert(
                -2,
                {
                    "action_id": f"accept-{proposed_write['write_id']}-outside-scopecat",
                    "label": (
                        f"Accept proposed {proposed_write['parameter_path']} "
                        "outside Scopecat after review"
                    ),
                    "kind": "manual_write_choice",
                    "available": True,
                    "requires_review": review_id,
                },
            )

        for block in source.get("known_blocking", []):
            if f"review:{review_id}" in block["blocked_by"]:
                blocked_step = block["blocked_step"]
                actions.append(
                    {
                        "action_id": f"continue-{blocked_step}",
                        "label": f"Continue {_step_label(source, blocked_step)}",
                        "kind": "manual_continuation_choice",
                        "available": False,
                        "blocked_by": list(block["blocked_by"]),
                    }
                )
    _require_unique_action_ids(actions)
    return actions


def _attention(source: dict[str, Any]) -> list[dict[str, Any]]:
    attention = []
    for fit_preview in _observed_record_groups(source)["fit_previews"]:
        if (
            fit_preview["status"] == "failed_quality_review"
            and fit_preview["quality_score"] < fit_preview["quality_threshold"]
        ):
            attention.append(
                {
                    "code": "fit_failed_quality_review",
                    "subject": fit_preview["record_id"],
                    "message": (
                        "Rabi amplitude fit preview failed the fixture-declared quality review."
                    ),
                }
            )

    for block in source.get("known_blocking", []):
        attention.append(
            {
                "code": "downstream_step_blocked",
                "subject": block["blocked_step"],
                "message": "T1 check is blocked until the Rabi review gate is resolved.",
            }
        )

    for proposed_write in _observed_record_groups(source)["proposed_writes"]:
        if proposed_write["status"] == "proposed_not_applied":
            attention.append(
                {
                    "code": "write_requires_review",
                    "subject": proposed_write["write_id"],
                    "message": (
                        "Pulse amplitude write is proposed by user-authored code "
                        "and has not been applied."
                    ),
                }
            )
    return attention


def build_calibration_continuation_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a structured continuation summary from scattered fixture context."""
    declared = source["declared_intent"]
    _validate_references(source)
    return {
        "episode": {
            "episode_id": declared["episode_id"],
            "label": declared["label"],
            "target_group": declared["target_group"],
            "operator_intent": declared["operator_intent"],
            "execution_context": dict(declared["execution_context"]),
        },
        "steps": [_step_summary(source, step) for step in source["declared_step_plan"]],
        "outputs": _outputs_summary(source),
        "review_gates": _review_gates_summary(source),
        "declared_writes": _declared_writes_summary(source),
        "applied_writes": _applied_writes_summary(source),
        "requested_next_actions": _requested_next_actions(source),
        "attention": _attention(source),
    }
