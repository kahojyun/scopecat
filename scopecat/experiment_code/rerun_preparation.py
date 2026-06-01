"""Reference-based rerun preparation engineering prototype.

This route-local module is deliberately side-effect free: it does not control
hardware, write parameters, mutate setup bindings, sync environments, import
code, execute code, correct drift, infer cause, guarantee reproducibility, or
define a universal context schema.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

_EXPECTED_POLICY = {
    "rerun_preparation_authority": "selected_reference_seed_summary_only",
    "reference_source": "declared_selected_reference_measurement",
    "context_source": "declared_fixture_records",
    "prepared_context_output": "proposed_manual_run_context_only",
    "shared_context_schema": "not_defined",
    "hardware_control": "not_performed",
    "parameter_write_back": "not_performed",
    "setup_mutation": "not_performed",
    "environment_sync": "not_performed",
    "code_import_execution": "not_performed",
    "automatic_drift_correction": "not_performed",
    "cause_attribution": "not_performed",
    "reproducibility_claim": "not_made",
}

_SUPPORTED_CONTEXT_FAMILIES = {
    "measurement_intent",
    "parameter_state",
    "setup_binding",
    "station_registry",
    "managed_code_version",
    "editable_workspace_observation",
    "declared_environment",
}

_ALLOWED_INCLUDE_STATES = {
    "selected",
    "unavailable",
    "optional_not_selected",
}

_OBSERVATION_FINDINGS_NEEDING_REVIEW = {
    "changed_observed",
    "missing_expected",
    "target_is_symlink",
    "not_a_file",
    "extra_observed",
    "extra_symlink_not_read",
    "extra_unstable_not_read",
    "skipped_redacted",
    "unavailable_reference",
}

_ENVIRONMENT_FINDINGS_NEEDING_REVIEW = {
    "dependency_source_unavailable",
    "runtime_hint_unsupported",
    "package_pin_unpinned",
    "package_pin_unknown",
    "external_tool_unverified",
}

_EXPECTED_REFERENCE_CLAIM = "user_selected_reference_only"
_EXPECTED_PREPARATION_CLAIM = "manual_rerun_seed_summary_only"


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _context_records_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["context_records"], "context_id")


def _references_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["selected_reference_measurements"], "selected_reference_id")


def _preparations_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["rerun_preparations"], "rerun_preparation_id")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["rerun_preparation_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("rerun preparation policy must match the expected policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"rerun preparation policy {key} must be {expected}")


def _validate_context_records(source: dict[str, Any]) -> None:
    _context_records_by_id(source)
    for context in source["context_records"]:
        family = context["family"]
        if family not in _SUPPORTED_CONTEXT_FAMILIES:
            raise ValueError(f"unsupported context family: {family}")
        if context["payload_handling"] != "family_owned_summary_only":
            raise ValueError("context payload handling must remain family-owned")


def _validate_context_ref(
    owner_id: str,
    context_ref: dict[str, Any],
    context_records: dict[str, dict[str, Any]],
) -> None:
    family = context_ref["family"]
    include_state = context_ref["include_state"]
    if family not in _SUPPORTED_CONTEXT_FAMILIES:
        raise ValueError(f"unsupported context family: {family}")
    if include_state not in _ALLOWED_INCLUDE_STATES:
        raise ValueError(f"unsupported include_state: {include_state}")

    context_id = context_ref.get("context_id")
    if include_state == "selected":
        if "missing_reason" in context_ref:
            raise ValueError(f"{owner_id} selected context must not carry missing_reason")
        if context_id not in context_records:
            raise ValueError(f"{owner_id} references missing selected context")
        if context_records[context_id]["family"] != family:
            raise ValueError(f"{owner_id} references context from wrong family")
        return

    if context_id is not None:
        raise ValueError(f"{owner_id} non-selected context must not carry context_id")
    if include_state == "optional_not_selected" and context_ref["required"]:
        raise ValueError(f"{owner_id} optional_not_selected context must not be required")
    if context_ref["required"] and not context_ref.get("missing_reason"):
        raise ValueError(f"{owner_id} required unavailable context needs a reason")


def _selected_context_for_family(
    context_refs: list[dict[str, Any]],
    family: str,
) -> dict[str, Any] | None:
    matches = [
        item
        for item in context_refs
        if item["family"] == family and item["include_state"] == "selected"
    ]
    if len(matches) > 1:
        raise ValueError(f"contains multiple selected {family} contexts")
    return matches[0] if matches else None


def _reference_context_key(context_ref: dict[str, Any]) -> tuple[str, str]:
    return (context_ref["family"], context_ref["role"])


def _validate_preparation_seeded_from_reference(
    preparation: dict[str, Any],
    selected_reference: dict[str, Any],
) -> None:
    reference_links = {
        _reference_context_key(link): link for link in selected_reference["linked_contexts"]
    }
    if len(reference_links) != len(selected_reference["linked_contexts"]):
        raise ValueError("selected reference measurement contains duplicate family role")

    preparation_links = {
        _reference_context_key(link): link for link in preparation["selected_contexts"]
    }
    if set(preparation_links) != set(reference_links):
        raise ValueError("rerun preparation must carry the selected reference context links")

    for selected_context in preparation["selected_contexts"]:
        key = _reference_context_key(selected_context)
        reference_link = reference_links.get(key)
        if reference_link is None:
            raise ValueError("rerun preparation selected context is not linked by reference")
        if selected_context["required"] != reference_link["required"]:
            raise ValueError("rerun preparation required flag does not match reference link")
        if selected_context.get("context_id") != reference_link.get("context_id"):
            raise ValueError("rerun preparation selected context does not match reference link")
        if selected_context["include_state"] != reference_link["include_state"]:
            raise ValueError("rerun preparation include_state does not match reference link")
        if selected_context.get("missing_reason") != reference_link.get("missing_reason"):
            raise ValueError("rerun preparation missing_reason does not match reference link")


def _validate_workspace_observation_alignment(
    owner_id: str,
    context_refs: list[dict[str, Any]],
    context_records: dict[str, dict[str, Any]],
) -> None:
    managed_context = _selected_context_for_family(context_refs, "managed_code_version")
    observation_context = _selected_context_for_family(
        context_refs, "editable_workspace_observation"
    )
    if managed_context is None and observation_context is None:
        return
    if managed_context is None:
        raise ValueError(f"{owner_id} requires selected managed code version")
    if observation_context is None:
        raise ValueError(f"{owner_id} requires selected editable workspace observation")

    managed_id = managed_context["context_id"]
    observation = context_records[observation_context["context_id"]]
    observed_version_id = observation["declared_summary"].get("selected_version_id")
    if observed_version_id != managed_id:
        raise ValueError(
            "editable workspace observation must reference the selected managed code version"
        )


def _validate_environment_alignment(
    owner_id: str,
    context_refs: list[dict[str, Any]],
    context_records: dict[str, dict[str, Any]],
) -> None:
    environment_context = _selected_context_for_family(context_refs, "declared_environment")
    if environment_context is None:
        return

    managed_context = _selected_context_for_family(context_refs, "managed_code_version")
    if managed_context is None:
        raise ValueError(f"{owner_id} requires selected managed code version")

    managed_id = managed_context["context_id"]
    environment = context_records[environment_context["context_id"]]
    environment_version_id = environment["declared_summary"].get("managed_code_version_id")
    if environment_version_id != managed_id:
        raise ValueError(
            "declared environment context must reference the selected managed code version"
        )


def _validate_target_matches_measurement_intent(
    preparation: dict[str, Any],
    context_records: dict[str, dict[str, Any]],
) -> None:
    measurement_intent_context = _selected_context_for_family(
        preparation["selected_contexts"], "measurement_intent"
    )
    if measurement_intent_context is None:
        raise ValueError("rerun preparation requires selected measurement intent")

    intent = context_records[measurement_intent_context["context_id"]]["declared_summary"]
    target = preparation["proposed_run_target"]
    compared_fields = ("experiment_label", "logical_targets", "entrypoint_hint")
    for compared_field in compared_fields:
        if compared_field not in target or compared_field not in intent:
            raise ValueError(
                "proposed run target and selected measurement intent require field: "
                f"{compared_field}"
            )
        if target.get(compared_field) != intent.get(compared_field):
            raise ValueError(
                "proposed run target does not match selected measurement intent field: "
                f"{compared_field}"
            )


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_context_records(source)
    context_records = _context_records_by_id(source)
    references = _references_by_id(source)
    _preparations_by_id(source)

    for selected_reference in source["selected_reference_measurements"]:
        if selected_reference["reference_claim"] != _EXPECTED_REFERENCE_CLAIM:
            raise ValueError(f"selected reference claim must be {_EXPECTED_REFERENCE_CLAIM}")
        seen_roles = set()
        for linked_context in selected_reference["linked_contexts"]:
            role_key = _reference_context_key(linked_context)
            if role_key in seen_roles:
                raise ValueError("selected reference measurement contains duplicate family role")
            seen_roles.add(role_key)
            _validate_context_ref(
                selected_reference["selected_reference_id"], linked_context, context_records
            )
        _validate_workspace_observation_alignment(
            selected_reference["selected_reference_id"],
            selected_reference["linked_contexts"],
            context_records,
        )
        _validate_environment_alignment(
            selected_reference["selected_reference_id"],
            selected_reference["linked_contexts"],
            context_records,
        )

    for preparation in source["rerun_preparations"]:
        if preparation["preparation_claim"] != _EXPECTED_PREPARATION_CLAIM:
            raise ValueError(f"rerun preparation claim must be {_EXPECTED_PREPARATION_CLAIM}")
        selected_reference_id = preparation["selected_reference_id"]
        if selected_reference_id not in references:
            raise ValueError("rerun preparation references missing selected reference")
        selected_reference = references[selected_reference_id]
        if preparation["reference_measurement_id"] != selected_reference["measurement_id"]:
            raise ValueError("rerun preparation reference measurement does not match selection")

        seen_roles = set()
        for selected_context in preparation["selected_contexts"]:
            role_key = _reference_context_key(selected_context)
            if role_key in seen_roles:
                raise ValueError("rerun preparation contains duplicate family role")
            seen_roles.add(role_key)
            _validate_context_ref(
                preparation["rerun_preparation_id"], selected_context, context_records
            )
        _validate_preparation_seeded_from_reference(preparation, selected_reference)
        _validate_workspace_observation_alignment(
            preparation["rerun_preparation_id"],
            preparation["selected_contexts"],
            context_records,
        )
        _validate_environment_alignment(
            preparation["rerun_preparation_id"],
            preparation["selected_contexts"],
            context_records,
        )
        _validate_target_matches_measurement_intent(preparation, context_records)


def _context_record_summary(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "context_id": context["context_id"],
        "family": context["family"],
        "label": context["label"],
        "record_status": context["record_status"],
        "authority": context["authority"],
        "payload_handling": context["payload_handling"],
        "declared_summary": copy.deepcopy(context["declared_summary"]),
    }


def _selected_reference_summary(selected_reference: dict[str, Any]) -> dict[str, Any]:
    selected_count = sum(
        1 for item in selected_reference["linked_contexts"] if item["include_state"] == "selected"
    )
    unavailable_required_count = sum(
        1
        for item in selected_reference["linked_contexts"]
        if item["required"] and item["include_state"] != "selected"
    )
    return {
        "selected_reference_id": selected_reference["selected_reference_id"],
        "measurement_id": selected_reference["measurement_id"],
        "label": selected_reference["label"],
        "selection_reason": selected_reference["selection_reason"],
        "recorded_at": selected_reference["recorded_at"],
        "context_ref_count": len(selected_reference["linked_contexts"]),
        "selected_context_count": selected_count,
        "unavailable_required_context_count": unavailable_required_count,
        "reference_claim": selected_reference["reference_claim"],
    }


def _rerun_preparation_summary(preparation: dict[str, Any]) -> dict[str, Any]:
    required_count = sum(1 for item in preparation["selected_contexts"] if item["required"])
    selected_count = sum(
        1 for item in preparation["selected_contexts"] if item["include_state"] == "selected"
    )
    unavailable_required_count = sum(
        1
        for item in preparation["selected_contexts"]
        if item["required"] and item["include_state"] != "selected"
    )
    return {
        "rerun_preparation_id": preparation["rerun_preparation_id"],
        "label": preparation["label"],
        "selected_reference_id": preparation["selected_reference_id"],
        "reference_measurement_id": preparation["reference_measurement_id"],
        "proposed_run_target": copy.deepcopy(preparation["proposed_run_target"]),
        "context_ref_count": len(preparation["selected_contexts"]),
        "required_context_count": required_count,
        "selected_context_count": selected_count,
        "unavailable_required_context_count": unavailable_required_count,
        "preparation_claim": preparation["preparation_claim"],
    }


def _selected_context_summary(
    rerun_preparation_id: str,
    selected_context: dict[str, Any],
    context_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    output = {
        "rerun_preparation_id": rerun_preparation_id,
        "family": selected_context["family"],
        "role": selected_context["role"],
        "required": selected_context["required"],
        "include_state": selected_context["include_state"],
        "context_id": selected_context.get("context_id"),
        "seeded_from_reference_link": True,
    }
    context = context_records.get(selected_context.get("context_id"))
    if context is not None:
        output["context_label"] = context["label"]
        output["record_status"] = context["record_status"]
        output["authority"] = context["authority"]
    else:
        output["missing_reason"] = selected_context.get("missing_reason")
    return output


def _missing_context_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for preparation in source["rerun_preparations"]:
        for selected_context in preparation["selected_contexts"]:
            if selected_context["include_state"] == "selected":
                continue
            if not selected_context["required"]:
                continue
            findings.append(
                {
                    "rerun_preparation_id": preparation["rerun_preparation_id"],
                    "family": selected_context["family"],
                    "role": selected_context["role"],
                    "severity": "review",
                    "finding": "required_reference_context_unavailable",
                    "basis": selected_context["missing_reason"],
                    "does_not_claim": "run_is_blocked_or_reference_is_invalid",
                }
            )
    return findings


def _workspace_context_findings(
    source: dict[str, Any],
    context_records: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    findings = []
    for preparation in source["rerun_preparations"]:
        observation_context = _selected_context_for_family(
            preparation["selected_contexts"], "editable_workspace_observation"
        )
        if observation_context is None:
            continue

        observation = context_records[observation_context["context_id"]]
        finding_counts = observation["declared_summary"]["finding_counts"]
        review_findings = {
            finding: count
            for finding, count in finding_counts.items()
            if finding in _OBSERVATION_FINDINGS_NEEDING_REVIEW and count > 0
        }
        if review_findings:
            findings.append(
                {
                    "rerun_preparation_id": preparation["rerun_preparation_id"],
                    "context_id": observation["context_id"],
                    "severity": "review",
                    "finding": "workspace_observation_has_review_findings",
                    "basis": copy.deepcopy(review_findings),
                    "does_not_claim": "run_is_blocked_or_workspace_is_unusable",
                }
            )
    return findings


def _environment_context_findings(
    source: dict[str, Any],
    context_records: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    findings = []
    for preparation in source["rerun_preparations"]:
        environment_context = _selected_context_for_family(
            preparation["selected_contexts"], "declared_environment"
        )
        if environment_context is None:
            continue

        environment = context_records[environment_context["context_id"]]
        finding_counts = environment["declared_summary"]["finding_counts"]
        review_findings = {
            finding: count
            for finding, count in finding_counts.items()
            if finding in _ENVIRONMENT_FINDINGS_NEEDING_REVIEW and count > 0
        }
        if review_findings:
            findings.append(
                {
                    "rerun_preparation_id": preparation["rerun_preparation_id"],
                    "context_id": environment["context_id"],
                    "severity": "review",
                    "finding": "declared_environment_has_review_findings",
                    "basis": copy.deepcopy(review_findings),
                    "does_not_claim": "environment_is_synced_runnable_or_reproducible",
                }
            )
    return findings


def _attention(source: dict[str, Any]) -> list[dict[str, Any]]:
    policy = source["rerun_preparation_policy"]
    attention = []

    if any(
        selected_context["include_state"] != "selected" and selected_context["required"]
        for preparation in source["rerun_preparations"]
        for selected_context in preparation["selected_contexts"]
    ):
        attention.append(
            {
                "code": "required_reference_context_unavailable",
                "severity": "review",
                "basis": "At least one required reference-linked context record is unavailable.",
                "does_not_claim": "automatic_run_blocking",
            }
        )

    if policy["reference_source"] == "declared_selected_reference_measurement":
        attention.append(
            {
                "code": "selected_reference_reused_as_seed",
                "severity": "info",
                "basis": "Rerun preparation starts from a declared selected reference measurement.",
                "does_not_claim": "reference_is_scientifically_good_or_reproducible",
            }
        )

    if policy["shared_context_schema"] == "not_defined":
        attention.append(
            {
                "code": "shared_context_schema_not_defined",
                "severity": "info",
                "basis": "The rerun preparation groups family-owned context records by reference.",
                "does_not_claim": "universal_context_payload_schema",
            }
        )

    if policy["hardware_control"] == "not_performed":
        attention.append(
            {
                "code": "hardware_control_not_granted",
                "severity": "review",
                "basis": "Reference-based rerun preparation does not configure instruments.",
                "does_not_claim": "hardware_state_applied",
            }
        )

    if policy["environment_sync"] == "not_performed":
        attention.append(
            {
                "code": "environment_sync_not_performed",
                "severity": "review",
                "basis": "Declared environment context is represented by reference state, not a synced runtime.",
                "does_not_claim": "runnable_environment",
            }
        )

    if policy["code_import_execution"] == "not_performed":
        attention.append(
            {
                "code": "code_execution_not_granted",
                "severity": "review",
                "basis": "Selected code and workspace context are not imported, loaded, or executed.",
                "does_not_claim": "execution_permission",
            }
        )

    if policy["automatic_drift_correction"] == "not_performed":
        attention.append(
            {
                "code": "automatic_drift_correction_not_performed",
                "severity": "review",
                "basis": "Rerun preparation reports context findings without changing files, parameters, or setup bindings.",
                "does_not_claim": "drift_corrected",
            }
        )

    if policy["cause_attribution"] == "not_performed":
        attention.append(
            {
                "code": "cause_attribution_not_performed",
                "severity": "info",
                "basis": "Reference context differences are preparation facts, not explanations for future outcomes.",
                "does_not_claim": "automatic_cause_analysis",
            }
        )

    if policy["reproducibility_claim"] == "not_made":
        attention.append(
            {
                "code": "reproducibility_not_claimed",
                "severity": "review",
                "basis": "A selected reference can seed a manual rerun, but the summary does not guarantee repeatability.",
                "does_not_claim": "experiment_reproducible",
            }
        )

    return attention


@dataclass(frozen=True, init=False)
class ReferenceBasedRerunPreparationRequest:
    """Typed local request for selected-reference manual rerun preparation."""

    _source: dict[str, Any] = field(repr=False)

    def __init__(self, *, source: dict[str, Any]) -> None:
        _validate_references(source)
        object.__setattr__(self, "_source", copy.deepcopy(source))

    @classmethod
    def from_dict(cls, source: dict[str, Any]) -> ReferenceBasedRerunPreparationRequest:
        return cls(source=source)

    @property
    def source(self) -> dict[str, Any]:
        return copy.deepcopy(self._source)


@dataclass(frozen=True, init=False)
class ReferenceBasedRerunPreparationResult:
    """Reference-based rerun preparation summary projection."""

    _summary: dict[str, Any] = field(repr=False)

    def __init__(self, *, summary: dict[str, Any]) -> None:
        object.__setattr__(self, "_summary", copy.deepcopy(summary))

    @property
    def rerun_preparations(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(item) for item in self._summary["rerun_preparations"])

    @property
    def selected_context_refs(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(item) for item in self._summary["selected_context_refs"])

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._summary)


def prepare_reference_based_rerun(
    request: ReferenceBasedRerunPreparationRequest,
) -> ReferenceBasedRerunPreparationResult:
    """Prepare a manual rerun context from an explicit selected reference."""
    source = request.source
    context_records = _context_records_by_id(source)
    summary = {
        "rerun_preparation_policy": copy.deepcopy(source["rerun_preparation_policy"]),
        "selected_reference_measurements": [
            _selected_reference_summary(selected_reference)
            for selected_reference in source["selected_reference_measurements"]
        ],
        "context_records": [
            _context_record_summary(context) for context in source["context_records"]
        ],
        "rerun_preparations": [
            _rerun_preparation_summary(preparation) for preparation in source["rerun_preparations"]
        ],
        "selected_context_refs": [
            _selected_context_summary(
                preparation["rerun_preparation_id"],
                selected_context,
                context_records,
            )
            for preparation in source["rerun_preparations"]
            for selected_context in preparation["selected_contexts"]
        ],
        "missing_context_findings": _missing_context_findings(source),
        "workspace_context_findings": _workspace_context_findings(source, context_records),
        "environment_context_findings": _environment_context_findings(source, context_records),
        "attention": _attention(source),
    }
    return ReferenceBasedRerunPreparationResult(summary=summary)


def build_reference_based_rerun_preparation_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Raw-dictionary adapter for reference-based-rerun fixtures."""
    return prepare_reference_based_rerun(
        ReferenceBasedRerunPreparationRequest.from_dict(source)
    ).to_dict()
