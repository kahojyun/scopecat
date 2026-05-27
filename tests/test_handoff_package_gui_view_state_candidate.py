from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from implementation_candidates.handoff_package_gui_view_state import (
    build_handoff_package_gui_view_state,
)
from implementation_candidates.handoff_package_gui_view_state import summary as gui_summary

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


def _copy_package(temp_root: Path) -> Path:
    package_dir = temp_root / PACKAGE.name
    shutil.copytree(PACKAGE, package_dir)
    return package_dir


def _manifest(package_dir: Path) -> dict:
    return json.loads((package_dir / "package-manifest.json").read_text(encoding="utf-8"))


def _write_manifest(package_dir: Path, manifest: dict) -> None:
    (package_dir / "package-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _add_second_measurement_without_plot(package_dir: Path) -> None:
    manifest = _manifest(package_dir)
    source = manifest["selected_measurements"][0]
    measurement = copy.deepcopy(source)
    measurement["measurement_record_id"] = "legacy-rabi-002"
    measurement["legacy_data_id"] = 1002
    measurement["label"] = "Rabi calibration follow-up without plot"
    measurement["primary_data"]["package_path"] = "measurements/legacy-rabi-002/primary.csv"
    measurement["declared_preview_metadata"]["plot_candidates"] = []
    measurement["default_bundle"][0]["item_id"] = "legacy-rabi-002-primary"
    measurement["default_bundle"][0]["package_path"] = "measurements/legacy-rabi-002/primary.csv"
    manifest["selected_measurements"].append(measurement)
    manifest["linked_context"][0]["linked_measurement_record_ids"].append("legacy-rabi-002")
    target_dir = package_dir / "measurements" / "legacy-rabi-002"
    target_dir.mkdir()
    shutil.copyfile(
        package_dir / "measurements" / "legacy-rabi-001" / "primary.csv",
        target_dir / "primary.csv",
    )
    _write_manifest(package_dir, manifest)


def _assert_no_path_leak(test_case: unittest.TestCase, summary: dict, path: Path) -> None:
    serialized = json.dumps(summary, sort_keys=True)
    test_case.assertNotIn(str(path), serialized)
    test_case.assertNotIn(str(path.resolve()), serialized)


def _assert_summary_shape(test_case: unittest.TestCase, summary: dict) -> None:
    test_case.assertEqual(
        set(summary),
        {
            "artifact_posture",
            "attention",
            "consumed_projections",
            "gui_view_state_policy",
            "measurement_states",
            "navigation",
            "package",
            "selected_measurement",
        },
    )
    test_case.assertEqual(
        set(summary["package"]),
        {
            "display_name",
            "measurement_count",
            "package_id",
            "preview_classification",
            "primary_surface_counts",
            "selected_measurement_id",
        },
    )
    for measurement in summary["measurement_states"]:
        test_case.assertEqual(
            set(measurement),
            {
                "available_actions",
                "context_panel",
                "findings_panel",
                "label",
                "measurement_record_id",
                "plot_panel",
                "primary_surface",
                "table_panel",
            },
        )


class HandoffPackageGuiViewStateCandidateTest(unittest.TestCase):
    def test_builds_plot_first_gui_view_state(self) -> None:
        summary = build_handoff_package_gui_view_state(PACKAGE)
        selected = summary["selected_measurement"]
        expected_policy = {
            "archive_handling": "not_performed",
            "dataframe_adapter": "not_invoked",
            "default_selection": "first_measurement_in_package_order",
            "gui_components": "not_defined",
            "interactive_events": "not_performed",
            "measurement_navigation": "projected_as_local_state",
            "package_acceptance": "not_performed",
            "package_integrity": "not_claimed",
            "package_open": "performed_via_handoff_package_read_view",
            "plot_rendering": "not_performed",
            "preview_consumption_projection": "consumed",
            "primary_surface_selection": "derived_from_preview_consumption_first_surface",
            "scan_shape_inference": "not_performed",
            "schema_inference": "not_performed",
            "sdk_adapter": "not_invoked",
            "shared_measurement_schema": "not_defined",
            "storage_import": "not_performed",
            "view_state_authority": "local_handoff_package_reader_projections",
            "visual_review_projection": "consumed",
        }

        self.assertEqual(summary["artifact_posture"], "review_summary")
        self.assertEqual(summary, build_handoff_package_gui_view_state(PACKAGE))
        _assert_summary_shape(self, summary)
        self.assertEqual(summary["gui_view_state_policy"], expected_policy)
        self.assertEqual(summary["package"]["package_id"], "handoff-package-legacy-rabi-001")
        self.assertEqual(summary["package"]["selected_measurement_id"], "legacy-rabi-001")
        self.assertEqual(
            summary["package"]["primary_surface_counts"],
            {"plot": 1, "review_findings": 0, "table_drilldown": 0},
        )
        self.assertEqual(
            summary["navigation"]["default_selection"],
            {
                "basis": "first_measurement_in_package_order",
                "measurement_record_id": "legacy-rabi-001",
            },
        )
        self.assertEqual(len(summary["navigation"]["measurement_list"]), 1)
        self.assertEqual(
            summary["navigation"]["measurement_list"][0]["primary_surface"],
            "plot",
        )

        self.assertEqual(selected["measurement_record_id"], "legacy-rabi-001")
        self.assertEqual(selected["primary_surface"]["kind"], "plot")
        self.assertEqual(
            selected["primary_surface"]["source_surface"],
            "plot_first_visual_review",
        )
        self.assertEqual(
            selected["primary_surface"]["visual_summary_id"],
            "legacy-rabi-001-visual-1",
        )
        self.assertEqual(selected["plot_panel"]["state"], "ready_for_gui_renderer")
        self.assertEqual(selected["plot_panel"]["title_label"], "Rabi calibration follow-up")
        self.assertEqual(selected["plot_panel"]["point_count"], 5)
        self.assertEqual(selected["plot_panel"]["point_data"], "available_from_visual_review_model")
        self.assertEqual(selected["plot_panel"]["rendering"], "not_performed")
        self.assertNotIn("points", selected["plot_panel"])
        self.assertEqual(
            selected["plot_panel"]["x_axis"],
            {
                "label": "Drive frequency",
                "name": "drive_frequency",
                "role": "sweep_axis",
                "unit": "GHz",
            },
        )
        self.assertEqual(
            selected["table_panel"]["primary_table"],
            {"columns": ["drive_frequency", "signal"], "row_count": 5},
        )
        self.assertEqual(selected["table_panel"]["dataframe_adapter"], "not_invoked")
        self.assertEqual(selected["context_panel"]["linked_context_count"], 1)
        self.assertEqual(
            selected["context_panel"]["linked_context_refs"][0]["link_id"],
            "package-legacy-001-parameter-snapshot",
        )
        self.assertEqual(
            [item["action"] for item in selected["available_actions"]],
            [
                "render_primary_plot",
                "open_table_drilldown",
                "copy_dataframe_code",
                "accept_package",
            ],
        )
        self.assertEqual(
            selected["available_actions"][0]["state"],
            "deferred_to_gui_renderer",
        )
        self.assertEqual(
            selected["available_actions"][2]["state"],
            "not_defined",
        )
        self.assertEqual(
            summary["consumed_projections"]["visual_review"]["visual_summary_count"], 1
        )

    def test_no_declared_plot_routes_primary_surface_to_table_drilldown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            manifest = _manifest(package_dir)
            manifest["selected_measurements"][0]["declared_preview_metadata"][
                "plot_candidates"
            ] = []
            _write_manifest(package_dir, manifest)

            summary = build_handoff_package_gui_view_state(package_dir)
            selected = summary["selected_measurement"]
            _assert_no_path_leak(self, summary, Path(temp_dir))
            _assert_no_path_leak(self, summary, package_dir)

        self.assertEqual(selected["primary_surface"]["kind"], "table_drilldown")
        self.assertEqual(
            selected["primary_surface"]["source_surface"],
            "table_drilldown",
        )
        self.assertEqual(selected["plot_panel"]["state"], "not_primary_surface")
        self.assertEqual(
            [item["action"] for item in selected["available_actions"]],
            ["open_table_drilldown", "copy_dataframe_code", "accept_package"],
        )
        self.assertEqual(
            summary["package"]["primary_surface_counts"],
            {"plot": 0, "review_findings": 0, "table_drilldown": 1},
        )

    def test_unsupported_preview_shape_routes_primary_surface_to_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            manifest = _manifest(package_dir)
            manifest["selected_measurements"][0]["declared_preview_metadata"]["data_shape"][
                "kind"
            ] = "unsupported_preview_shape"
            _write_manifest(package_dir, manifest)

            summary = build_handoff_package_gui_view_state(package_dir)
            selected = summary["selected_measurement"]
            _assert_no_path_leak(self, summary, Path(temp_dir))
            _assert_no_path_leak(self, summary, package_dir)

        self.assertEqual(selected["primary_surface"]["kind"], "review_findings")
        self.assertIn(
            "declared_preview_affordance_unsupported",
            selected["findings_panel"]["finding_codes"],
        )
        self.assertEqual(
            summary["package"]["primary_surface_counts"],
            {"plot": 0, "review_findings": 1, "table_drilldown": 0},
        )

    def test_multiple_measurements_project_navigation_and_default_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            _add_second_measurement_without_plot(package_dir)

            summary = build_handoff_package_gui_view_state(package_dir)
            _assert_no_path_leak(self, summary, Path(temp_dir))
            _assert_no_path_leak(self, summary, package_dir)

        self.assertEqual(summary["package"]["selected_measurement_id"], "legacy-rabi-001")
        self.assertEqual(
            [item["measurement_record_id"] for item in summary["navigation"]["measurement_list"]],
            ["legacy-rabi-001", "legacy-rabi-002"],
        )
        self.assertEqual(
            [item["primary_surface"] for item in summary["navigation"]["measurement_list"]],
            ["plot", "table_drilldown"],
        )
        self.assertEqual(
            summary["package"]["primary_surface_counts"],
            {"plot": 1, "review_findings": 0, "table_drilldown": 1},
        )
        self.assertEqual(len(summary["measurement_states"]), 2)

    def test_default_selection_uses_package_order_not_consumption_projection_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(Path(temp_dir))
            _add_second_measurement_without_plot(package_dir)
            actual_consumption = gui_summary.build_handoff_package_preview_consumption_summary(
                package_dir
            )
            actual_consumption["measurements"] = list(reversed(actual_consumption["measurements"]))

            with patch.object(
                gui_summary,
                "build_handoff_package_preview_consumption_summary",
                return_value=actual_consumption,
            ):
                summary = build_handoff_package_gui_view_state(package_dir)

        self.assertEqual(summary["package"]["selected_measurement_id"], "legacy-rabi-001")
        self.assertEqual(
            [item["measurement_record_id"] for item in summary["navigation"]["measurement_list"]],
            ["legacy-rabi-001", "legacy-rabi-002"],
        )

    def test_rejects_projection_package_id_drift(self) -> None:
        visual_model = {
            "package": {
                "package_id": "wrong-package",
                "visual_summary_count": 0,
            },
            "visual_summaries": [],
            "measurement_index": [],
            "linked_context_refs": [],
        }
        with patch.object(
            gui_summary,
            "build_handoff_package_visual_review_model_from_read_view",
            return_value=visual_model,
        ):
            with self.assertRaisesRegex(ValueError, "package id alignment"):
                build_handoff_package_gui_view_state(PACKAGE)

    def test_rejects_projection_measurement_id_drift(self) -> None:
        visual_model = {
            "package": {
                "package_id": "handoff-package-legacy-rabi-001",
                "visual_summary_count": 0,
            },
            "visual_summaries": [],
            "measurement_index": [
                {
                    "measurement_record_id": "other-measurement",
                    "visual_summary_ids": [],
                    "attention_items": [],
                    "finding_codes": [],
                    "linked_context_count": 0,
                    "table_drilldown": {
                        "primary_table": {"columns": ["x"], "row_count": 0},
                        "preview_table": {"columns": ["x"], "row_count": 0},
                        "dataframe_adapter": "not_defined",
                    },
                }
            ],
            "linked_context_refs": [],
        }
        with patch.object(
            gui_summary,
            "build_handoff_package_visual_review_model_from_read_view",
            return_value=visual_model,
        ):
            with self.assertRaisesRegex(ValueError, "aligned measurement ids"):
                build_handoff_package_gui_view_state(PACKAGE)

    def test_rejects_unknown_first_surface(self) -> None:
        actual_consumption = gui_summary.build_handoff_package_preview_consumption_summary(PACKAGE)
        actual_consumption["measurements"][0]["first_surface"]["surface"] = "mystery_surface"
        with patch.object(
            gui_summary,
            "build_handoff_package_preview_consumption_summary",
            return_value=actual_consumption,
        ):
            with self.assertRaisesRegex(ValueError, "known preview-consumption first surface"):
                build_handoff_package_gui_view_state(PACKAGE)

    def test_rejects_unknown_linked_context_measurement_id(self) -> None:
        read_view = gui_summary.open_handoff_package_view(PACKAGE)
        visual_model = gui_summary.build_handoff_package_visual_review_model_from_read_view(
            read_view
        )
        visual_model["linked_context_refs"][0]["linked_measurement_record_ids"].append(
            "unknown-measurement"
        )
        with patch.object(
            gui_summary,
            "build_handoff_package_visual_review_model_from_read_view",
            return_value=visual_model,
        ):
            with self.assertRaisesRegex(ValueError, "linked context measurement ids to align"):
                build_handoff_package_gui_view_state(PACKAGE)

    def test_rejects_non_list_table_columns_from_visual_projection(self) -> None:
        read_view = gui_summary.open_handoff_package_view(PACKAGE)
        visual_model = gui_summary.build_handoff_package_visual_review_model_from_read_view(
            read_view
        )
        visual_model["measurement_index"][0]["table_drilldown"]["primary_table"]["columns"] = (
            "drive_frequency"
        )
        with patch.object(
            gui_summary,
            "build_handoff_package_visual_review_model_from_read_view",
            return_value=visual_model,
        ):
            with self.assertRaisesRegex(ValueError, "primary_table.columns"):
                build_handoff_package_gui_view_state(PACKAGE)
