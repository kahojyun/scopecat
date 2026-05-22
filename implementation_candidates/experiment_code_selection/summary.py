"""Structured summary builder for experiment code selection.

This module is an experimental production-shaped boundary. It is deliberately
side-effect free: it does not read source files, inspect Git state, scan
unselected folders, discover dependencies, import code, execute code, restore
environments, materialize workspaces, or define workflow/DAG contracts.
"""

from __future__ import annotations

import copy
from typing import Any


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _root_ids(source: dict[str, Any]) -> set[str]:
    return {root["root_id"] for root in source["external_code_roots"]}


def _contexts_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["selected_code_contexts"], "context_id")


def _whitelisted_paths(context: dict[str, Any]) -> list[str]:
    return [item["path"] for item in context["whitelisted_files"]]


def _validate_references(source: dict[str, Any]) -> None:
    roots = _root_ids(source)
    contexts = _contexts_by_id(source)

    for context in source["selected_code_contexts"]:
        external_root_id = context["external_root_id"]
        if external_root_id not in roots:
            raise ValueError(f"selected code context references missing root: {external_root_id}")

        entrypoint = context["entrypoint"]
        if entrypoint["path"] not in _whitelisted_paths(context):
            raise ValueError("selected code context entrypoint must be whitelisted")
        if (
            entrypoint["kind"] == "notebook"
            and entrypoint["recorded_form"] != "source_without_outputs"
        ):
            raise ValueError("notebook entrypoint must be recorded without outputs")

    for step in source.get("calibration_steps", []):
        for input_ref in step["inputs"]:
            if input_ref["name"] == "code_context" and input_ref["snapshot_id"] not in contexts:
                raise ValueError("calibration step references missing code context")

    for candidate in source["captured_version_candidates"]:
        source_context_id = candidate["source_context_id"]
        if source_context_id not in contexts:
            raise ValueError(
                f"captured version candidate references missing context: {source_context_id}"
            )
        source_context = contexts[source_context_id]
        scope = candidate["capture_scope"]
        if scope["root_id"] != source_context["external_root_id"]:
            raise ValueError("captured version root must match source context root")
        if scope["whitelisted_files"] != _whitelisted_paths(source_context):
            raise ValueError("captured version whitelist must match source context whitelist")


def _external_code_root_summary(root: dict[str, Any]) -> dict[str, Any]:
    return {
        "root_id": root["root_id"],
        "mode": root["mode"],
        "authority": root["authority"],
    }


def _selected_context_summary(context: dict[str, Any]) -> dict[str, Any]:
    entrypoint = context["entrypoint"]
    return {
        "context_id": context["context_id"],
        "external_root_id": context["external_root_id"],
        "context_role": context["context_role"],
        "entrypoint_path": entrypoint["path"],
        "entrypoint_kind": entrypoint["kind"],
        "entrypoint_recorded_form": entrypoint["recorded_form"],
        "execution_claim": entrypoint["execution_claim"],
        "whitelisted_file_count": len(context["whitelisted_files"]),
        "declared_context_ref_count": len(context["declared_context_refs"]),
        "mutation_capability": context["mutation_capability"]["classification"],
    }


def _whitelisted_file_summaries(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "context_id": context["context_id"],
            "path": item["path"],
            "role": item["role"],
            "recorded_form": item["recorded_form"],
        }
        for context in source["selected_code_contexts"]
        for item in context["whitelisted_files"]
    ]


def _declared_context_refs(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        copy.deepcopy(ref)
        for context in source["selected_code_contexts"]
        for ref in context["declared_context_refs"]
    ]


def _not_recorded_policy(source: dict[str, Any]) -> list[dict[str, Any]]:
    policy = []
    for context in source["selected_code_contexts"]:
        policy.extend(copy.deepcopy(context["not_recorded_policy"]))
    return policy


def _calibration_step_reference(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "step_id": step["step_id"],
        "step_label": step["step_label"],
        "inputs": copy.deepcopy(step["inputs"]),
    }


def _captured_version_candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    scope = candidate["capture_scope"]
    return {
        "candidate_id": candidate["candidate_id"],
        "source_context_id": candidate["source_context_id"],
        "candidate_status": candidate["candidate_status"],
        "materialization_intent": candidate["materialization_intent"],
        "storage_claim": candidate["storage_claim"],
        "whitelisted_files": list(scope["whitelisted_files"]),
        "notebook_recording_policy": scope["notebook_recording_policy"],
        "default_file_inclusion": scope["default_file_inclusion"],
    }


def _attention(source: dict[str, Any]) -> list[dict[str, Any]]:
    attention = []
    notebook_files = [
        item
        for context in source["selected_code_contexts"]
        for item in context["whitelisted_files"]
        if item["path"].endswith(".ipynb")
    ]
    if source["capture_policy"][
        "notebook_output_policy"
    ] == "strip_outputs_before_recording" and any(
        item["recorded_form"] == "source_without_outputs" for item in notebook_files
    ):
        attention.append(
            {
                "code": "notebook_outputs_stripped",
                "severity": "info",
                "basis": "Whitelisted notebooks are recorded as source without outputs.",
                "does_not_claim": "notebook_execution_reproduced",
            }
        )

    if source["capture_policy"]["default_file_inclusion"] == "not_recorded_unless_whitelisted":
        attention.append(
            {
                "code": "unwhitelisted_files_not_recorded",
                "severity": "info",
                "basis": "Early capture records only whitelisted files and declared refs.",
                "does_not_claim": "folder_fully_analyzed",
            }
        )

    if source["capture_policy"]["internal_git_inspection"] == "not_performed":
        attention.append(
            {
                "code": "internal_git_not_inspected",
                "severity": "info",
                "basis": "Git state is ignored in this early-adoption boundary.",
                "does_not_claim": "git_clean_or_dirty_status",
            }
        )

    if any(
        context["mutation_capability"]["execution_permission"] == "not_granted_by_selection_record"
        for context in source["selected_code_contexts"]
    ):
        attention.append(
            {
                "code": "code_execution_not_granted",
                "severity": "review",
                "basis": "Selection and capture do not execute, import, or validate code.",
                "does_not_claim": "execution_permission",
            }
        )
    return attention


def build_experiment_code_selection_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a structured selected-code summary from explicit fixture input."""
    _validate_references(source)
    return {
        "capture_policy": copy.deepcopy(source["capture_policy"]),
        "external_code_roots": [
            _external_code_root_summary(root) for root in source["external_code_roots"]
        ],
        "selected_code_contexts": [
            _selected_context_summary(context) for context in source["selected_code_contexts"]
        ],
        "whitelisted_files": _whitelisted_file_summaries(source),
        "declared_context_refs": _declared_context_refs(source),
        "not_recorded_policy": _not_recorded_policy(source),
        "calibration_step_references": [
            _calibration_step_reference(step) for step in source.get("calibration_steps", [])
        ],
        "captured_version_candidates": [
            _captured_version_candidate_summary(candidate)
            for candidate in source["captured_version_candidates"]
        ],
        "attention": _attention(source),
    }
