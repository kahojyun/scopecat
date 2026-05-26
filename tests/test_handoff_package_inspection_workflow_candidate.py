from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from implementation_candidates.handoff_package_inspection_workflow import (
    build_handoff_package_inspection_summary,
)

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = (
    ROOT
    / "tests"
    / "fixtures"
    / "handoff_package_opener"
    / "basic_package"
    / "package"
    / "handoff-package-legacy-rabi-001"
)
ARTIFACT_NAME = "handoff-package-visual-review.html"


class HandoffPackageInspectionWorkflowCandidateTest(unittest.TestCase):
    def test_inspects_package_through_visual_artifact_for_local_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "inspection"
            summary = build_handoff_package_inspection_summary(
                PACKAGE,
                artifact_output_dir=output_dir,
            )
            artifact_path = Path(summary["local_visual_artifact"]["local_path"])
            html = artifact_path.read_text(encoding="utf-8")

        self.assertEqual(summary["artifact_posture"], "review_summary")
        self.assertEqual(
            summary["inspection_policy"]["manifest_preview"],
            "performed_via_read_only_opener_contract",
        )
        self.assertEqual(summary["inspection_policy"]["package_acceptance"], "not_performed")
        self.assertEqual(summary["inspection_policy"]["storage_import"], "not_performed")
        self.assertEqual(summary["inspection_policy"]["interactive_gui"], "not_defined")
        self.assertEqual(summary["package"]["package_id"], "handoff-package-legacy-rabi-001")
        self.assertEqual(summary["package"]["package_directory_name"], PACKAGE.name)
        self.assertEqual(
            summary["package"]["preview_classification"],
            "needs_review_before_acceptance",
        )
        self.assertEqual(summary["package"]["measurement_count"], 1)

        self.assertTrue(summary["manifest_preview"]["performed"])
        self.assertEqual(summary["manifest_preview"]["selected_measurement_count"], 1)
        self.assertEqual(summary["manifest_preview"]["linked_context_count"], 1)
        self.assertGreaterEqual(len(summary["manifest_preview"]["finding_codes"]), 1)

        self.assertTrue(summary["read_only_open"]["performed"])
        self.assertEqual(
            summary["read_only_open"]["classification"],
            "opened_read_only_for_declared_preview",
        )
        self.assertEqual(summary["read_only_open"]["measurement_ids"], ["legacy-rabi-001"])
        self.assertEqual(summary["read_view"]["measurement_ids"], ["legacy-rabi-001"])
        self.assertEqual(len(summary["read_view"]["linked_context_ids"]), 1)

        self.assertEqual(summary["visual_review"]["visual_summary_count"], 1)
        self.assertEqual(summary["visual_review"]["measurement_index_count"], 1)
        self.assertGreaterEqual(len(summary["visual_review"]["attention_codes"]), 1)

        self.assertTrue(summary["local_visual_artifact"]["performed"])
        self.assertEqual(summary["local_visual_artifact"]["filename"], ARTIFACT_NAME)
        self.assertEqual(summary["local_visual_artifact"]["created"], True)
        self.assertEqual(summary["local_visual_artifact"]["overwritten"], False)
        self.assertEqual(
            summary["local_visual_artifact"]["portable_package_member"],
            False,
        )
        self.assertIn("Visual Review", html)
        self.assertFalse(
            Path(summary["local_visual_artifact"]["local_path"]).is_relative_to(PACKAGE)
        )

    def test_rejects_visual_artifact_output_inside_package_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_like_root = Path(temp_dir) / "package-like-root"
            package_like_root.mkdir()
            (package_like_root / "package-manifest.json").write_text(
                "{}",
                encoding="utf-8",
            )
            output_dir = package_like_root / "local-review"

            with self.assertRaisesRegex(ValueError, "must not be in a package tree"):
                build_handoff_package_inspection_summary(
                    PACKAGE,
                    artifact_output_dir=output_dir,
                )

            self.assertFalse(output_dir.exists())

    def test_rejects_second_artifact_write_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "inspection"
            first = build_handoff_package_inspection_summary(
                PACKAGE,
                artifact_output_dir=output_dir,
            )
            artifact_path = Path(first["local_visual_artifact"]["local_path"])
            sentinel_html = "<!doctype html><title>sentinel</title>"
            artifact_path.write_text(sentinel_html, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "already exists"):
                build_handoff_package_inspection_summary(
                    PACKAGE,
                    artifact_output_dir=output_dir,
                )

            self.assertEqual(artifact_path.read_text(encoding="utf-8"), sentinel_html)

    def test_allows_explicit_visual_artifact_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "inspection"
            first = build_handoff_package_inspection_summary(
                PACKAGE,
                artifact_output_dir=output_dir,
            )
            second = build_handoff_package_inspection_summary(
                PACKAGE,
                artifact_output_dir=output_dir,
                overwrite_artifact=True,
            )
            artifact_path = Path(second["local_visual_artifact"]["local_path"])
            self.assertEqual(artifact_path, output_dir / ARTIFACT_NAME)
            self.assertEqual(artifact_path.name, ARTIFACT_NAME)
            self.assertTrue(artifact_path.is_file())

        self.assertEqual(first["local_visual_artifact"]["overwritten"], False)
        self.assertEqual(second["local_visual_artifact"]["overwritten"], True)

    def test_invalid_package_stops_before_visual_artifact_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_dir = temp_root / "not-a-package"
            package_dir.mkdir()
            output_dir = temp_root / "inspection"

            with self.assertRaisesRegex(ValueError, "manifest.*unavailable"):
                build_handoff_package_inspection_summary(
                    package_dir,
                    artifact_output_dir=output_dir,
                )

            self.assertFalse(output_dir.exists())


if __name__ == "__main__":
    unittest.main()
