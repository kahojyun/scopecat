from __future__ import annotations

import json
import unittest
from pathlib import Path

from implementation_candidates.handoff_package_contents_preview import (
    build_handoff_package_contents_preview_summary,
)
from implementation_candidates.handoff_package_gui_view_state import (
    build_handoff_package_gui_view_state,
)
from implementation_candidates.handoff_package_opener import open_handoff_package
from implementation_candidates.handoff_package_preview_consumption import (
    build_handoff_package_preview_consumption_summary,
)
from implementation_candidates.handoff_package_read_view import open_handoff_package_view
from implementation_candidates.handoff_package_visual_review import (
    build_handoff_package_visual_review_model,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "handoff_package_route_pressure"
RICHER_PACKAGE = (
    FIXTURE_ROOT / "richer_reader_package" / "package" / "handoff-package-reader-pressure-001"
)
DEGRADED_PACKAGE = (
    FIXTURE_ROOT / "degraded_preview_package" / "package" / "handoff-package-degraded-preview-001"
)


def _load_manifest(package_dir: Path) -> dict:
    return json.loads((package_dir / "package-manifest.json").read_text(encoding="utf-8"))


class HandoffPackageRoutePressureFixtureTest(unittest.TestCase):
    def test_richer_package_opens_multi_plot_and_table_only_measurements(self) -> None:
        summary = open_handoff_package(RICHER_PACKAGE)

        self.assertEqual(summary["package"]["package_id"], "handoff-package-reader-pressure-001")
        self.assertEqual(
            summary["package"]["preview_classification"],
            "needs_review_before_acceptance",
        )
        self.assertEqual(
            [item["measurement_record_id"] for item in summary["selected_measurements"]],
            ["pressure-rabi-001", "pressure-check-001"],
        )
        rabi, check = summary["selected_measurements"]
        self.assertNotIn("declared_digest", rabi["primary_data"])
        self.assertNotIn("declared_size_bytes", rabi["primary_data"])
        self.assertEqual(len(rabi["preview_data"]["plot_series"]), 2)
        self.assertEqual(
            rabi["preview_data"]["plot_series"][1]["points"][2],
            {"x": "5.02", "y": "0.01"},
        )
        self.assertEqual(check["preview_data"]["plot_series"], [])
        self.assertEqual(check["preview_data"]["row_count"], 4)
        self.assertEqual(summary["linked_context"][0]["materialization"], "reference_only")

    def test_read_view_exposes_richer_fixture_through_reader_objects(self) -> None:
        view = open_handoff_package_view(RICHER_PACKAGE)
        rabi = view.measurement("pressure-rabi-001")
        check = view.measurement("pressure-check-001")

        self.assertEqual(view.measurement_ids, ("pressure-rabi-001", "pressure-check-001"))
        self.assertEqual(rabi.primary_table().columns, ("drive_frequency", "signal", "residual"))
        self.assertEqual(rabi.preview_table().row_count, 5)
        self.assertEqual(len(rabi.plot_series()), 2)
        self.assertEqual(
            rabi.plot_series_by_columns(x="drive_frequency", y="residual").y[2],
            "0.01",
        )
        self.assertEqual(check.primary_table().columns, ("delay", "contrast"))
        self.assertEqual(check.plot_series(), ())
        self.assertEqual(check.linked_context[0]["link_id"], "pressure-shared-setup-snapshot")

    def test_richer_package_pressures_visual_consumption_and_gui_surfaces(self) -> None:
        visual = build_handoff_package_visual_review_model(RICHER_PACKAGE)
        consumption = build_handoff_package_preview_consumption_summary(RICHER_PACKAGE)
        gui = build_handoff_package_gui_view_state(RICHER_PACKAGE)

        self.assertEqual(visual["package"]["visual_summary_count"], 2)
        self.assertEqual(
            [item["visual_summary_id"] for item in visual["visual_summaries"]],
            ["pressure-rabi-001-visual-1", "pressure-rabi-001-visual-2"],
        )
        visual_index = {item["measurement_record_id"]: item for item in visual["measurement_index"]}
        self.assertEqual(
            visual_index["pressure-rabi-001"]["visual_summary_ids"],
            ["pressure-rabi-001-visual-1", "pressure-rabi-001-visual-2"],
        )
        self.assertEqual(visual_index["pressure-check-001"]["visual_summary_ids"], [])
        self.assertIn(
            "no_declared_plot_candidates",
            [item["code"] for item in visual_index["pressure-check-001"]["attention_items"]],
        )

        self.assertEqual(
            consumption["package"]["first_surface_counts"],
            {
                "plot_first_visual_review": 1,
                "review_findings": 0,
                "table_drilldown": 1,
            },
        )
        self.assertEqual(consumption["visual_review"]["visual_summary_count"], 2)
        self.assertEqual(
            [item["first_surface"]["surface"] for item in consumption["measurements"]],
            ["plot_first_visual_review", "table_drilldown"],
        )

        self.assertEqual(
            gui["package"]["primary_surface_counts"],
            {"plot": 1, "review_findings": 0, "table_drilldown": 1},
        )
        self.assertEqual(gui["selected_measurement"]["measurement_record_id"], "pressure-rabi-001")
        self.assertEqual(gui["selected_measurement"]["plot_panel"]["point_count"], 5)
        self.assertEqual(
            [item["primary_surface"] for item in gui["navigation"]["measurement_list"]],
            ["plot", "table_drilldown"],
        )

    def test_degraded_preview_fixture_is_manifest_previewable_but_not_openable(self) -> None:
        manifest = _load_manifest(DEGRADED_PACKAGE)
        primary_path = manifest["selected_measurements"][0]["primary_data"]["package_path"]
        self.assertTrue((DEGRADED_PACKAGE / primary_path).is_file())

        summary = build_handoff_package_contents_preview_summary(manifest)

        self.assertEqual(summary["package"]["classification"], "needs_review_before_acceptance")
        self.assertEqual(
            summary["selected_measurements"][0]["classification"],
            "needs_preview_metadata_review",
        )
        self.assertEqual(summary["preview_findings"][0]["finding"], "preview_metadata_missing")

        with self.assertRaisesRegex(ValueError, "requires preview_ready metadata"):
            open_handoff_package(DEGRADED_PACKAGE)


if __name__ == "__main__":
    unittest.main()
