from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scopecat.handoff import HANDOFF_INSPECTION_ARTIFACT_NAME, run_package_workflow

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "handoff_engineering_prototype_writer" / "basic_package"
SOURCE_ROOT = FIXTURE / "source"


def _load_input() -> dict:
    return json.loads((FIXTURE / "package-writer-input.json").read_text(encoding="utf-8"))


class HandoffEngineeringPrototypeWorkflowTest(unittest.TestCase):
    def test_workflow_writes_opens_and_summarizes_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir) / "packages"
            package_root.mkdir()

            run = run_package_workflow(
                _load_input(),
                source_root=SOURCE_ROOT,
                package_root=package_root,
            )
            summary = run.to_dict()

        self.assertEqual(run.package_id, "handoff-package-legacy-rabi-001")
        self.assertEqual(run.measurement_ids, ("legacy-rabi-001",))
        self.assertEqual(run.package.measurement("legacy-rabi-001").primary_table.row_count, 5)
        self.assertEqual(summary["artifact_posture"], "local_workflow_receipt")
        self.assertEqual(
            summary["workflow"]["steps"],
            ["write_package", "open_package"],
        )
        self.assertEqual(
            summary["package"]["preview_classification"],
            "needs_review_before_acceptance",
        )
        self.assertIn(
            "package_import_or_acceptance",
            summary["workflow"]["does_not_claim"],
        )
        self.assertIsNone(summary["inspection_receipt"])

    def test_workflow_can_write_local_inspection_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            package_root = temp_root / "packages"
            inspection_root = temp_root / "inspection"
            package_root.mkdir()

            run = run_package_workflow(
                _load_input(),
                source_root=SOURCE_ROOT,
                package_root=package_root,
                inspection_output_dir=inspection_root,
            )
            summary = run.to_dict()
            html_path = inspection_root / HANDOFF_INSPECTION_ARTIFACT_NAME
            html_exists = html_path.is_file()
            html = html_path.read_text(encoding="utf-8")

        self.assertTrue(html_exists)
        self.assertIn("Rabi calibration follow-up", html)
        self.assertEqual(
            summary["workflow"]["steps"],
            ["write_package", "open_package", "write_inspection_artifact"],
        )
        self.assertEqual(
            summary["inspection_receipt"]["html_artifact"]["portable_package_member"],
            False,
        )

    def test_workflow_rejects_inspection_artifact_inside_package_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir) / "packages"
            package_root.mkdir()
            package_dir = package_root / "handoff-package-legacy-rabi-001"

            with self.assertRaisesRegex(ValueError, "must not be in a package tree"):
                run_package_workflow(
                    _load_input(),
                    source_root=SOURCE_ROOT,
                    package_root=package_root,
                    inspection_output_dir=package_dir,
                )

            self.assertTrue(package_dir.exists())
            self.assertFalse((package_dir / HANDOFF_INSPECTION_ARTIFACT_NAME).exists())


if __name__ == "__main__":
    unittest.main()
