from __future__ import annotations

import unittest
from pathlib import Path

from scopecat.handoff import (
    HandoffContractError,
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


if __name__ == "__main__":
    unittest.main()
