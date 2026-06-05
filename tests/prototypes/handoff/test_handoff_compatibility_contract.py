from __future__ import annotations

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


def _receiving_gate_source() -> dict:
    return {
        "receiving_gate_schema": "scopecat.handoff_receiving_gate.v1",
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
        "import_plan_schema": "scopecat.handoff_import_plan.v1",
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
    def test_contract_names_current_route_local_schemas_and_policies(self) -> None:
        contract = current_handoff_compatibility_contract()

        self.assertEqual(
            contract["artifact_posture"],
            "local_handoff_compatibility_contract",
        )
        self.assertEqual(contract["contract_version"], HANDOFF_COMPATIBILITY_CONTRACT_VERSION)
        self.assertEqual(
            contract["schemas"],
            {
                "receiving_gate": "scopecat.handoff_receiving_gate.v1",
                "import_plan": "scopecat.handoff_import_plan.v1",
                "handoff_durable_import": "scopecat.handoff_durable_import.v1",
                "archive_materialization_review": (
                    "scopecat.handoff_archive_materialization_review.v1"
                ),
                "archive_materialization": "scopecat.handoff_archive_materialization.v1",
                "archive_creation": "scopecat.handoff_archive_creation.v1",
            },
        )
        self.assertNotIn("receiving_gate", contract["policies"])
        self.assertNotIn("import_plan", contract["policies"])
        self.assertNotIn("handoff_durable_import", contract["policies"])
        self.assertEqual(
            contract["policies"]["archive_materialization"]["archive_extraction"],
            "not_performed",
        )
        self.assertEqual(
            contract["policies"]["archive_package_materialization"]["archive_extraction"],
            "performed_into_staging_directory",
        )
        self.assertEqual(
            contract["policies"]["archive_package_creation"]["archive_creation"],
            "performed_from_dec010_directory_manifest_package",
        )
        self.assertIn(
            "local_handoff_error_diagnostic",
            contract["local_artifact_postures"],
        )
        self.assertIn(
            "local_receiving_review_state_projection",
            contract["local_artifact_postures"],
        )
        self.assertIn(
            "local_receiving_review_state_receipt",
            contract["local_artifact_postures"],
        )
        self.assertIn(
            "local_archive_materialization_contract_review",
            contract["local_artifact_postures"],
        )
        self.assertIn(
            "local_archive_creation_receipt",
            contract["local_artifact_postures"],
        )
        self.assertIn(
            "local_archive_materialization_receipt",
            contract["local_artifact_postures"],
        )
        self.assertIn(
            "local_jny001_operator_smoke_summary",
            contract["local_artifact_postures"],
        )
        self.assertIn("local_write_receipt", contract["local_artifact_postures"])
        self.assertIn("local_workflow_receipt", contract["local_artifact_postures"])
        self.assertIn("review_summary", contract["local_artifact_postures"])
        self.assertTrue(contract["public_error_contract"]["value_error_compatible"])

    def test_contract_returns_copy_safe_policy_snapshots(self) -> None:
        contract = current_handoff_compatibility_contract()
        contract["policies"]["archive_materialization"]["archive_extraction"] = "mutated"

        fresh_contract = current_handoff_compatibility_contract()

        self.assertEqual(
            fresh_contract["policies"]["archive_materialization"]["archive_extraction"],
            "not_performed",
        )

    def test_receiving_schema_drift_is_rejected_as_contract_error(self) -> None:
        source = _receiving_gate_source()
        source["receiving_gate_schema"] = "scopecat.handoff_receiving_gate.v0"

        with self.assertRaises(HandoffContractError) as context:
            run_receiving_gate(source, package_dir=Path("unused-package"))

        diagnostic = context.exception.to_diagnostic().to_dict()
        self.assertEqual(diagnostic["error"]["operation"], "run_receiving_gate")
        self.assertEqual(diagnostic["error"]["code"], "handoff_contract_error")
        self.assertEqual(diagnostic["error"]["message"], "receiving_gate_schema is unsupported")

    def test_import_plan_schema_drift_is_rejected_as_contract_error(self) -> None:
        source = _import_plan_source()
        source["import_plan_schema"] = "scopecat.handoff_import_plan.v0"

        with self.assertRaises(HandoffContractError) as context:
            run_import_plan(source, package_dir=Path("unused-package"))

        self.assertEqual(
            context.exception.to_diagnostic().to_dict()["error"],
            {
                "code": "handoff_contract_error",
                "operation": "run_import_plan",
                "message": "import_plan_schema is unsupported",
            },
        )

    def test_handoff_durable_receipt_posture_drift_is_rejected_as_contract_error(self) -> None:
        with self.assertRaises(HandoffContractError) as context:
            summarize_handoff_durable_import_receipt(
                {
                    "artifact_posture": "portable_handoff_import_receipt",
                    "classification": "unsupported",
                    "steps": [],
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
