"""Structured summary builders for selected-reference comparison findings.

These builders are experimental production-shaped boundaries. They compare
explicit fixture facts only and deliberately do not inspect raw data, source
files, Git state, runtime environments, hardware state, or user-authored
analysis conclusions.
"""

from __future__ import annotations

import copy
import re
from pathlib import PurePosixPath
from typing import Any

_SIDES = {"reference", "current"}
_PRIVATE_TOKEN_MARKERS = {"users", "private"}

_BASIC_SCOPE = [
    "measurement_identity",
    "declared_preview_metadata",
    "quick_preview_compatibility",
    "named_input_snapshots",
    "selected_context_artifacts",
    "declared_facts",
]

_BASIC_NOT_COMPARED = [
    "fit_quality",
    "user_interpretation",
    "raw_waveforms",
    "hardware_runtime_state",
    "experiment_code_context",
]

_CODE_SCOPE = [
    "measurement_identity",
    "recorded_code_context",
    "code_snapshot_record_identity",
    "recorded_code_file_inventory",
    "declared_context_refs",
]

_CODE_NOT_COMPARED = [
    "internal_git_state",
    "dependency_closure",
    "environment_readiness",
    "code_execution",
    "managed_workspace_restore",
    "workflow_dag",
]

_EXPECTED_RECORDING_POLICY = {
    "mode": "minimal_explicit_include_recording",
    "internal_git_inspection": "not_performed",
    "default_file_inclusion": "not_recorded_unless_included",
    "notebook_output_policy": "strip_outputs_before_recording",
    "dependency_discovery": "not_performed",
}

_BASIC_FINDING_ORDER = [
    "same_observed_preview_shape",
    "same_observed_setup_binding",
    "changed_parameter_state",
    "missing_current_fit_summary",
    "unlinked_reference_analysis_note",
    "unverified_mounted_sample_identity",
    "redacted_station_connection_details",
]

_CODE_FINDING_ORDER = [
    "changed_recorded_code_context",
    "changed_code_snapshot_record_identity",
    "same_observed_code_entrypoint",
    "same_observed_notebook_recording_policy",
    "changed_entrypoint_source_observation",
    "same_observed_helper_source_observation",
    "missing_current_readout_correction_helper",
    "missing_reference_readout_correction_v2_helper",
    "same_observed_declared_environment_ref",
    "redacted_external_code_root",
]


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


def _validate_relative_path(path: str, owner: str) -> None:
    if not _path_is_relative(path):
        raise ValueError(f"{owner} path must be relative")


def _validate_redacted_display(value: str, owner: str) -> None:
    if (
        not value
        or "redacted" not in value.lower()
        or "/" in value
        or "\\" in value
        or re.match(r"^[A-Za-z]:", value)
        or value.startswith("~")
        or ":" in value
    ):
        raise ValueError(f"{owner} display must be public-safe and redacted")


def _validate_public_safe_token(value: str, owner: str, *, requires_redacted: bool = False) -> None:
    if (
        not value
        or value.startswith(("/", "~"))
        or "/" in value
        or "\\" in value
        or re.match(r"^[A-Za-z]:", value)
        or ":" in value
        or any(marker in value.lower() for marker in _PRIVATE_TOKEN_MARKERS)
        or (requires_redacted and "redacted" not in value.lower())
    ):
        raise ValueError(f"{owner} must be public-safe")


def _validate_request(
    source: dict[str, Any],
    *,
    expected_scope: list[str],
    expected_not_compared: list[str],
) -> dict[str, Any]:
    request = source["comparison_request"]
    if request["comparison_scope"] != expected_scope:
        raise ValueError("comparison scope must match the selected-reference boundary")
    if request["not_compared_scope"] != expected_not_compared:
        raise ValueError("not-compared scope must match the selected-reference boundary")

    selection = request["reference_selection"]
    if selection["selection_source"] != "user_measurement_mark":
        raise ValueError("selected reference must come from ordinary measurement marks")
    if not selection["mark_label"]:
        raise ValueError("selected reference mark label is required")

    return request


def _validate_measurements(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    request = source["comparison_request"]
    _validate_public_safe_token(request["current_measurement_id"], "current measurement id")
    _validate_public_safe_token(request["reference_measurement_id"], "reference measurement id")
    measurements = _records_by_side(source["measurements"], owner="measurements")
    for measurement in measurements.values():
        _validate_public_safe_token(measurement["measurement_id"], "measurement id")
        _validate_public_safe_token(measurement["sample_id"], "sample id")
        _validate_public_safe_token(measurement["cooldown_id"], "cooldown id")
        _validate_public_safe_token(measurement["source_identity"], "source identity")
        if "primary_data_reference" in measurement:
            _validate_relative_path(measurement["primary_data_reference"], "primary data reference")
    if measurements["reference"]["measurement_id"] != request["reference_measurement_id"]:
        raise ValueError("reference measurement must match comparison request")
    if measurements["current"]["measurement_id"] != request["current_measurement_id"]:
        raise ValueError("current measurement must match comparison request")
    return measurements


def _validate_snapshot_summaries(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    summaries = _records_by_key(source.get("snapshot_summaries", []), "snapshot_id")
    for snapshot in summaries.values():
        _validate_public_safe_token(snapshot["snapshot_id"], "snapshot id")
        _validate_public_safe_token(snapshot["snapshot_family"], "snapshot family")
    for measurement in _validate_measurements(source).values():
        for input_ref in measurement["inputs"]:
            snapshot_id = input_ref["snapshot_id"]
            _validate_public_safe_token(input_ref["name"], "measurement input name")
            _validate_public_safe_token(snapshot_id, "measurement input snapshot id")
            if input_ref["name"] != "code_context" and snapshot_id not in summaries:
                raise ValueError(
                    f"measurement input references missing snapshot summary: {snapshot_id}"
                )
    return summaries


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
            "measurement_id": measurement["measurement_id"],
            "experiment_label": measurement["experiment_label"],
            "sample_id": measurement["sample_id"],
            "cooldown_id": measurement["cooldown_id"],
            "run_start_time": measurement["run_start_time"],
        }
        for measurement in source["measurements"]
    ]


def _inputs_by_name(measurement: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(measurement["inputs"], "name")


def _validate_basic_inputs(source: dict[str, Any]) -> None:
    for measurement in _validate_measurements(source).values():
        if "code_context" in _inputs_by_name(measurement):
            raise ValueError("basic selected-reference comparison must not compare code context")


def _validate_code_measurement_inputs(source: dict[str, Any]) -> None:
    for measurement in _validate_measurements(source).values():
        inputs = _inputs_by_name(measurement)
        if set(inputs) != {"code_context"}:
            raise ValueError(
                "code-context comparison measurements must only reference code_context"
            )


def _snapshot_readiness(source: dict[str, Any], snapshot_id: str) -> str | None:
    return _validate_snapshot_summaries(source)[snapshot_id]["readiness"]


def _input_comparison(source: dict[str, Any]) -> list[dict[str, Any]]:
    measurements = _validate_measurements(source)
    reference_inputs = _inputs_by_name(measurements["reference"])
    current_inputs = _inputs_by_name(measurements["current"])
    for input_ref in list(reference_inputs.values()) + list(current_inputs.values()):
        _validate_public_safe_token(input_ref["name"], "measurement input name")
        _validate_public_safe_token(input_ref["snapshot_id"], "measurement input snapshot id")
    if set(reference_inputs) != set(current_inputs):
        raise ValueError("selected-reference input names must match for this candidate")

    comparison = []
    for name, reference_input in reference_inputs.items():
        current_input = current_inputs[name]
        reference_id = reference_input["snapshot_id"]
        current_id = current_input["snapshot_id"]
        if reference_id == current_id:
            readiness = _snapshot_readiness(source, reference_id)
            finding = (
                "same_observed_redacted" if readiness == "redacted_context" else "same_observed"
            )
        else:
            finding = "changed"
        comparison.append(
            {
                "name": name,
                "reference_snapshot_id": reference_id,
                "current_snapshot_id": current_id,
                "finding": finding,
            }
        )
    return comparison


def _preview_comparison(source: dict[str, Any]) -> dict[str, Any]:
    measurements = _validate_measurements(source)
    reference = measurements["reference"]["declared_preview_metadata"]
    current = measurements["current"]["declared_preview_metadata"]
    if reference != current:
        raise ValueError("preview metadata differences are not supported by this candidate")
    return {
        "finding": "same_observed",
        "shape_kind": reference["shape_kind"],
        "axis_order": copy.deepcopy(reference["axis_order"]),
        "signal": reference["signal"],
        "plot_candidates": copy.deepcopy(reference["plot_candidates"]),
        "future_preview_use": "quick_multi_measurement_browsing",
    }


def _selected_artifacts_by_side(source: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    measurements = _validate_measurements(source)
    return {
        side: measurement.get("selected_context_artifacts", [])
        for side, measurement in measurements.items()
    }


def _declared_facts_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    facts = _records_by_key(source["declared_facts"], "fact_id")
    for fact in facts.values():
        if fact["verification"] == "redacted_for_public_fixture" and fact["value"] != "redacted":
            raise ValueError("redacted declared fact value must stay redacted")
    return facts


def _basic_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    _validate_basic_inputs(source)
    inputs = {item["name"]: item for item in _input_comparison(source)}
    preview = _preview_comparison(source)
    artifacts = _selected_artifacts_by_side(source)
    facts = _declared_facts_by_id(source)
    findings = {}

    if preview["finding"] == "same_observed":
        findings["same_observed_preview_shape"] = {
            "code": "same_observed_preview_shape",
            "kind": "same_observed",
            "subject": "declared_preview_metadata",
            "message": "Both measurements declare the same rectangular 2D heatmap preview shape.",
        }

    setup = inputs.get("setup_binding")
    if setup and setup["finding"] == "same_observed":
        findings["same_observed_setup_binding"] = {
            "code": "same_observed_setup_binding",
            "kind": "same_observed",
            "subject": "setup_binding",
            "message": f"Both measurements reference {setup['reference_snapshot_id']}.",
        }

    parameter = inputs.get("parameter_state")
    if parameter and parameter["finding"] == "changed":
        findings["changed_parameter_state"] = {
            "code": "changed_parameter_state",
            "kind": "changed",
            "subject": "parameter_state",
            "message": (
                f"Reference used {parameter['reference_snapshot_id']}; "
                f"current used {parameter['current_snapshot_id']}."
            ),
        }

    current_fit = [
        artifact
        for artifact in artifacts["current"]
        if artifact["relation"] == "fit_summary" and artifact["availability"] == "missing"
    ]
    if current_fit:
        findings["missing_current_fit_summary"] = {
            "code": "missing_current_fit_summary",
            "kind": "missing",
            "subject": "fit_summary",
            "message": "Current measurement has no linked fit summary in this fixture.",
        }

    reference_notes = [
        artifact
        for artifact in artifacts["reference"]
        if artifact["relation"] == "analysis_note" and artifact["source_relation"] == "unlinked"
    ]
    if reference_notes:
        findings["unlinked_reference_analysis_note"] = {
            "code": "unlinked_reference_analysis_note",
            "kind": "unlinked",
            "subject": "analysis_note",
            "message": "Reference-side analysis note exists but its source relation is uncertain.",
        }

    sample = facts.get("mounted-sample-identity")
    if sample and sample["verification"] == "declared_not_software_verified":
        findings["unverified_mounted_sample_identity"] = {
            "code": "unverified_mounted_sample_identity",
            "kind": "unverified",
            "subject": "mounted_sample_identity",
            "message": "Mounted sample identity is declared but not verified from software evidence.",
        }

    connection = facts.get("station-connection-detail")
    if connection and connection["verification"] == "redacted_for_public_fixture":
        findings["redacted_station_connection_details"] = {
            "code": "redacted_station_connection_details",
            "kind": "redacted",
            "subject": "station_connection_details",
            "message": "Station connection details exist but are hidden in this public-safe fixture.",
        }

    return _ordered_findings(findings, _BASIC_FINDING_ORDER)


def _ordered_findings(
    findings_by_code: dict[str, dict[str, Any]],
    expected_codes: list[str],
) -> list[dict[str, Any]]:
    if set(findings_by_code) != set(expected_codes):
        missing = sorted(set(expected_codes) - set(findings_by_code))
        extra = sorted(set(findings_by_code) - set(expected_codes))
        raise ValueError(
            f"finding codes do not match candidate boundary: missing={missing} extra={extra}"
        )
    return [findings_by_code[code] for code in expected_codes]


def build_selected_reference_context_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build objective selected-reference findings from explicit context input."""
    request = _validate_request(
        source,
        expected_scope=_BASIC_SCOPE,
        expected_not_compared=_BASIC_NOT_COMPARED,
    )
    _validate_measurements(source)
    _validate_basic_inputs(source)
    return {
        "comparison": _comparison_header(request),
        "not_compared_scope": copy.deepcopy(request["not_compared_scope"]),
        "measurement_pair": _measurement_pair(source),
        "input_comparison": _input_comparison(source),
        "preview_comparison": _preview_comparison(source),
        "findings": _basic_findings(source),
        "warnings": [],
    }


def _validate_code_contexts(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    _validate_code_measurement_inputs(source)
    contexts = _records_by_side(source["recorded_code_contexts"], owner="recorded code contexts")
    for context in contexts.values():
        _validate_public_safe_token(context["context_id"], "recorded code context id")
        _validate_public_safe_token(context["code_snapshot_record_id"], "code snapshot record id")
        _validate_public_safe_token(context["external_root_id"], "external root id")
        _validate_redacted_display(context["external_root_display"], "external code root")
        _validate_relative_path(context["entrypoint_path"], "recorded code entrypoint")
        if context["entrypoint_kind"] != "notebook":
            raise ValueError("recorded code entrypoint kind must be notebook")
        if context["entrypoint_recorded_form"] != "source_without_outputs":
            raise ValueError("recorded code entrypoint must be source without outputs")
        if context["execution_claim"] != "not_executed_by_fixture":
            raise ValueError("recorded code context must not claim execution")
        if context["recording_policy"] != _EXPECTED_RECORDING_POLICY:
            raise ValueError("recording policy must preserve no-Git/no-dependency boundary")
        for file_record in context["included_files"]:
            _validate_relative_path(file_record["path"], "recorded code included file")
            _validate_public_safe_token(
                file_record["recorded_source_observation_id"],
                "recorded source observation id",
            )
        included_files = _records_by_key(context["included_files"], "path")
        if context["entrypoint_path"] not in included_files:
            raise ValueError("recorded code context entrypoint must be included")
        _records_by_key(context["declared_context_refs"], "ref_id")
        for context_ref in context["declared_context_refs"]:
            _validate_public_safe_token(context_ref["ref_id"], "declared context ref id")
            _validate_public_safe_token(context_ref["ref_kind"], "declared context ref kind")
        refs_by_kind = _records_by_key(context["declared_context_refs"], "ref_kind")
        if "environment_profile_hint" not in refs_by_kind:
            raise ValueError("recorded code context requires environment profile hint")

    measurements = _validate_measurements(source)
    for side, measurement in measurements.items():
        code_input = _inputs_by_name(measurement)["code_context"]
        if code_input["snapshot_id"] != contexts[side]["context_id"]:
            raise ValueError(f"{side} measurement code input must reference its code context")
    return contexts


def _code_context_pair(source: dict[str, Any]) -> list[dict[str, Any]]:
    _validate_code_contexts(source)
    return [
        {
            "side": context["side"],
            "context_id": context["context_id"],
            "code_snapshot_record_id": context["code_snapshot_record_id"],
            "external_root_id": context["external_root_id"],
            "external_root_display": context["external_root_display"],
            "entrypoint_path": context["entrypoint_path"],
            "entrypoint_kind": context["entrypoint_kind"],
            "entrypoint_recorded_form": context["entrypoint_recorded_form"],
            "included_file_count": len(context["included_files"]),
            "declared_context_ref_count": len(context["declared_context_refs"]),
        }
        for context in source["recorded_code_contexts"]
    ]


def _finding_for_values(reference: Any, current: Any) -> str:
    return "same_observed" if reference == current else "changed"


def _code_context_comparison(source: dict[str, Any]) -> dict[str, Any]:
    contexts = _validate_code_contexts(source)
    reference = contexts["reference"]
    current = contexts["current"]
    reference_refs = _records_by_key(reference["declared_context_refs"], "ref_kind")
    current_refs = _records_by_key(current["declared_context_refs"], "ref_kind")
    return {
        "context_id_finding": _finding_for_values(reference["context_id"], current["context_id"]),
        "code_snapshot_record_identity_finding": _finding_for_values(
            reference["code_snapshot_record_id"], current["code_snapshot_record_id"]
        ),
        "entrypoint_path_finding": _finding_for_values(
            reference["entrypoint_path"], current["entrypoint_path"]
        ),
        "entrypoint_recorded_form_finding": _finding_for_values(
            reference["entrypoint_recorded_form"], current["entrypoint_recorded_form"]
        ),
        "recording_policy_finding": _finding_for_values(
            reference["recording_policy"], current["recording_policy"]
        ),
        "declared_context_ref_finding": _finding_for_values(reference_refs, current_refs),
        "execution_finding": "not_compared",
    }


def _files_by_path(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(context["included_files"], "path")


def _file_inventory_comparison(source: dict[str, Any]) -> list[dict[str, Any]]:
    contexts = _validate_code_contexts(source)
    reference_files = _files_by_path(contexts["reference"])
    current_files = _files_by_path(contexts["current"])
    findings = []

    paths = list(reference_files)
    paths.extend(path for path in current_files if path not in reference_files)
    for path in paths:
        reference_file = reference_files.get(path)
        current_file = current_files.get(path)
        reference_id = (
            None if reference_file is None else reference_file["recorded_source_observation_id"]
        )
        current_id = (
            None if current_file is None else current_file["recorded_source_observation_id"]
        )
        if reference_file is None:
            finding = "missing_on_reference"
        elif current_file is None:
            finding = "missing_on_current"
        else:
            finding = _finding_for_values(reference_id, current_id)
        findings.append(
            {
                "path": path,
                "reference_observation_id": reference_id,
                "current_observation_id": current_id,
                "finding": finding,
            }
        )
    return findings


def _code_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    contexts = _validate_code_contexts(source)
    reference = contexts["reference"]
    current = contexts["current"]
    comparison = _code_context_comparison(source)
    inventory = {item["path"]: item for item in _file_inventory_comparison(source)}
    findings = {}

    if comparison["context_id_finding"] == "changed":
        findings["changed_recorded_code_context"] = {
            "code": "changed_recorded_code_context",
            "kind": "changed",
            "subject": "recorded_code_context",
            "message": (
                f"Reference used {reference['context_id']}; current used {current['context_id']}."
            ),
        }
    if comparison["code_snapshot_record_identity_finding"] == "changed":
        findings["changed_code_snapshot_record_identity"] = {
            "code": "changed_code_snapshot_record_identity",
            "kind": "changed",
            "subject": "code_snapshot_record_identity",
            "message": (
                f"Reference used {reference['code_snapshot_record_id']}; "
                f"current used {current['code_snapshot_record_id']}."
            ),
        }
    if comparison["entrypoint_path_finding"] == "same_observed":
        findings["same_observed_code_entrypoint"] = {
            "code": "same_observed_code_entrypoint",
            "kind": "same_observed",
            "subject": "recorded_code_entrypoint",
            "message": (
                f"Both recorded code contexts use {reference['entrypoint_path']} "
                "as the notebook entrypoint."
            ),
        }
    if reference["recording_policy"]["notebook_output_policy"] == "strip_outputs_before_recording":
        findings["same_observed_notebook_recording_policy"] = {
            "code": "same_observed_notebook_recording_policy",
            "kind": "same_observed",
            "subject": "notebook_recording_policy",
            "message": "Both recorded code contexts record notebooks as source without outputs.",
        }

    entrypoint = inventory[reference["entrypoint_path"]]
    if entrypoint["finding"] == "changed":
        findings["changed_entrypoint_source_observation"] = {
            "code": "changed_entrypoint_source_observation",
            "kind": "changed",
            "subject": reference["entrypoint_path"],
            "message": "The entrypoint path matches, but the recorded source observation IDs differ.",
        }

    helper = inventory.get("helpers/record_measurement_context.py")
    if helper and helper["finding"] == "same_observed":
        findings["same_observed_helper_source_observation"] = {
            "code": "same_observed_helper_source_observation",
            "kind": "same_observed",
            "subject": "helpers/record_measurement_context.py",
            "message": (
                "Both recorded code contexts reference the same recorded helper source observation."
            ),
        }

    missing_current = inventory.get("helpers/readout_correction.py")
    if missing_current and missing_current["finding"] == "missing_on_current":
        findings["missing_current_readout_correction_helper"] = {
            "code": "missing_current_readout_correction_helper",
            "kind": "missing",
            "subject": "helpers/readout_correction.py",
            "message": "The reference recorded this helper, but the current recorded code context does not.",
        }

    missing_reference = inventory.get("helpers/readout_correction_v2.py")
    if missing_reference and missing_reference["finding"] == "missing_on_reference":
        findings["missing_reference_readout_correction_v2_helper"] = {
            "code": "missing_reference_readout_correction_v2_helper",
            "kind": "missing",
            "subject": "helpers/readout_correction_v2.py",
            "message": "The current recorded this helper, but the reference recorded code context does not.",
        }

    refs = _records_by_key(reference["declared_context_refs"], "ref_kind")
    current_refs = _records_by_key(current["declared_context_refs"], "ref_kind")
    environment_ref = refs.get("environment_profile_hint")
    if environment_ref is not None and environment_ref == current_refs.get(
        "environment_profile_hint"
    ):
        findings["same_observed_declared_environment_ref"] = {
            "code": "same_observed_declared_environment_ref",
            "kind": "same_observed",
            "subject": "declared_environment_ref",
            "message": (
                f"Both recorded code contexts declare {environment_ref['ref_id']} "
                "as an environment profile hint."
            ),
        }

    if (
        "redacted" in reference["external_root_display"].lower()
        and "redacted" in current["external_root_display"].lower()
    ):
        findings["redacted_external_code_root"] = {
            "code": "redacted_external_code_root",
            "kind": "redacted",
            "subject": "external_code_root",
            "message": "The external code root display value is redacted in this public-safe fixture.",
        }

    return _ordered_findings(findings, _CODE_FINDING_ORDER)


def build_selected_reference_code_context_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build recorded-code selected-reference findings from explicit context input."""
    request = _validate_request(
        source,
        expected_scope=_CODE_SCOPE,
        expected_not_compared=_CODE_NOT_COMPARED,
    )
    _validate_measurements(source)
    _validate_code_contexts(source)
    return {
        "comparison": _comparison_header(request),
        "not_compared_scope": copy.deepcopy(request["not_compared_scope"]),
        "measurement_pair": _measurement_pair(source),
        "code_context_pair": _code_context_pair(source),
        "code_context_comparison": _code_context_comparison(source),
        "file_inventory_comparison": _file_inventory_comparison(source),
        "findings": _code_findings(source),
        "warnings": [],
    }
