"""Tests for handoff-package route-local contract helpers."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.handoff_package_contracts import (
    MANIFEST_AUTHORITY,
    validate_handoff_package_identity,
    validate_handoff_preview_ready_metadata,
    validate_handoff_receiving_roots,
    validate_handoff_reviewed_package_continuity,
    validate_package_item_shape,
)

ARTIFACT_NAME = "handoff-package-visual-review.html"


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


def _inspected_package() -> dict[str, object]:
    return {
        "package_id": "handoff-package-001",
        "preview_classification": "needs_review_before_acceptance",
    }


def _integrity_package() -> dict[str, object]:
    return {
        "package_id": "handoff-package-001",
        "preview_classification": "needs_review_before_acceptance",
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

    def test_receiving_roots_require_artifact_outside_package_and_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = temp_root / "handoff-package-001"
            storage_root = temp_root / "storage"
            artifact_output_dir = temp_root / "local-review"
            package_dir.mkdir()
            storage_root.mkdir()

            validate_handoff_receiving_roots(
                package_dir=package_dir,
                storage_root=storage_root,
                artifact_output_dir=artifact_output_dir,
                artifact_output_filenames=(ARTIFACT_NAME,),
            )

            with self.assertRaisesRegex(ValueError, "outside the package tree"):
                validate_handoff_receiving_roots(
                    package_dir=package_dir,
                    storage_root=storage_root,
                    artifact_output_dir=package_dir / "review",
                    artifact_output_filenames=(ARTIFACT_NAME,),
                )

            with self.assertRaisesRegex(ValueError, "outside the package tree"):
                validate_handoff_receiving_roots(
                    package_dir=package_dir,
                    storage_root=storage_root,
                    artifact_output_dir=package_dir,
                    artifact_output_filenames=(ARTIFACT_NAME,),
                )

            with self.assertRaisesRegex(ValueError, "outside the storage root"):
                validate_handoff_receiving_roots(
                    package_dir=package_dir,
                    storage_root=storage_root,
                    artifact_output_dir=storage_root / "review",
                    artifact_output_filenames=(ARTIFACT_NAME,),
                )

            with self.assertRaisesRegex(ValueError, "outside the storage root"):
                validate_handoff_receiving_roots(
                    package_dir=package_dir,
                    storage_root=storage_root,
                    artifact_output_dir=storage_root,
                    artifact_output_filenames=(ARTIFACT_NAME,),
                )

    def test_receiving_roots_require_package_and_storage_separation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = temp_root / "package"
            storage_root = package_dir / "storage"
            artifact_output_dir = temp_root / "local-review"
            storage_root.mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "must be separate"):
                validate_handoff_receiving_roots(
                    package_dir=package_dir,
                    storage_root=storage_root,
                    artifact_output_dir=artifact_output_dir,
                )

            with self.assertRaisesRegex(ValueError, "must be separate"):
                validate_handoff_receiving_roots(
                    package_dir=storage_root,
                    storage_root=storage_root,
                    artifact_output_dir=artifact_output_dir,
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            storage_root = temp_root / "storage"
            package_dir = storage_root / "package"
            artifact_output_dir = temp_root / "local-review"
            package_dir.mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "must be separate"):
                validate_handoff_receiving_roots(
                    package_dir=package_dir,
                    storage_root=storage_root,
                    artifact_output_dir=artifact_output_dir,
                )

    def test_receiving_roots_reject_existing_artifact_target_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = temp_root / "package"
            storage_root = temp_root / "storage"
            artifact_output_dir = temp_root / "local-review"
            package_dir.mkdir()
            storage_root.mkdir()
            artifact_output_dir.mkdir()
            (artifact_output_dir / ARTIFACT_NAME).symlink_to(
                storage_root / "records" / "legacy-rabi-001.html",
            )

            with self.assertRaisesRegex(ValueError, "must not be a symlink"):
                validate_handoff_receiving_roots(
                    package_dir=package_dir,
                    storage_root=storage_root,
                    artifact_output_dir=artifact_output_dir,
                    artifact_output_filenames=(ARTIFACT_NAME,),
                )

            with self.assertRaisesRegex(ValueError, "must not be a symlink"):
                validate_handoff_receiving_roots(
                    package_dir=package_dir,
                    storage_root=storage_root,
                    artifact_output_dir=artifact_output_dir,
                    artifact_output_filenames=(ARTIFACT_NAME,),
                    allow_existing_artifact_targets=True,
                )

    def test_reviewed_package_continuity_accepts_matching_facts(self) -> None:
        validate_handoff_reviewed_package_continuity(
            reviewed_package_id="handoff-package-001",
            reviewed_preview_classification="needs_review_before_acceptance",
            reviewed_integrity_classification="declared_integrity_verified",
            inspected_package=_inspected_package(),
            integrity_package=_integrity_package(),
            integrity_classification="declared_integrity_verified",
        )

    def test_reviewed_package_continuity_checks_integrity_preview(self) -> None:
        integrity_package = _integrity_package()
        integrity_package["preview_classification"] = "preview_ready_for_opening"

        with self.assertRaisesRegex(ValueError, "preview classification"):
            validate_handoff_reviewed_package_continuity(
                reviewed_package_id="handoff-package-001",
                reviewed_preview_classification="needs_review_before_acceptance",
                reviewed_integrity_classification="declared_integrity_verified",
                inspected_package=_inspected_package(),
                integrity_package=integrity_package,
                integrity_classification="declared_integrity_verified",
            )

    def test_reviewed_package_continuity_checks_integrity_package_id(self) -> None:
        integrity_package = _integrity_package()
        integrity_package["package_id"] = "different-package"

        with self.assertRaisesRegex(ValueError, "integrity-observed package"):
            validate_handoff_reviewed_package_continuity(
                reviewed_package_id="handoff-package-001",
                reviewed_preview_classification="needs_review_before_acceptance",
                reviewed_integrity_classification="declared_integrity_verified",
                inspected_package=_inspected_package(),
                integrity_package=integrity_package,
                integrity_classification="declared_integrity_verified",
            )

    def test_reviewed_package_continuity_checks_integrity_classification(self) -> None:
        with self.assertRaisesRegex(ValueError, "integrity classification"):
            validate_handoff_reviewed_package_continuity(
                reviewed_package_id="handoff-package-001",
                reviewed_preview_classification="needs_review_before_acceptance",
                reviewed_integrity_classification="integrity_review_required",
                inspected_package=_inspected_package(),
                integrity_package=_integrity_package(),
                integrity_classification="declared_integrity_verified",
            )


if __name__ == "__main__":
    unittest.main()
