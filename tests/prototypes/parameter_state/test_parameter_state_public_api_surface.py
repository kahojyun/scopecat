from __future__ import annotations

import unittest

import scopecat.parameter_state as parameter_state


class ParameterStatePublicApiSurfaceTest(unittest.TestCase):
    def test_all_top_level_exports_resolve(self) -> None:
        for name in parameter_state.__all__:
            self.assertTrue(hasattr(parameter_state, name), name)

    def test_private_helpers_are_not_top_level_exports(self) -> None:
        private_names = {
            "_contracts",
            "_storage",
            "validate_relative_path",
            "relative_path_parts",
            "path_under",
            "write_new_files_transaction",
        }

        self.assertFalse(private_names.intersection(parameter_state.__all__))
        for name in private_names - {"_contracts", "_storage"}:
            self.assertFalse(hasattr(parameter_state, name), name)

    def test_promoted_route_exports_core_review_chain(self) -> None:
        expected_names = {
            "build_adapter_parameter_import_review_commit_summary",
            "read_parameter_state_storage_view",
            "write_parameter_state_storage",
        }

        self.assertTrue(expected_names.issubset(parameter_state.__all__))


if __name__ == "__main__":
    unittest.main()
