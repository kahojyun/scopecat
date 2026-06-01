from __future__ import annotations

import unittest

import scopecat.selected_reference as selected_reference


class SelectedReferencePublicApiSurfaceTest(unittest.TestCase):
    def test_all_top_level_exports_resolve(self) -> None:
        for name in selected_reference.__all__:
            self.assertTrue(hasattr(selected_reference, name), name)

    def test_private_helpers_are_not_top_level_exports(self) -> None:
        private_names = {
            "_BASIC_SCOPE",
            "_CODE_SCOPE",
            "_records_by_key",
            "_validate_measurements",
            "_validate_source_for_mode",
        }

        self.assertFalse(private_names.intersection(selected_reference.__all__))
        for name in private_names:
            self.assertFalse(hasattr(selected_reference, name), name)

    def test_promoted_route_exports_comparison_surfaces(self) -> None:
        expected_names = {
            "SelectedReferenceCodeContextComparisonRequest",
            "SelectedReferenceComparisonRequest",
            "SelectedReferenceComparisonResult",
            "build_selected_reference_code_context_summary",
            "build_selected_reference_context_summary",
            "compare_selected_reference_code_context",
            "compare_selected_reference_context",
        }

        self.assertTrue(expected_names.issubset(selected_reference.__all__))


if __name__ == "__main__":
    unittest.main()
