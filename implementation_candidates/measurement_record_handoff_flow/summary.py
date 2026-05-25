"""Provisional vertical flow over existing measurement-record candidates.

This module composes validated slice-local candidates without accepting a
shared measurement schema, final package format, GUI, storage architecture, or
package writer. It consumes explicit accepted-record facts from the legacy
import acceptance candidate, then keeps source observation, export summary,
and handoff package preview side-effect free.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from implementation_candidates.handoff_package_contents_preview import (
    build_handoff_package_contents_preview_summary,
)
from implementation_candidates.measurement_record_handoff_flow.contracts import (
    HandoffFlowContract,
    validate_measurement_record_handoff_flow_contract,
)
from implementation_candidates.measurement_source_observation import observe_measurement_source
from implementation_candidates.selected_measurement_export import (
    build_selected_measurement_export_summary,
)


def _preview_metadata_for_observation(
    accepted_record: dict[str, Any],
    contract: HandoffFlowContract,
    *,
    primary_data_path: str,
) -> dict[str, Any]:
    preview = accepted_record["preview"]
    if preview["status"] != "preview_ready":
        raise ValueError("handoff flow currently requires preview-ready accepted metadata")
    return {
        "status": "preview_ready",
        "metadata_authority": "storage_manifest_declared",
        "data_shape": {
            "kind": preview["shape_kind"],
            "axis_order": list(preview["axis_order"]),
        },
        "declared_columns": [column.to_summary() for column in contract.accepted_preview_columns],
        "plot_candidates": [
            {
                "x": candidate["x"],
                "y": candidate["y"],
                "source": primary_data_path,
            }
            for candidate in preview["plot_candidates"]
        ],
    }


def _observation_input(
    source: dict[str, Any],
    contract: HandoffFlowContract,
) -> dict[str, Any]:
    request = contract.flow_request
    measurement_record = contract.measurement_record
    accepted_record = contract.accepted_record
    accepted_request = contract.acceptance_request
    primary_result = contract.primary_write_result
    primary_data_path = accepted_request.primary_data_path
    return {
        "source_observation_policy": copy.deepcopy(source["source_observation_policy"]),
        "measurement_record": {
            "measurement_record_id": measurement_record.measurement_record_id,
            "label": measurement_record.label,
            "experiment_type": measurement_record.experiment_type,
            "target": request.target,
            "source_kind": measurement_record.source_kind,
            "expected_points": accepted_record["preview"]["declared_row_count"],
        },
        "observation_request": {
            "request_id": request.source_observation_request_id,
            "primary_data_path": primary_data_path,
            "primary_data_format": "csv_table",
            "expected_digest": primary_result.digest,
            "expected_size_bytes": primary_result.bytes_written,
            "expected_rows_recorded": accepted_record["preview"]["declared_row_count"],
        },
        "declared_preview_metadata": _preview_metadata_for_observation(
            accepted_record,
            contract,
            primary_data_path=primary_data_path,
        ),
    }


def _legacy_source_location_input(source: dict[str, Any]) -> dict[str, Any]:
    location = source["legacy_source_location"]
    return {
        "display_path": location["display_path"],
    }


def _export_linked_context(
    legacy_data_id: int,
    contract: HandoffFlowContract,
) -> list[dict[str, Any]]:
    output = []
    for item in contract.accepted_linked_context:
        export_ref = contract.linked_context_export_refs_by_id[item.link_id]
        output.append(
            {
                "kind": item.kind,
                "label": item.label,
                "path": export_ref.path.to_summary(),
                "include_status": export_ref.include_status,
                "relation": export_ref.relation,
                "authority": export_ref.authority,
                "linked_legacy_data_ids": [legacy_data_id],
            }
        )
    return output


def _export_input(source: dict[str, Any], contract: HandoffFlowContract) -> dict[str, Any]:
    request = contract.flow_request
    measurement_record = contract.measurement_record
    accepted_record = contract.accepted_record
    accepted_request = contract.acceptance_request
    legacy_data_id = request.legacy_data_id
    primary_data_path = accepted_request.primary_data_path
    preview = accepted_record["preview"]
    return {
        "legacy_source_location": _legacy_source_location_input(source),
        "selected_export_set": {
            "selection_mode": "single_measurement",
            "selected_legacy_data_ids": [legacy_data_id],
            "traversal_policy": "non_recursive",
        },
        "measurements": [
            {
                "legacy_data_id": legacy_data_id,
                "experiment_label": measurement_record.label,
                "experiment_type": measurement_record.experiment_type,
                "target": request.target,
                "source_file": primary_data_path,
                "export_source": request.export_source_display.to_summary(),
                "source_transform_expectation": {
                    "policy": "no_silent_transform",
                    "message": (
                        "Accepted primary data should not be silently compressed, converted, "
                        "filtered, or replaced by a derived copy during export."
                    ),
                },
                "preview_metadata": {
                    "status": preview["status"],
                    "metadata_authority": "storage_manifest_declared",
                    "data_shape": {
                        "kind": preview["shape_kind"],
                        "axis_order": list(preview["axis_order"]),
                    },
                    "declared_columns": [
                        column.to_summary() for column in contract.accepted_preview_columns
                    ],
                    "plot_candidates": [
                        {
                            "x": candidate["x"],
                            "y": candidate["y"],
                            "source": primary_data_path,
                        }
                        for candidate in preview["plot_candidates"]
                    ],
                },
                "default_bundle": [
                    {
                        "kind": "primary_data",
                        "label": "Accepted primary data",
                        "path": primary_data_path,
                        "include_status": "included_by_default",
                        "relation": "selected_measurement_source",
                        "authority": "imported_record_manifest",
                    }
                ],
            }
        ],
        "linked_context": _export_linked_context(legacy_data_id, contract),
    }


def _classification(
    observation_summary: dict[str, Any],
    package_summary: dict[str, Any],
) -> str:
    if (
        observation_summary["measurement_record"]["classification"]
        != "source_observed_matches_declared_facts"
    ):
        return "handoff_package_needs_source_observation_review"
    if package_summary["package"]["classification"] == "preview_ready_for_opening":
        return "handoff_package_preview_ready"
    return "handoff_package_needs_review"


def _package_manifest_input(
    source: dict[str, Any], contract: HandoffFlowContract
) -> dict[str, Any]:
    manifest = source["handoff_package_manifest"]
    selected = manifest["selected_measurements"]
    if len(selected) != 1:
        raise ValueError("handoff flow currently requires one selected package measurement")
    record = selected[0]
    preview = record["declared_preview_metadata"]
    return {
        "package_preview_policy": copy.deepcopy(manifest["package_preview_policy"]),
        "package_identity": contract.package_identity.to_child_input(),
        "selected_measurements": [
            {
                "measurement_record_id": contract.measurement_record.measurement_record_id,
                "legacy_data_id": contract.flow_request.legacy_data_id,
                "label": contract.measurement_record.label,
                "experiment_type": contract.measurement_record.experiment_type,
                "target": contract.flow_request.target,
                "primary_data": contract.package_primary_data.to_child_input(),
                "declared_preview_metadata": {
                    "status": preview["status"],
                    "metadata_authority": preview["metadata_authority"],
                    "data_shape": {
                        "kind": preview["data_shape"]["kind"],
                        "axis_order": list(preview["data_shape"]["axis_order"]),
                    },
                    "declared_columns": [
                        column.to_summary() for column in contract.package_preview_columns
                    ],
                    "plot_candidates": [
                        {
                            "x": candidate["x"],
                            "y": candidate["y"],
                            "source": candidate["source"],
                        }
                        for candidate in preview["plot_candidates"]
                    ],
                },
                "default_bundle": [contract.package_default_bundle_item.to_child_input()],
            }
        ],
        "linked_context": [item.to_child_input() for item in contract.package_linked_context],
    }


def _accepted_record_summary(contract: HandoffFlowContract) -> dict[str, Any]:
    accepted_record = contract.accepted_record
    return {
        "measurement_record": contract.measurement_record.to_summary(),
        "source_identity": contract.source_identity.to_summary(),
        "acceptance_request": contract.acceptance_request.to_summary(),
        "write_results": [
            contract.write_results_by_kind["primary_data"].to_summary(),
            contract.write_results_by_kind["imported_record_manifest"].to_summary(),
        ],
        "preview": {
            "status": accepted_record["preview"]["status"],
            "metadata_authority": accepted_record["preview"]["metadata_authority"],
            "shape_kind": accepted_record["preview"]["shape_kind"],
            "axis_order": list(accepted_record["preview"]["axis_order"]),
            "declared_row_count": accepted_record["preview"]["declared_row_count"],
            "declared_roles": [column.to_summary() for column in contract.accepted_preview_columns],
            "plot_candidates": [
                {
                    "x": candidate["x"],
                    "y": candidate["y"],
                    "source": candidate["source"],
                }
                for candidate in accepted_record["preview"]["plot_candidates"]
            ],
            "warnings": [],
        },
        "linked_context": [item.to_summary() for item in contract.accepted_linked_context],
    }


def build_measurement_record_handoff_flow_summary(
    source: dict[str, Any],
    *,
    storage_root: Path,
) -> dict[str, Any]:
    """Build one composed measurement-record import-to-handoff flow summary."""
    contract = validate_measurement_record_handoff_flow_contract(source)
    observation_summary = observe_measurement_source(
        _observation_input(source, contract),
        storage_root=storage_root,
    )
    export_summary = build_selected_measurement_export_summary(_export_input(source, contract))
    package_summary = build_handoff_package_contents_preview_summary(
        _package_manifest_input(source, contract)
    )
    primary_result = contract.primary_write_result

    return {
        "flow_policy": copy.deepcopy(source["flow_policy"]),
        "flow": {
            "flow_id": source["flow_request"]["flow_id"],
            "summary_posture": "review_summary",
            "classification": _classification(observation_summary, package_summary),
            "route": [
                "legacy_import_acceptance",
                "measurement_source_observation",
                "selected_measurement_export",
                "handoff_package_contents_preview",
            ],
            "storage_mutation": "not_performed",
            "package_writing": "not_performed",
            "shared_measurement_schema": "not_defined",
        },
        "identity_trace": {
            "measurement_record_id": contract.measurement_record.measurement_record_id,
            "legacy_data_id": contract.flow_request.legacy_data_id,
            "external_record_id": contract.source_identity.external_record_id,
            "stored_primary_data_path": primary_result.path,
            "package_primary_data_path": package_summary["selected_measurements"][0][
                "primary_data"
            ]["package_path"],
            "source_observation_classification": observation_summary["measurement_record"][
                "classification"
            ],
            "package_classification": package_summary["package"]["classification"],
        },
        "accepted_record_summary": _accepted_record_summary(contract),
        "source_observation": observation_summary,
        "selected_measurement_export": export_summary,
        "handoff_package_preview": package_summary,
    }
