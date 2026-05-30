from __future__ import annotations

import unittest

import scopecat.handoff as handoff


class HandoffPublicApiSurfaceTest(unittest.TestCase):
    def test_candidate_storage_helpers_are_not_top_level_exports(self) -> None:
        legacy_names = {
            "HandoffAcceptancePreflightRequest",
            "HandoffStorageAcceptanceRequest",
            "approve_import",
            "run_acceptance_preflight",
            "run_import_workflow",
            "run_storage_acceptance",
            "summarize_import_workflow_receipt",
        }

        self.assertFalse(legacy_names.intersection(handoff.__all__))
        for name in legacy_names:
            self.assertFalse(hasattr(handoff, name), name)

    def test_durable_handoff_import_remains_top_level_export(self) -> None:
        self.assertIn("run_handoff_durable_import", handoff.__all__)
        self.assertTrue(hasattr(handoff, "run_handoff_durable_import"))
        self.assertIn("summarize_handoff_durable_import_receipt", handoff.__all__)


if __name__ == "__main__":
    unittest.main()
