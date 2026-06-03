from __future__ import annotations

import copy
import unittest
from pathlib import Path

from scopecat.handoff import (
    HANDOFF_COMPATIBILITY_CONTRACT_VERSION,
    HandoffContractError,
    current_handoff_compatibility_contract,
    run_import_plan,
    run_receiving_gate,
    summarize_handoff_durable_import_receipt,
)
from scopecat.handoff.durable_import import HANDOFF_DURABLE_IMPORT_POLICY


def _receiving_gate_source() -> dict:
    return {
        "receiving_gate_schema": "scopecat.handoff_receiving_gate.v0",
        "receiving_gate_policy": {
            "workflow_authority": "approved_receiving_review_request",
            "package_open": "read_only_declared_preview",
            "integrity_observation": "read_only_package_local_member_observation",
            "acceptance_gate": "require_approved_review_and_declared_integrity_verified",
            "storage_mutation": "not_performed",
            "import_acceptance": "not_performed",
            "archive_handling": "not_performed",
            "signature_validation": "not_performed",
            "package_root_concurrency": "not_supported",
            "schema_inference": "not_performed",
            "dataframe_adapter": "not_defined",
            "interactive_gui": "not_defined",
            "shared_measurement_schema": "not_defined",
        },
        "receiving_review_request": {
            "request_id": "receive-handoff-package-legacy-rabi-001",
            "review": {
                "approval_state": "approved",
                "reviewed_package_id": "handoff-package-legacy-rabi-001",
                "reviewed_preview_classification": "needs_review_before_acceptance",
                "reviewed_integrity_classification": "declared_integrity_verified",
            },
        },
    }


def _import_plan_source() -> dict:
    return {
        "import_plan_schema": "scopecat.handoff_import_plan.v0",
        "import_plan_policy": {
            "workflow_authority": "approved_import_planning_request",
            "package_open": "read_only_declared_preview",
            "inspection_artifact": "optional_local_static_review_artifact",
            "receiving_gate": "required_before_import_plan",
            "import_plan": "non_mutating_measurement_acceptance_plan",
            "storage_mutation": "not_performed",
            "import_acceptance": "not_performed",
            "archive_handling": "not_performed",
            "signature_validation": "not_performed",
            "conflict_detection": "not_performed",
            "final_storage_schema": "not_defined",
            "rollback": "not_defined",
        },
        "receiving_gate_source": _receiving_gate_source(),
        "import_plan_request": {
            "request_id": "plan-import-handoff-package-legacy-rabi-001",
            "approval_state": "approved",
            "requested_package_id": "handoff-package-legacy-rabi-001",
            "measurement_scope": {
                "selection": "all_measurements",
            },
        },
    }


class HandoffCompatibilityContractTest(unittest.TestCase):
    def test_contract_names_current_route_local_schemas_policies_and_non_claims(self) -> None:
        contract = current_handoff_compatibility_contract()

        self.assertEqual(
            contract["artifact_posture"],
            "local_handoff_compatibility_contract",
        )
        self.assertEqual(contract["contract_version"], HANDOFF_COMPATIBILITY_CONTRACT_VERSION)
        self.assertEqual(
            contract["schemas"],
            {
                "receiving_gate": "scopecat.handoff_receiving_gate.v0",
                "import_plan": "scopecat.handoff_import_plan.v0",
                "handoff_durable_import": "scopecat.handoff_durable_import.v0",
            },
        )
        self.assertEqual(
            contract["policies"]["receiving_gate"]["archive_handling"],
            "not_performed",
        )
        self.assertEqual(
            contract["policies"]["import_plan"]["storage_mutation"],
            "not_performed",
        )
        self.assertEqual(
            contract["policies"]["handoff_durable_import"],
            HANDOFF_DURABLE_IMPORT_POLICY,
        )
        self.assertIn(
            "local_handoff_error_diagnostic",
            contract["local_artifact_postures"],
        )
        self.assertIn("local_write_receipt", contract["local_artifact_postures"])
        self.assertIn("local_workflow_receipt", contract["local_artifact_postures"])
        self.assertIn("review_summary", contract["local_artifact_postures"])
        self.assertTrue(contract["public_error_contract"]["value_error_compatible"])
        self.assertIn("public_sdk", contract["does_not_claim"])
        self.assertIn("final_package_format", contract["does_not_claim"])
        self.assertIn("durable_schema_publication", contract["does_not_claim"])
        self.assertIn("existing_record_update", contract["does_not_claim"])
        self.assertIn("candidate_storage_acceptance_route", contract["does_not_claim"])

    def test_contract_returns_copy_safe_policy_snapshots(self) -> None:
        contract = current_handoff_compatibility_contract()
        contract["policies"]["handoff_durable_import"]["batch_import"] = "mutated"

        fresh_contract = current_handoff_compatibility_contract()

        self.assertEqual(
            fresh_contract["policies"]["handoff_durable_import"]["batch_import"],
            "not_performed",
        )

    def test_receiving_schema_drift_is_rejected_as_contract_error(self) -> None:
        source = _receiving_gate_source()
        source["receiving_gate_schema"] = "scopecat.handoff_receiving_gate.v1"

        with self.assertRaises(HandoffContractError) as context:
            run_receiving_gate(source, package_dir=Path("unused-package"))

        diagnostic = context.exception.to_diagnostic().to_dict()
        self.assertEqual(diagnostic["error"]["operation"], "run_receiving_gate")
        self.assertEqual(diagnostic["error"]["code"], "handoff_contract_error")
        self.assertEqual(diagnostic["error"]["message"], "receiving_gate_schema is unsupported")

    def test_import_plan_policy_drift_is_rejected_as_contract_error(self) -> None:
        source = _import_plan_source()
        source["import_plan_policy"] = copy.deepcopy(source["import_plan_policy"])
        source["import_plan_policy"]["archive_handling"] = "extract_zip"

        with self.assertRaises(HandoffContractError) as context:
            run_import_plan(source, package_dir=Path("unused-package"))

        self.assertEqual(
            context.exception.to_diagnostic().to_dict()["error"],
            {
                "code": "handoff_contract_error",
                "operation": "run_import_plan",
                "message": "import_plan_policy is unsupported",
            },
        )

    def test_handoff_durable_receipt_posture_drift_is_rejected_as_contract_error(self) -> None:
        with self.assertRaises(HandoffContractError) as context:
            summarize_handoff_durable_import_receipt(
                {
                    "artifact_posture": "portable_handoff_import_receipt",
                    "handoff_durable_import_policy": HANDOFF_DURABLE_IMPORT_POLICY,
                    "workflow": {},
                    "request": {},
                    "import_plan": {},
                    "durable_import_request": None,
                    "durable_import_result": None,
                    "durable_import_review": {},
                }
            )

        self.assertEqual(
            context.exception.to_diagnostic().to_dict()["error"]["message"],
            "handoff durable import receipt posture is unsupported",
        )


if __name__ == "__main__":
    unittest.main()
