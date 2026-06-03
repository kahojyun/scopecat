from __future__ import annotations

import unittest
from pathlib import Path

from scopecat.handoff import (
    HandoffContractError,
    run_import_plan,
    run_receiving_gate,
    summarize_handoff_durable_import_receipt,
)


class HandoffErrorDiagnosticsTest(unittest.TestCase):
    def test_public_receiving_boundary_promotes_contract_error_with_diagnostic(self) -> None:
        with self.assertRaises(HandoffContractError) as context:
            run_receiving_gate(
                {
                    "receiving_gate_schema": "unsupported",
                    "receiving_gate_policy": {},
                    "receiving_review_request": {},
                },
                package_dir=Path("unused-package"),
            )

        self.assertIsInstance(context.exception, ValueError)
        diagnostic = context.exception.to_diagnostic().to_dict()
        self.assertEqual(diagnostic["artifact_posture"], "local_handoff_error_diagnostic")
        self.assertEqual(diagnostic["error"]["code"], "handoff_contract_error")
        self.assertEqual(diagnostic["error"]["operation"], "run_receiving_gate")
        self.assertEqual(
            diagnostic["error"]["message"],
            "receiving_gate_schema is unsupported",
        )
        self.assertEqual(diagnostic["summary_policy"]["portable_export"], "not_produced")
        self.assertIn("retry_authorization", diagnostic["does_not_claim"])

    def test_public_durable_summary_boundary_reports_operation(self) -> None:
        with self.assertRaises(HandoffContractError) as context:
            summarize_handoff_durable_import_receipt(
                {
                    "artifact_posture": "unsupported",
                    "handoff_durable_import_policy": {},
                    "workflow": {},
                    "request": {},
                    "import_plan": {},
                    "durable_import_request": None,
                    "durable_import_result": None,
                    "durable_import_review": {},
                }
            )

        diagnostic = context.exception.to_diagnostic().to_dict()
        self.assertEqual(
            diagnostic["error"]["operation"],
            "summarize_handoff_durable_import_receipt",
        )
        self.assertEqual(
            diagnostic["error"]["message"],
            "handoff durable import receipt posture is unsupported",
        )

    def test_nested_public_boundary_reports_outer_operation(self) -> None:
        with self.assertRaises(HandoffContractError) as context:
            run_import_plan(
                {
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
                        "external_authenticity_validation": "not_performed",
                        "conflict_detection": "not_performed",
                        "final_storage_schema": "not_defined",
                        "rollback": "not_defined",
                    },
                    "receiving_gate_source": {
                        "receiving_gate_schema": "unsupported",
                        "receiving_gate_policy": {},
                        "receiving_review_request": {},
                    },
                    "import_plan_request": {
                        "request_id": "plan-import-handoff-package-legacy-rabi-001",
                        "approval_state": "approved",
                        "requested_package_id": "handoff-package-legacy-rabi-001",
                        "measurement_scope": {"selection": "all_measurements"},
                    },
                },
                package_dir=Path("unused-package"),
            )

        diagnostic = context.exception.to_diagnostic().to_dict()
        self.assertEqual(diagnostic["error"]["operation"], "run_import_plan")
        self.assertEqual(diagnostic["error"]["message"], "receiving_gate_schema is unsupported")
        self.assertIsNot(context.exception.__cause__, context.exception)


if __name__ == "__main__":
    unittest.main()
