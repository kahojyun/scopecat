"""Receiving-side inspection workflow for handoff packages.

This candidate composes the existing read-only receiving path for a
directory-shaped package. Given a package directory, it opens the package,
projects it into the plot-first visual-review model, writes a local static HTML
review artifact, and returns a local inspection receipt.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from implementation_candidates.handoff_package_read_view import open_handoff_package_view
from implementation_candidates.handoff_package_visual_artifact import (
    write_handoff_package_visual_review_artifact,
)
from implementation_candidates.handoff_package_visual_review import (
    build_handoff_package_visual_review_model_from_read_view,
)

_EXPECTED_POLICY = {
    "inspection_authority": "caller_provided_package_directory",
    "manifest_preview": "performed_via_read_only_opener_contract",
    "read_only_open": "performed",
    "read_view_projection": "performed",
    "visual_review_model": "performed",
    "local_visual_artifact": "performed",
    "package_acceptance": "not_performed",
    "storage_import": "not_performed",
    "archive_handling": "not_performed",
    "package_integrity": "not_claimed",
    "schema_inference": "not_performed",
    "dataframe_adapter": "not_defined",
    "interactive_gui": "not_defined",
    "shared_measurement_schema": "not_defined",
}


def _codes(items: list[dict[str, Any]] | tuple[dict[str, Any], ...], key: str) -> list[str]:
    return [item[key] for item in items]


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "inspection_workflow_completed",
            "severity": "info",
            "basis": "The package was opened read-only, projected to the visual-review model, and rendered as a local static review artifact.",
            "does_not_claim": "package_import_or_acceptance",
        },
        {
            "code": "local_review_artifact_not_portable",
            "severity": "review",
            "basis": "The generated HTML is a local inspection surface and is not written into the package tree.",
            "does_not_claim": "portable_package_member_or_public_report",
        },
        {
            "code": "package_integrity_not_claimed",
            "severity": "review",
            "basis": "The receiving path keeps declared digest and size facts as package facts without checksum validation.",
            "does_not_claim": "package_integrity_verified",
        },
    ]


def build_handoff_package_inspection_summary(
    package_dir: Path,
    *,
    artifact_output_dir: Path,
    overwrite_artifact: bool = False,
) -> dict[str, Any]:
    """Inspect a handoff package and write a local static visual review artifact."""

    read_view = open_handoff_package_view(package_dir)
    open_summary = read_view.as_open_summary()
    visual_model = build_handoff_package_visual_review_model_from_read_view(read_view)
    artifact_receipt = write_handoff_package_visual_review_artifact(
        visual_model,
        output_dir=artifact_output_dir,
        overwrite=overwrite_artifact,
    )

    return {
        "artifact_posture": "review_summary",
        "inspection_policy": copy.deepcopy(_EXPECTED_POLICY),
        "package": {
            "package_id": read_view.package_id,
            "display_name": read_view.display_name,
            "package_directory_name": package_dir.resolve().name,
            "preview_classification": read_view.preview_classification,
            "measurement_count": len(read_view.measurement_ids),
        },
        "manifest_preview": {
            "performed": True,
            "source": "read_only_opener_contract_reuse",
            "finding_codes": _codes(open_summary["manifest_preview_findings"], "finding"),
            "selected_measurement_count": len(open_summary["selected_measurements"]),
            "linked_context_count": len(open_summary["linked_context"]),
        },
        "read_only_open": {
            "performed": True,
            "classification": open_summary["package"]["classification"],
            "measurement_ids": list(read_view.measurement_ids),
            "open_finding_codes": _codes(open_summary["open_findings"], "finding"),
        },
        "read_view": {
            "performed": True,
            "measurement_ids": list(read_view.measurement_ids),
            "linked_context_ids": [item["link_id"] for item in read_view.linked_context],
            "finding_codes": _codes(read_view.findings, "finding"),
        },
        "visual_review": {
            "performed": True,
            "visual_summary_count": visual_model["package"]["visual_summary_count"],
            "measurement_index_count": len(visual_model["measurement_index"]),
            "attention_codes": _codes(visual_model["attention"], "code"),
        },
        "local_visual_artifact": {
            "performed": True,
            "artifact_posture": artifact_receipt["artifact_posture"],
            "filename": artifact_receipt["html_artifact"]["filename"],
            "local_path": artifact_receipt["html_artifact"]["local_path"],
            "created": artifact_receipt["html_artifact"]["created"],
            "overwritten": artifact_receipt["html_artifact"]["overwritten"],
            "portable_package_member": artifact_receipt["html_artifact"]["portable_package_member"],
        },
        "attention": _attention(),
    }
