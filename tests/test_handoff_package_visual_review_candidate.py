from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from implementation_candidates.handoff_package_read_view import (
    HandoffPackageReadView,
    open_handoff_package_view,
)
from implementation_candidates.handoff_package_visual_review import (
    build_handoff_package_visual_review_model,
    build_handoff_package_visual_review_model_from_read_view,
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


def _copy_package(temp_dir: str) -> Path:
    destination = Path(temp_dir) / PACKAGE.name
    shutil.copytree(PACKAGE, destination)
    return destination


def _load_manifest(package_dir: Path) -> dict[str, Any]:
    return json.loads((package_dir / "package-manifest.json").read_text(encoding="utf-8"))


def _write_manifest(package_dir: Path, manifest: dict[str, Any]) -> None:
    (package_dir / "package-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


class HandoffPackageVisualReviewCandidateTest(unittest.TestCase):
    def test_visual_review_model_is_plot_first_and_structured(self) -> None:
        model = build_handoff_package_visual_review_model(PACKAGE)

        self.assertEqual(model["artifact_posture"], "review_summary")
        self.assertEqual(
            model["visual_review_policy"]["primary_orientation"],
            "plot_first",
        )
        self.assertEqual(
            model["visual_review_policy"]["caption_text_generation"],
            "not_performed",
        )
        self.assertEqual(model["package"]["visual_summary_count"], 1)

        visual = model["visual_summaries"][0]
        self.assertEqual(visual["visual_priority"], "primary_review_surface")
        self.assertEqual(visual["measurement_label"], "Rabi calibration follow-up")
        self.assertEqual(visual["plot"]["kind"], "declared_xy_series")
        self.assertEqual(
            visual["plot"]["x_axis"],
            {
                "name": "drive_frequency",
                "label": "Drive frequency",
                "unit": "GHz",
                "role": "sweep_axis",
            },
        )
        self.assertEqual(
            visual["plot"]["y_axis"],
            {
                "name": "signal",
                "label": "Signal",
                "unit": "a.u.",
                "role": "response",
            },
        )
        self.assertEqual(visual["plot"]["series"]["point_count"], 5)
        self.assertEqual(
            visual["plot"]["series"]["points"][2],
            {"x": "5.02", "y": "0.81"},
        )
        self.assertEqual(visual["plot"]["rendering"], "not_performed")
        self.assertFalse(_contains_key(model, "caption"))

    def test_table_facts_are_drilldown_not_the_primary_surface(self) -> None:
        model = build_handoff_package_visual_review_model(PACKAGE)
        measurement = model["measurement_index"][0]

        self.assertTrue(
            {
                "artifact_posture",
                "visual_review_policy",
                "package",
                "visual_summaries",
                "measurement_index",
                "linked_context_refs",
                "attention",
            }.issubset(model)
        )
        self.assertTrue(model["visual_summaries"])
        self.assertEqual(
            measurement["visual_summary_ids"],
            ["legacy-rabi-001-visual-1"],
        )
        self.assertEqual(measurement["integrity_check"], "not_performed")
        self.assertEqual(
            measurement["table_drilldown"]["primary_table"],
            {"columns": ["drive_frequency", "signal"], "row_count": 5},
        )
        self.assertEqual(
            measurement["table_drilldown"]["preview_table"],
            {"columns": ["drive_frequency", "signal"], "row_count": 5},
        )
        self.assertNotIn("rows", measurement["table_drilldown"]["primary_table"])

    def test_linked_context_and_findings_stay_visible_next_to_plot(self) -> None:
        model = build_handoff_package_visual_review_model(PACKAGE)
        visual = model["visual_summaries"][0]

        self.assertEqual(
            visual["structured_context"]["linked_context_refs"][0]["link_id"],
            "package-legacy-001-parameter-snapshot",
        )
        self.assertEqual(
            visual["structured_context"]["linked_context_refs"][0]["materialization"],
            "reference_only",
        )
        attention_codes = [item["code"] for item in visual["attention_items"]]
        self.assertIn("linked_context_not_packaged_visible_reference", attention_codes)
        self.assertNotIn("package_integrity_not_verified", attention_codes)
        self.assertEqual(
            model["package"]["finding_codes"],
            ["linked_context_not_packaged_visible_reference"],
        )

    def test_multiple_declared_plot_candidates_become_multiple_visual_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            primary = package_dir / "measurements" / "legacy-rabi-001" / "primary.csv"
            primary.write_text(
                "drive_frequency,signal,phase\n4.98,0.12,0.01\n5.00,0.44,0.04\n5.02,0.81,0.10\n",
                encoding="utf-8",
            )
            manifest = _load_manifest(package_dir)
            preview = manifest["selected_measurements"][0]["declared_preview_metadata"]
            preview["declared_columns"].append(
                {
                    "name": "phase",
                    "label": "Phase",
                    "role": "response",
                    "unit": "rad",
                }
            )
            preview["plot_candidates"].append(
                {
                    "source": "measurements/legacy-rabi-001/primary.csv",
                    "x": "drive_frequency",
                    "y": "phase",
                }
            )
            _write_manifest(package_dir, manifest)

            model = build_handoff_package_visual_review_model(package_dir)

        self.assertEqual(model["package"]["visual_summary_count"], 2)
        self.assertEqual(
            [visual["visual_summary_id"] for visual in model["visual_summaries"]],
            [
                "legacy-rabi-001-visual-1",
                "legacy-rabi-001-visual-2",
            ],
        )
        self.assertEqual(model["visual_summaries"][1]["plot"]["y_axis"]["label"], "Phase")
        self.assertEqual(model["visual_summaries"][1]["plot"]["series"]["point_count"], 3)

    def test_no_declared_plot_candidates_stays_reviewable_without_blank_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            manifest = _load_manifest(package_dir)
            manifest["selected_measurements"][0]["declared_preview_metadata"][
                "plot_candidates"
            ] = []
            _write_manifest(package_dir, manifest)

            model = build_handoff_package_visual_review_model(package_dir)

        self.assertEqual(model["package"]["visual_summary_count"], 0)
        self.assertEqual(model["visual_summaries"], [])
        self.assertEqual(model["measurement_index"][0]["visual_summary_ids"], [])
        attention_codes = [
            item["code"] for item in model["measurement_index"][0]["attention_items"]
        ]
        self.assertCountEqual(
            attention_codes,
            ["linked_context_not_packaged_visible_reference", "no_declared_plot_candidates"],
        )

    def test_missing_axis_metadata_fails_instead_of_guessing_visual_labels(self) -> None:
        summary = open_handoff_package_view(PACKAGE).as_open_summary()
        summary["selected_measurements"][0]["preview_data"]["plot_series"][0]["y"] = (
            "missing_signal_metadata"
        )

        with self.assertRaisesRegex(ValueError, "requires plot axis metadata"):
            build_handoff_package_visual_review_model_from_read_view(
                HandoffPackageReadView(summary)
            )

    def test_duplicate_declared_plot_candidates_are_preserved_and_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            manifest = _load_manifest(package_dir)
            preview = manifest["selected_measurements"][0]["declared_preview_metadata"]
            preview["plot_candidates"].append(copy.deepcopy(preview["plot_candidates"][0]))
            _write_manifest(package_dir, manifest)

            model = build_handoff_package_visual_review_model(package_dir)

        self.assertEqual(model["package"]["visual_summary_count"], 2)
        self.assertEqual(model["visual_summaries"][0]["plot"]["candidate_position"], 1)
        self.assertEqual(model["visual_summaries"][0]["plot"]["duplicate_candidate"], False)
        self.assertEqual(model["visual_summaries"][1]["plot"]["candidate_position"], 2)
        self.assertEqual(model["visual_summaries"][1]["plot"]["duplicate_candidate"], True)
        duplicate_visual_codes = [
            item["code"] for item in model["visual_summaries"][1]["attention_items"]
        ]
        self.assertCountEqual(
            duplicate_visual_codes,
            [
                "linked_context_not_packaged_visible_reference",
                "duplicate_declared_plot_candidate",
            ],
        )
        self.assertIn(
            "duplicate_declared_plot_candidate",
            [item["code"] for item in model["measurement_index"][0]["attention_items"]],
        )

    def test_multiple_measurements_keep_visual_and_attention_index_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = _copy_package(temp_dir)
            primary = package_dir / "measurements" / "legacy-rabi-002" / "primary.csv"
            primary.parent.mkdir(parents=True)
            primary.write_text(
                "drive_frequency,signal\n4.90,0.12\n4.95,0.44\n",
                encoding="utf-8",
            )
            manifest = _load_manifest(package_dir)
            second = copy.deepcopy(manifest["selected_measurements"][0])
            second["measurement_record_id"] = "legacy-rabi-002"
            second["legacy_data_id"] = 1002
            second["label"] = "Second Rabi calibration follow-up"
            second["primary_data"]["package_path"] = "measurements/legacy-rabi-002/primary.csv"
            second["default_bundle"][0]["item_id"] = "legacy-rabi-002-primary"
            second["default_bundle"][0]["package_path"] = "measurements/legacy-rabi-002/primary.csv"
            second["declared_preview_metadata"]["plot_candidates"] = []
            manifest["selected_measurements"].append(second)
            manifest["linked_context"][0]["linked_measurement_record_ids"].append("legacy-rabi-002")
            _write_manifest(package_dir, manifest)

            model = build_handoff_package_visual_review_model(package_dir)

        self.assertEqual(model["package"]["measurement_count"], 2)
        self.assertEqual(model["package"]["visual_summary_count"], 1)
        self.assertEqual(
            [item["measurement_record_id"] for item in model["measurement_index"]],
            ["legacy-rabi-001", "legacy-rabi-002"],
        )
        self.assertEqual(
            model["measurement_index"][0]["visual_summary_ids"],
            ["legacy-rabi-001-visual-1"],
        )
        self.assertEqual(model["measurement_index"][1]["visual_summary_ids"], [])
        self.assertCountEqual(
            [item["code"] for item in model["measurement_index"][1]["attention_items"]],
            ["linked_context_not_packaged_visible_reference", "no_declared_plot_candidates"],
        )


if __name__ == "__main__":
    unittest.main()
