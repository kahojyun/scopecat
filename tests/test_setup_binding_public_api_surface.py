from __future__ import annotations

import unittest

import scopecat.setup_binding as setup_binding


class SetupBindingPublicApiSurfaceTest(unittest.TestCase):
    def test_exports_route_local_surface(self) -> None:
        self.assertEqual(
            set(setup_binding.__all__),
            {
                "SetupBindingSummaryRequest",
                "SetupBindingSummaryResult",
                "build_setup_binding_summary",
                "summarize_setup_binding_context",
            },
        )


if __name__ == "__main__":
    unittest.main()
