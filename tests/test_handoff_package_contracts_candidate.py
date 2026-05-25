"""Tests for handoff-package route-local contract helpers."""

from __future__ import annotations

import copy
import unittest

from implementation_candidates.handoff_package_contracts import (
    MANIFEST_AUTHORITY,
    validate_handoff_package_identity,
    validate_handoff_preview_ready_metadata,
    validate_package_item_shape,
)


def _identity() -> dict[str, object]:
    return {
        "package_id": "handoff-package-001",
        "display_name": "Handoff package",
        "created_by": "scopecat_selected_measurement_export",
        "source_export_summary_id": "export-summary-001",
        "display_path": "HANDOFF_PACKAGE:/redacted/handoff-package-001",
        "local_path_redacted": True,
    }


def _package_item() -> dict[str, object]:
    return {
        "item_id": "measurement-001-primary",
        "kind": "primary_data",
        "label": "Primary data",
        "package_path": "measurements/measurement-001/primary.csv",
        "include_status": "included_by_default",
        "relation": "selected_measurement_source",
        "authority": MANIFEST_AUTHORITY,
        "package_state": "packaged",
        "reason": None,
    }


def _preview() -> dict[str, object]:
    return {
        "status": "preview_ready",
        "metadata_authority": MANIFEST_AUTHORITY,
        "data_shape": {"kind": "table", "axis_order": ["drive_frequency"]},
        "declared_columns": [
            {
                "name": "drive_frequency",
                "role": "x_axis",
                "label": "Drive frequency",
                "unit": "GHz",
            },
            {
                "name": "signal",
                "role": "y_axis",
                "label": "Signal",
                "unit": "arb",
            },
        ],
        "plot_candidates": [
            {
                "x": "drive_frequency",
                "y": "signal",
                "source": "measurements/measurement-001/primary.csv",
            }
        ],
    }


class HandoffPackageContractsCandidateTest(unittest.TestCase):
    def test_package_identity_display_path_modes_are_explicit(self) -> None:
        validate_handoff_package_identity(_identity(), display_path="required")

        optional_identity = _identity()
        del optional_identity["display_path"]
        validate_handoff_package_identity(optional_identity, display_path="optional")

        with self.assertRaisesRegex(ValueError, "display_path is required"):
            validate_handoff_package_identity(optional_identity, display_path="required")

        with self.assertRaisesRegex(ValueError, "display_path must not be exported"):
            validate_handoff_package_identity(_identity(), display_path="forbidden")

    def test_package_item_shape_ties_include_status_to_package_state(self) -> None:
        validate_package_item_shape(_package_item(), "package item")

        item = _package_item()
        item["include_status"] = "visible_excluded"
        with self.assertRaisesRegex(ValueError, "include_status must match package_state"):
            validate_package_item_shape(item, "package item")

    def test_package_item_shape_rejects_private_path_segments(self) -> None:
        item = _package_item()
        item["package_path"] = "measurements/measurement-001/Users/lab/private-note.json"

        with self.assertRaisesRegex(ValueError, "path segments"):
            validate_package_item_shape(item, "package item")

    def test_preview_ready_metadata_binds_axes_and_plots_to_declared_columns(self) -> None:
        validate_handoff_preview_ready_metadata(
            _preview(),
            primary_path="measurements/measurement-001/primary.csv",
            owner="preview",
        )

        preview = copy.deepcopy(_preview())
        preview["plot_candidates"][0]["y"] = "missing_signal"
        with self.assertRaisesRegex(ValueError, "axes must reference declared columns"):
            validate_handoff_preview_ready_metadata(
                preview,
                primary_path="measurements/measurement-001/primary.csv",
                owner="preview",
            )

    def test_preview_ready_metadata_rejects_non_string_column_names(self) -> None:
        preview = copy.deepcopy(_preview())
        preview["declared_columns"][0]["name"] = {"name": "drive_frequency"}

        with self.assertRaisesRegex(ValueError, "column name"):
            validate_handoff_preview_ready_metadata(
                preview,
                primary_path="measurements/measurement-001/primary.csv",
                owner="preview",
            )

    def test_preview_ready_metadata_rejects_non_object_data_shape(self) -> None:
        preview = copy.deepcopy(_preview())
        preview["data_shape"] = ["drive_frequency", "signal"]

        with self.assertRaisesRegex(ValueError, "data_shape must be an object"):
            validate_handoff_preview_ready_metadata(
                preview,
                primary_path="measurements/measurement-001/primary.csv",
                owner="preview",
            )

    def test_preview_ready_metadata_rejects_non_list_declared_columns(self) -> None:
        preview = copy.deepcopy(_preview())
        preview["declared_columns"] = {"drive_frequency": "x_axis"}

        with self.assertRaisesRegex(ValueError, "declared columns must be a list"):
            validate_handoff_preview_ready_metadata(
                preview,
                primary_path="measurements/measurement-001/primary.csv",
                owner="preview",
            )

    def test_preview_ready_metadata_rejects_non_object_declared_column(self) -> None:
        preview = copy.deepcopy(_preview())
        preview["declared_columns"][0] = "drive_frequency"

        with self.assertRaisesRegex(ValueError, "column must be an object"):
            validate_handoff_preview_ready_metadata(
                preview,
                primary_path="measurements/measurement-001/primary.csv",
                owner="preview",
            )

    def test_preview_ready_metadata_rejects_non_list_axis_order(self) -> None:
        preview = copy.deepcopy(_preview())
        preview["declared_columns"] = [
            {"name": "x", "role": "x_axis", "label": "X", "unit": "arb"},
            {"name": "y", "role": "y_axis", "label": "Y", "unit": "arb"},
        ]
        preview["data_shape"]["axis_order"] = "xy"
        preview["plot_candidates"] = [
            {
                "x": "x",
                "y": "y",
                "source": "measurements/measurement-001/primary.csv",
            }
        ]

        with self.assertRaisesRegex(ValueError, "axis order must be a list"):
            validate_handoff_preview_ready_metadata(
                preview,
                primary_path="measurements/measurement-001/primary.csv",
                owner="preview",
            )

    def test_preview_ready_metadata_rejects_non_list_plot_candidates(self) -> None:
        preview = copy.deepcopy(_preview())
        preview["plot_candidates"] = {"x": "drive_frequency", "y": "signal"}

        with self.assertRaisesRegex(ValueError, "plot candidates must be a list"):
            validate_handoff_preview_ready_metadata(
                preview,
                primary_path="measurements/measurement-001/primary.csv",
                owner="preview",
            )

    def test_preview_ready_metadata_rejects_non_object_plot_candidate(self) -> None:
        preview = copy.deepcopy(_preview())
        preview["plot_candidates"][0] = "drive_frequency_signal"

        with self.assertRaisesRegex(ValueError, "plot candidate must be an object"):
            validate_handoff_preview_ready_metadata(
                preview,
                primary_path="measurements/measurement-001/primary.csv",
                owner="preview",
            )


if __name__ == "__main__":
    unittest.main()
