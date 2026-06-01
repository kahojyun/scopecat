from __future__ import annotations

import unittest

import scopecat.measurement_context as measurement_context


class MeasurementContextPublicApiSurfaceTest(unittest.TestCase):
    def test_exports_resolved_context_link_surface(self) -> None:
        self.assertEqual(
            set(measurement_context.__all__),
            {
                "ResolvedContextLinkComparisonRequest",
                "ResolvedContextLinkComparisonResult",
                "build_resolved_context_link_comparison_summary",
                "compare_resolved_context_links",
            },
        )


if __name__ == "__main__":
    unittest.main()
