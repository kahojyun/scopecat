"""Route-local compatibility contract for the current handoff slice."""

from __future__ import annotations

from typing import Any

HANDOFF_COMPATIBILITY_CONTRACT_VERSION = "scopecat.handoff.compatibility.v0"


def current_handoff_compatibility_contract() -> dict[str, Any]:
    """Return the current route-local compatibility surface for review."""

    return {
        "artifact_posture": "local_handoff_compatibility_contract",
        "contract_version": HANDOFF_COMPATIBILITY_CONTRACT_VERSION,
        "scope": {
            "owner": "JNY-001 production vertical slice",
            "stability": "route_local_current_slice",
            "public_sdk": "not_defined",
            "final_package_format": "not_claimed",
        },
        "local_artifact_postures": [
            "local_write_receipt",
            "local_workflow_receipt",
            "review_summary",
            "local_review_summary",
            "local_context_reference_summary",
            "local_selected_record_export_receipt",
            "local_selected_record_batch_export_receipt",
            "local_receiving_gate_receipt",
            "local_import_plan_receipt",
            "local_handoff_durable_import_receipt",
            "local_handoff_durable_import_receipt_summary",
            "local_handoff_durable_import_retry_review",
            "local_jny001_operator_smoke_summary",
            "local_receiving_review_state_projection",
            "local_receiving_review_state_receipt",
            "local_archive_materialization_contract",
            "local_archive_materialization_contract_review",
            "local_archive_creation_receipt",
            "local_archive_materialization_receipt",
            "local_handoff_error_diagnostic",
        ],
        "public_error_contract": {
            "base": "HandoffError",
            "contract_error": "HandoffContractError",
            "value_error_compatible": True,
            "diagnostic_posture": "local_handoff_error_diagnostic",
        },
    }
