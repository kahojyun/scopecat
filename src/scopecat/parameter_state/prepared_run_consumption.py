"""Prepared-run consumption of source-agnostic parameter-state read views."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

_READY_READ_CLASSIFICATION = "stored_parameter_state_read_view_ready"


@dataclass(frozen=True, init=False)
class PreparedRunParameterStateConsumptionRequest:
    """Typed route-local request for prepared-run parameter-state consumption."""

    _source: dict[str, Any] = field(repr=False)

    def __init__(self, *, source: dict[str, Any]) -> None:
        _validate_references(source)
        object.__setattr__(self, "_source", copy.deepcopy(source))

    @classmethod
    def from_dict(cls, source: dict[str, Any]) -> PreparedRunParameterStateConsumptionRequest:
        return cls(source=source)

    @property
    def source(self) -> dict[str, Any]:
        return copy.deepcopy(self._source)

    @property
    def prepared_run_context_id(self) -> str:
        return self._source["consumption_request"]["prepared_run_context_id"]


@dataclass(frozen=True, init=False)
class PreparedRunParameterStateConsumptionResult:
    """Typed route-local result for prepared-run parameter-state consumption."""

    _summary: dict[str, Any] = field(repr=False)

    def __init__(self, *, summary: dict[str, Any]) -> None:
        object.__setattr__(self, "_summary", copy.deepcopy(summary))

    @property
    def classification(self) -> str:
        return self._summary["classification"]

    @property
    def review_findings(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(item) for item in self._summary["review_findings"])

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


def _prepared_contexts_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(
        source["prepared_run_context_summary"]["prepared_run_contexts"],
        "prepared_run_context_id",
    )


def _stored_states_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    states = source["source_agnostic_read_view_summary"]["stored_states"]
    output = {}
    for state in states:
        parameter_state = state.get("parameter_state")
        if parameter_state is None:
            continue
        state_id = parameter_state["state_id"]
        if state_id in output:
            raise ValueError(f"duplicate stored parameter state_id: {state_id}")
        output[state_id] = state
    return output


def _selected_parameter_context(
    source: dict[str, Any],
    prepared_context_id: str,
    role: str,
) -> dict[str, Any] | None:
    matches = [
        item
        for item in source["prepared_run_context_summary"]["selected_context_refs"]
        if item["prepared_run_context_id"] == prepared_context_id
        and item["family"] == "parameter_state"
        and item["role"] == role
    ]
    if len(matches) > 1:
        raise ValueError("prepared run context contains duplicate parameter_state role")
    return matches[0] if matches else None


def _validate_prepared_context_summary(source: dict[str, Any]) -> None:
    _prepared_contexts_by_id(source)


def _validate_read_view_summary(source: dict[str, Any]) -> None:
    summary = source["source_agnostic_read_view_summary"]
    for state in summary["stored_states"]:
        parameter_state = state.get("parameter_state")
        if parameter_state is None:
            continue
        trusted_paths = parameter_state["trusted_entry_paths"]
        if len(trusted_paths) != len(set(trusted_paths)):
            raise ValueError("source-agnostic read view contains duplicate trusted entry path")
        entry_paths = [entry["path"] for entry in state["trusted_entries"]]
        if len(entry_paths) != len(set(entry_paths)):
            raise ValueError("source-agnostic read view contains duplicate trusted entry")
        if set(entry_paths) != set(trusted_paths):
            raise ValueError("source-agnostic read view trusted entries must match trusted paths")
        if parameter_state["entry_count"] != len(state["trusted_entries"]):
            raise ValueError("source-agnostic read view entry_count must match trusted entries")
        for entry in state["trusted_entries"]:
            if entry["trust"] != "review_accepted":
                raise ValueError("source-agnostic consumed entries must be review_accepted")
    _stored_states_by_id(source)


def _validate_request(source: dict[str, Any]) -> None:
    request = source["consumption_request"]
    prepared_contexts = _prepared_contexts_by_id(source)
    prepared_context_id = request["prepared_run_context_id"]
    if prepared_context_id not in prepared_contexts:
        raise ValueError("consumption request references missing prepared run context")
    if request["parameter_context_role"] != "calibrated_values":
        raise ValueError("consumption request parameter_context_role must be calibrated_values")

    parameter_context = _selected_parameter_context(
        source,
        prepared_context_id,
        request["parameter_context_role"],
    )
    if parameter_context is None or parameter_context["include_state"] != "selected":
        return
    if parameter_context.get("context_id") != request["parameter_context_id"]:
        raise ValueError("consumption request parameter_context_id must match selected context")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_prepared_context_summary(source)
    _validate_read_view_summary(source)
    _validate_request(source)


def _selected_stored_state(source: dict[str, Any]) -> dict[str, Any] | None:
    return _stored_states_by_id(source).get(source["consumption_request"]["expected_state_id"])


def _finding(code: str, basis: Any) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "review",
        "basis": copy.deepcopy(basis),
    }


def _review_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    request = source["consumption_request"]
    read_view = source["source_agnostic_read_view_summary"]
    parameter_context = _selected_parameter_context(
        source,
        request["prepared_run_context_id"],
        request["parameter_context_role"],
    )
    selected_state = _selected_stored_state(source)
    findings = []

    if parameter_context is None:
        findings.append(
            _finding(
                "prepared_parameter_context_missing",
                "Prepared run context does not select the requested parameter_state role.",
            )
        )
    elif parameter_context["include_state"] != "selected":
        findings.append(
            _finding(
                "prepared_parameter_context_unavailable", parameter_context.get("missing_reason")
            )
        )

    if selected_state is None:
        findings.append(
            _finding(
                "selected_parameter_state_missing_from_read_view", request["expected_state_id"]
            )
        )
    else:
        state = selected_state["parameter_state"]
        if state["state_id"] != request["expected_state_id"]:
            findings.append(
                _finding(
                    "parameter_state_id_mismatch",
                    {
                        "expected_state_id": request["expected_state_id"],
                        "observed_state_id": state["state_id"],
                    },
                )
            )
        if (
            parameter_context is not None
            and parameter_context.get("context_id") != state["state_id"]
        ):
            findings.append(
                _finding(
                    "prepared_context_state_id_mismatch",
                    {
                        "prepared_context_id": parameter_context.get("context_id"),
                        "read_view_state_id": state["state_id"],
                    },
                )
            )
        if selected_state["classification"] != _READY_READ_CLASSIFICATION:
            findings.append(
                _finding(
                    "selected_parameter_state_read_view_not_ready", selected_state["classification"]
                )
            )
        for finding in selected_state["review_findings"]:
            findings.append(_finding("selected_parameter_state_read_view_finding", finding))

    for finding in read_view["review_findings"]:
        findings.append(_finding("source_agnostic_read_view_finding", finding))
    return findings


def _classification(findings: list[dict[str, Any]]) -> str:
    codes = {finding["code"] for finding in findings}
    if {
        "prepared_parameter_context_missing",
        "prepared_parameter_context_unavailable",
        "selected_parameter_state_missing_from_read_view",
    } & codes:
        return "prepared_run_parameter_state_unavailable_for_review"
    if findings:
        return "prepared_run_parameter_state_needs_review"
    return "prepared_run_parameter_state_ready"


def _prepared_context_output(source: dict[str, Any]) -> dict[str, Any]:
    request = source["consumption_request"]
    prepared_context = _prepared_contexts_by_id(source)[request["prepared_run_context_id"]]
    selected = _selected_parameter_context(
        source,
        request["prepared_run_context_id"],
        request["parameter_context_role"],
    )
    return {
        "prepared_run_context_id": prepared_context["prepared_run_context_id"],
        "label": prepared_context["label"],
        "manual_run_target": copy.deepcopy(prepared_context["manual_run_target"]),
        "parameter_context_ref": copy.deepcopy(selected),
    }


def _parameter_state_output(selected_state: dict[str, Any] | None) -> dict[str, Any] | None:
    if selected_state is None:
        return None
    state = selected_state["parameter_state"]
    return {
        "state_id": state["state_id"],
        "state_kind": state["state_kind"],
        "state_label": state["state_label"],
        "lineage": copy.deepcopy(state["lineage"]),
        "readiness": state["readiness"],
        "trust_status": state["trust_status"],
        "source_kind": selected_state["source_kind"],
        "trusted_entry_count": len(state["trusted_entry_paths"]),
        "read_view_classification": selected_state["classification"],
    }


def _storage_read_facts(selected_state: dict[str, Any] | None) -> dict[str, Any] | None:
    if selected_state is None:
        return None
    observed_by_kind = {item["kind"]: item for item in selected_state["observed_files"]}
    manifest = observed_by_kind["parameter_state_manifest"]
    receipt = observed_by_kind["write_receipt"]
    return {
        "manifest": {
            "path": manifest["path"],
            "status": manifest["status"],
            "observed_digest": manifest["observed_digest"],
            "observed_size_bytes": manifest["observed_size_bytes"],
        },
        "receipt": {
            "path": receipt["path"],
            "status": receipt["status"],
            "observed_digest": receipt["observed_digest"],
            "observed_size_bytes": receipt["observed_size_bytes"],
            "receipt_request_id": selected_state["receipt"]["request_id"]
            if selected_state.get("receipt") is not None
            else None,
        },
    }


def _typed_provenance(selected_state: dict[str, Any] | None) -> dict[str, Any] | None:
    if selected_state is None:
        return None
    return copy.deepcopy(selected_state["typed_provenance"])


def build_prepared_run_source_agnostic_parameter_state_consumption_summary(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Build a run-preparation summary from a source-agnostic parameter-state view."""
    request_model = PreparedRunParameterStateConsumptionRequest.from_dict(source)
    source = request_model.source
    selected_state = _selected_stored_state(source)
    findings = _review_findings(source)
    summary = {
        "consumption_request": copy.deepcopy(source["consumption_request"]),
        "classification": _classification(findings),
        "prepared_run_context": _prepared_context_output(source),
        "parameter_state": _parameter_state_output(selected_state),
        "trusted_entries": copy.deepcopy(selected_state["trusted_entries"])
        if selected_state is not None
        else [],
        "typed_provenance": _typed_provenance(selected_state),
        "storage_read_facts": _storage_read_facts(selected_state),
        "review_findings": findings,
    }
    return PreparedRunParameterStateConsumptionResult(summary=summary).to_dict()
