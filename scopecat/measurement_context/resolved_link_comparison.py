"""Resolved measurement-context link comparison engineering prototype.

This module compares explicit measurement-record context links only. It does
not compare measurement intent selectors, raw data, fit quality, context
payloads, hardware state, readiness claims, restore behavior, code import, or
execution.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

_EXPECTED_POLICY = {
    "comparison_authority": "explicit_measurement_record_context_links",
    "reference_selection": "user_measurement_mark",
    "context_payload_handling": "reference_only",
    "intent_selector_comparison": "not_performed",
    "primary_data_comparison": "not_performed",
    "fit_quality_comparison": "not_performed",
    "cause_attribution": "not_performed",
    "readiness_claim": "not_performed",
    "shared_context_schema": "not_defined",
    "recursive_traversal": "not_performed",
    "context_import": "not_performed",
    "hardware_control": "not_performed",
    "parameter_write_back": "not_performed",
    "setup_mutation": "not_performed",
    "environment_sync": "not_performed",
    "code_import_execution": "not_performed",
}

_EXPECTED_SCOPE = [
    "resolved_measurement_context_links",
]

_EXPECTED_NOT_COMPARED = [
    "measurement_intent_selectors",
    "primary_measurement_data",
    "fit_quality",
    "context_payloads",
    "hardware_runtime_state",
    "readiness_or_run_blocking",
    "cause_attribution",
]

_SIDES = {"reference", "current"}

_SUPPORTED_CONTEXT_FAMILIES = {
    "parameter_state",
    "setup_binding",
    "station_registry",
    "managed_code_version",
    "declared_environment",
    "analysis_choice",
    "artifact",
}

_INCLUDE_STATES = {
    "linked",
    "optional_unavailable",
    "optional_not_selected",
}

_FINDING_ORDER = [
    "changed_parameter_state",
    "same_observed_setup_binding",
    "same_observed_managed_code_version",
    "missing_current_declared_environment_context",
]

_PRIVATE_TOKEN_MARKERS = {"users", "private"}


@dataclass(frozen=True, init=False)
class ResolvedContextLinkComparisonRequest:
    """Typed local request for resolved context-link comparison."""

    _source: dict[str, Any] = field(repr=False)

    def __init__(self, *, source: dict[str, Any]) -> None:
        _validate_references(source)
        object.__setattr__(self, "_source", copy.deepcopy(source))

    @classmethod
    def from_dict(cls, source: dict[str, Any]) -> ResolvedContextLinkComparisonRequest:
        return cls(source=source)

    @property
    def source(self) -> dict[str, Any]:
        return copy.deepcopy(self._source)


@dataclass(frozen=True, init=False)
class ResolvedContextLinkComparisonResult:
    """Route-local resolved context-link comparison projection."""

    _summary: dict[str, Any] = field(repr=False)

    def __init__(self, *, summary: dict[str, Any]) -> None:
        object.__setattr__(self, "_summary", copy.deepcopy(summary))

    @property
    def comparison(self) -> dict[str, Any]:
        return copy.deepcopy(self._summary["comparison"])

    @property
    def context_link_comparison(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(item) for item in self._summary["context_link_comparison"])

    @property
    def findings(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(item) for item in self._summary["findings"])

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._summary)


def compare_resolved_context_links(
    request: ResolvedContextLinkComparisonRequest,
) -> ResolvedContextLinkComparisonResult:
    """Compare resolved measurement-record context links."""
    source = request.source
    request_payload = _validate_request(source)
    summary = {
        "comparison": _comparison_header(request_payload),
        "not_compared_scope": copy.deepcopy(request_payload["not_compared_scope"]),
        "measurement_pair": _measurement_pair(source),
        "context_link_comparison": _context_link_comparison(source),
        "findings": _findings(source),
        "attention": _attention(),
    }
    return ResolvedContextLinkComparisonResult(summary=summary)


def build_resolved_context_link_comparison_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Raw-dictionary adapter for resolved context-link comparison."""
    request = ResolvedContextLinkComparisonRequest.from_dict(source)
    return compare_resolved_context_links(request).to_dict()


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _records_by_side(records: list[dict[str, Any]], *, owner: str) -> dict[str, dict[str, Any]]:
    output = _records_by_key(records, "side")
    if set(output) != _SIDES:
        raise ValueError(f"{owner} must contain exactly reference and current sides")
    return output


def _validate_public_safe_token(value: str, owner: str) -> None:
    if (
        not value
        or "/" in value
        or "\\" in value
        or value.startswith("~")
        or re.match(r"^[A-Za-z]:", value)
        or any(part.lower() in _PRIVATE_TOKEN_MARKERS for part in PurePosixPath(value).parts)
    ):
        raise ValueError(f"{owner} must be public-safe")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["comparison_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("comparison policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"comparison policy {key} must be {expected}")


def _validate_request(source: dict[str, Any]) -> dict[str, Any]:
    request = source["comparison_request"]
    _validate_public_safe_token(request["comparison_id"], "comparison id")
    _validate_public_safe_token(request["reference_measurement_id"], "measurement id")
    _validate_public_safe_token(request["current_measurement_id"], "measurement id")
    if request["comparison_scope"] != _EXPECTED_SCOPE:
        raise ValueError("comparison scope must match resolved context-link boundary")
    if request["not_compared_scope"] != _EXPECTED_NOT_COMPARED:
        raise ValueError("not-compared scope must match resolved context-link boundary")
    selection = request["reference_selection"]
    if selection["selection_source"] != "user_measurement_mark":
        raise ValueError("selected reference must come from ordinary measurement marks")
    if not selection["mark_label"]:
        raise ValueError("selected reference mark label is required")
    return request


def _context_records_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["context_records"], "context_id")


def _validate_context_records(source: dict[str, Any]) -> None:
    _context_records_by_id(source)
    for context in source["context_records"]:
        _validate_public_safe_token(context["context_id"], "context id")
        family = context["family"]
        if family not in _SUPPORTED_CONTEXT_FAMILIES:
            raise ValueError(f"unsupported context family: {family}")
        if context["payload_handling"] != "family_owned_summary_only":
            raise ValueError("context payload handling must remain family-owned")


def _link_key(link: dict[str, Any]) -> tuple[str, str, str]:
    return (link["family"], link["role"], link["relation"])


def _validate_link(
    measurement_record_id: str,
    link: dict[str, Any],
    context_records: dict[str, dict[str, Any]],
) -> None:
    _validate_public_safe_token(link["link_id"], "context link id")
    family = link["family"]
    include_state = link["include_state"]
    if family not in _SUPPORTED_CONTEXT_FAMILIES:
        raise ValueError(f"unsupported context link family: {family}")
    if include_state not in _INCLUDE_STATES:
        raise ValueError(f"unsupported include_state: {include_state}")
    if link["required_for_record_validity"]:
        raise ValueError("context links must remain optional for measurement record validity")

    context_id = link.get("context_id")
    if include_state == "linked":
        if context_id not in context_records:
            raise ValueError(
                f"measurement record {measurement_record_id} references missing context"
            )
        if context_records[context_id]["family"] != family:
            raise ValueError(
                f"measurement record {measurement_record_id} references context from wrong family"
            )
        return

    if context_id is not None:
        raise ValueError("unlinked optional context must not carry context_id")
    if include_state == "optional_unavailable" and not link.get("missing_reason"):
        raise ValueError("unavailable optional context requires a missing_reason")


def _validate_measurements(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    request = source["comparison_request"]
    measurements = _records_by_side(source["measurements"], owner="measurements")
    if measurements["reference"]["measurement_record_id"] != request["reference_measurement_id"]:
        raise ValueError("reference measurement must match comparison request")
    if measurements["current"]["measurement_record_id"] != request["current_measurement_id"]:
        raise ValueError("current measurement must match comparison request")

    context_records = _context_records_by_id(source)
    for measurement in measurements.values():
        _validate_public_safe_token(measurement["measurement_record_id"], "measurement id")
        links = measurement["context_links"]
        keys = set()
        link_ids = set()
        for link in links:
            link_id = link["link_id"]
            if link_id in link_ids:
                raise ValueError(f"duplicate link_id: {link_id}")
            link_ids.add(link_id)
            key = _link_key(link)
            if key in keys:
                raise ValueError("measurement context links contain duplicate comparison key")
            keys.add(key)
            _validate_link(measurement["measurement_record_id"], link, context_records)

    reference_keys = {_link_key(link) for link in measurements["reference"]["context_links"]}
    current_keys = {_link_key(link) for link in measurements["current"]["context_links"]}
    if reference_keys != current_keys:
        raise ValueError("reference and current context link keys must match")
    return measurements


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_request(source)
    _validate_context_records(source)
    _validate_measurements(source)


def _comparison_header(request: dict[str, Any]) -> dict[str, Any]:
    selection = request["reference_selection"]
    return {
        "comparison_id": request["comparison_id"],
        "current_measurement_id": request["current_measurement_id"],
        "reference_measurement_id": request["reference_measurement_id"],
        "reference_selection_source": selection["selection_source"],
        "reference_mark_label": selection["mark_label"],
    }


def _measurement_pair(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "side": measurement["side"],
            "measurement_record_id": measurement["measurement_record_id"],
            "label": measurement["label"],
            "experiment_type": measurement["experiment_type"],
            "target": measurement["target"],
            "run_start_time": measurement["run_start_time"],
        }
        for measurement in source["measurements"]
    ]


def _links_by_key(measurement: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    return {_link_key(link): link for link in measurement["context_links"]}


def _context_label(
    context_records: dict[str, dict[str, Any]],
    context_id: str | None,
) -> str | None:
    if context_id is None:
        return None
    return context_records[context_id]["label"]


def _finding_for_pair(reference_link: dict[str, Any], current_link: dict[str, Any]) -> str:
    if reference_link["include_state"] == "linked" and current_link["include_state"] == "linked":
        if reference_link["context_id"] == current_link["context_id"]:
            return "same_observed"
        return "changed"
    if reference_link["include_state"] == "linked":
        return "missing_on_current"
    if current_link["include_state"] == "linked":
        return "missing_on_reference"
    return "same_unavailable"


def _context_link_comparison(source: dict[str, Any]) -> list[dict[str, Any]]:
    measurements = _validate_measurements(source)
    context_records = _context_records_by_id(source)
    reference_links = _links_by_key(measurements["reference"])
    current_links = _links_by_key(measurements["current"])
    comparisons = []
    for key in reference_links:
        reference_link = reference_links[key]
        current_link = current_links[key]
        comparisons.append(
            {
                "family": reference_link["family"],
                "role": reference_link["role"],
                "relation": reference_link["relation"],
                "reference_include_state": reference_link["include_state"],
                "current_include_state": current_link["include_state"],
                "reference_context_id": reference_link.get("context_id"),
                "current_context_id": current_link.get("context_id"),
                "reference_context_label": _context_label(
                    context_records, reference_link.get("context_id")
                ),
                "current_context_label": _context_label(
                    context_records, current_link.get("context_id")
                ),
                "finding": _finding_for_pair(reference_link, current_link),
            }
        )
    return comparisons


def _ordered_findings(findings_by_code: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if set(findings_by_code) != set(_FINDING_ORDER):
        missing = sorted(set(_FINDING_ORDER) - set(findings_by_code))
        extra = sorted(set(findings_by_code) - set(_FINDING_ORDER))
        raise ValueError(
            f"finding codes do not match candidate boundary: missing={missing} extra={extra}"
        )
    return [findings_by_code[code] for code in _FINDING_ORDER]


def _findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    comparisons = {
        (item["family"], item["role"], item["relation"]): item
        for item in _context_link_comparison(source)
    }
    findings = {}

    parameter = comparisons.get(("parameter_state", "calibrated_values", "run_start_context"))
    if parameter and parameter["finding"] == "changed":
        findings["changed_parameter_state"] = {
            "code": "changed_parameter_state",
            "kind": "changed",
            "subject": "parameter_state",
            "message": (
                f"Reference used {parameter['reference_context_id']}; "
                f"current used {parameter['current_context_id']}."
            ),
        }

    setup = comparisons.get(("setup_binding", "logical_to_physical_mapping", "run_start_context"))
    if setup and setup["finding"] == "same_observed":
        findings["same_observed_setup_binding"] = {
            "code": "same_observed_setup_binding",
            "kind": "same_observed",
            "subject": "setup_binding",
            "message": f"Both measurements reference {setup['reference_context_id']}.",
        }

    code = comparisons.get(("managed_code_version", "entrypoint_code_version", "run_start_context"))
    if code and code["finding"] == "same_observed":
        findings["same_observed_managed_code_version"] = {
            "code": "same_observed_managed_code_version",
            "kind": "same_observed",
            "subject": "managed_code_version",
            "message": f"Both measurements reference {code['reference_context_id']}.",
        }

    environment = comparisons.get(
        ("declared_environment", "runtime_environment_hint", "run_start_context")
    )
    if environment and environment["finding"] == "missing_on_current":
        findings["missing_current_declared_environment_context"] = {
            "code": "missing_current_declared_environment_context",
            "kind": "missing",
            "subject": "declared_environment",
            "message": "Reference has declared environment context; current reports it unavailable.",
        }

    return _ordered_findings(findings)


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "resolved_links_only",
            "severity": "info",
            "basis": "Comparison uses measurement-record context links, not measurement intent selectors.",
            "does_not_claim": "intent_selector_comparison",
        },
        {
            "code": "context_payloads_not_compared",
            "severity": "review",
            "basis": "Context record payloads remain family-owned and are not opened or interpreted.",
            "does_not_claim": "semantic_payload_diff",
        },
        {
            "code": "primary_data_not_compared",
            "severity": "review",
            "basis": "Primary measurement data, fit quality, and plots are outside this comparison.",
            "does_not_claim": "scientific_outcome_comparison",
        },
        {
            "code": "cause_attribution_not_performed",
            "severity": "review",
            "basis": "Changed context is reported as comparison evidence only.",
            "does_not_claim": "reason_measurement_changed",
        },
    ]
