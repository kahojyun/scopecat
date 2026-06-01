from __future__ import annotations

import unittest

import scopecat.measurement_context as measurement_context


class MeasurementContextPublicApiSurfaceTest(unittest.TestCase):
    def test_exports_measurement_context_surfaces(self) -> None:
        self.assertEqual(
            set(measurement_context.__all__),
            {
                "MeasurementContextLinkRequest",
                "MeasurementContextLinkResult",
                "ResolvedContextLinkComparisonRequest",
                "ResolvedContextLinkComparisonResult",
                "SupportingEvidenceReferenceRequest",
                "SupportingEvidenceReferenceResult",
                "build_measurement_context_link_summary",
                "build_resolved_context_link_comparison_summary",
                "build_supporting_evidence_reference_summary",
                "compare_resolved_context_links",
                "summarize_measurement_context_links",
                "summarize_supporting_evidence_reference",
            },
        )


if __name__ == "__main__":
    unittest.main()
