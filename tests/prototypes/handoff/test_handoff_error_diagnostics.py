from __future__ import annotations

import unittest

from scopecat.handoff import (
    HandoffContractError,
    summarize_handoff_durable_import_receipt,
)


class HandoffErrorDiagnosticsTest(unittest.TestCase):
    def test_public_durable_summary_boundary_reports_operation(self) -> None:
        with self.assertRaises(HandoffContractError) as context:
            summarize_handoff_durable_import_receipt(
                {
                    "artifact_posture": "unsupported",
                    "classification": "unsupported",
                    "steps": [],
                    "request": {},
                    "import_plan": {},
                    "durable_import_request": None,
                    "durable_import_result": None,
                    "block_reason": None,
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
