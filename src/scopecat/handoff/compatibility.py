"""Route-local compatibility contract for the current handoff slice."""

from __future__ import annotations

import copy
from typing import Any

from scopecat.handoff.durable_import import (
    DOES_NOT_CLAIM as _DURABLE_IMPORT_DOES_NOT_CLAIM,
)
from scopecat.handoff.durable_import import (
    HANDOFF_DURABLE_IMPORT_POLICY,
    HANDOFF_DURABLE_IMPORT_SCHEMA,
)
from scopecat.handoff.import_plan import (
    _EXPECTED_POLICY as _IMPORT_PLAN_POLICY,
)
from scopecat.handoff.import_plan import (
    _EXPECTED_SCHEMA as _IMPORT_PLAN_SCHEMA,
)
from scopecat.handoff.receiving import (
    _EXPECTED_POLICY as _RECEIVING_GATE_POLICY,
)
from scopecat.handoff.receiving import (
    _EXPECTED_SCHEMA as _RECEIVING_GATE_SCHEMA,
)
from scopecat.handoff.selected_record_export import SELECTED_RECORD_EXPORT_POLICY

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
        "schemas": {
            "receiving_gate": _RECEIVING_GATE_SCHEMA,
            "import_plan": _IMPORT_PLAN_SCHEMA,
            "handoff_durable_import": HANDOFF_DURABLE_IMPORT_SCHEMA,
        },
        "policies": {
            "selected_record_export": copy.deepcopy(SELECTED_RECORD_EXPORT_POLICY),
            "receiving_gate": copy.deepcopy(_RECEIVING_GATE_POLICY),
            "import_plan": copy.deepcopy(_IMPORT_PLAN_POLICY),
            "handoff_durable_import": copy.deepcopy(HANDOFF_DURABLE_IMPORT_POLICY),
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
            "local_receiving_review_state_projection",
            "local_handoff_error_diagnostic",
        ],
        "public_error_contract": {
            "base": "HandoffError",
            "contract_error": "HandoffContractError",
            "value_error_compatible": True,
            "diagnostic_posture": "local_handoff_error_diagnostic",
        },
        "does_not_claim": [
            "public_sdk",
            "final_package_format",
            "archive_creation_or_extraction",
            "signature_or_authenticity_validation",
            "trusted_source_policy",
            "batch_durable_import",
            "linked_context_payload_import",
            "persisted_gui_state",
            *_DURABLE_IMPORT_DOES_NOT_CLAIM,
        ],
    }
