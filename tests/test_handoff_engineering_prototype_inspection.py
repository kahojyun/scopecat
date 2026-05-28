from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scopecat.handoff import (
    HANDOFF_INSPECTION_ARTIFACT_NAME,
    build_inspection_html,
    open_package,
    write_inspection_artifact,
)

ROOT = Path(__file__).resolve().parents[1]
BASIC_PACKAGE = (
    ROOT
    / "tests"
    / "fixtures"
    / "handoff_package_opener"
    / "basic_package"
    / "package"
    / "handoff-package-legacy-rabi-001"
)
ROUTE_PRESSURE_ROOT = ROOT / "tests" / "fixtures" / "handoff_package_route_pressure"
RICHER_PACKAGE = (
    ROUTE_PRESSURE_ROOT
    / "richer_reader_package"
    / "package"
    / "handoff-package-reader-pressure-001"
)


class HandoffEngineeringPrototypeInspectionTest(unittest.TestCase):
    def test_inspection_html_renders_basic_package_plot_context_and_table(self) -> None:
        html = build_inspection_html(open_package(BASIC_PACKAGE))

        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn("Legacy Rabi selected measurement handoff", html)
        self.assertIn("Rabi calibration follow-up", html)
        self.assertIn("Drive frequency (GHz)", html)
        self.assertIn("Signal (a.u.)", html)
        self.assertIn("<svg", html)
        self.assertIn("render: rendered_fixture_svg", html)
        self.assertIn("linked_context_not_packaged_visible_reference", html)
        self.assertIn("reference_only", html)
        self.assertIn("<th>drive_frequency</th>", html)
        self.assertIn("<td>5.02</td>", html)
        self.assertNotIn("<script", html.lower())

    def test_inspection_html_renders_table_only_route_pressure_state(self) -> None:
        html = build_inspection_html(open_package(RICHER_PACKAGE))

        self.assertIn("Reader pressure Rabi run", html)
        self.assertIn("Reader pressure table-only check", html)
        self.assertIn("Residual (a.u.)", html)
        self.assertIn("plot 2", html)
        self.assertIn("No declared plot candidates. Table preview is shown instead.", html)
        self.assertIn("pressure-shared-setup-snapshot", html)

    def test_inspection_html_escapes_free_text_without_runtime_redaction(self) -> None:
        package = open_package(BASIC_PACKAGE)
        package._summary["package"]["display_name"] = 'Unsafe <Package> "Name"'
        package._summary["selected_measurements"][0]["label"] = "Rabi <calibration>"
        package._summary["linked_context"][0]["label"] = "Context <snapshot>"

        html = build_inspection_html(package)

        self.assertIn("Unsafe &lt;Package&gt; &quot;Name&quot;", html)
        self.assertIn("Rabi &lt;calibration&gt;", html)
        self.assertIn("Context &lt;snapshot&gt;", html)
        self.assertNotIn("Unsafe <Package>", html)
        self.assertNotIn("Rabi <calibration>", html)
        self.assertNotIn("Context <snapshot>", html)

    def test_write_inspection_artifact_returns_local_review_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            receipt = write_inspection_artifact(
                BASIC_PACKAGE,
                output_dir=Path(temp_dir),
            )
            artifact_path = Path(receipt["html_artifact"]["local_path"])
            html = artifact_path.read_text(encoding="utf-8")

        self.assertEqual(receipt["artifact_posture"], "review_summary")
        self.assertEqual(receipt["html_artifact"]["filename"], HANDOFF_INSPECTION_ARTIFACT_NAME)
        self.assertEqual(receipt["html_artifact"]["portable_package_member"], False)
        self.assertEqual(receipt["html_artifact"]["overwritten"], False)
        self.assertEqual(receipt["package_id"], "handoff-package-legacy-rabi-001")
        self.assertIn("Rabi calibration follow-up", html)

    def test_write_rejects_package_tree_output_dir(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be in a package tree"):
            write_inspection_artifact(BASIC_PACKAGE, output_dir=BASIC_PACKAGE)

    def test_write_rejects_existing_artifact_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            write_inspection_artifact(BASIC_PACKAGE, output_dir=output_dir)

            with self.assertRaisesRegex(ValueError, "already exists"):
                write_inspection_artifact(RICHER_PACKAGE, output_dir=output_dir)

    def test_write_allows_explicit_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            first = write_inspection_artifact(BASIC_PACKAGE, output_dir=output_dir)
            second = write_inspection_artifact(
                RICHER_PACKAGE,
                output_dir=output_dir,
                overwrite=True,
            )

        self.assertEqual(first["html_artifact"]["overwritten"], False)
        self.assertEqual(second["html_artifact"]["overwritten"], True)
        self.assertEqual(second["package_id"], "handoff-package-reader-pressure-001")


if __name__ == "__main__":
    unittest.main()
