from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.handoff_package_visual_artifact import (
    HANDOFF_PACKAGE_VISUAL_REVIEW_ARTIFACT_NAME,
    build_handoff_package_visual_review_html,
    write_handoff_package_visual_review_artifact,
)
from implementation_candidates.handoff_package_visual_review import (
    build_handoff_package_visual_review_model,
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
ARTIFACT_NAME = HANDOFF_PACKAGE_VISUAL_REVIEW_ARTIFACT_NAME


def _visual_model() -> dict:
    return build_handoff_package_visual_review_model(PACKAGE)


def _minimal_model() -> dict:
    return {
        "package": {
            "display_name": "Synthetic package",
            "package_id": "handoff-package-synthetic",
            "preview_classification": "preview_ready",
            "measurement_count": 1,
            "visual_summary_count": 1,
        },
        "attention": [],
        "visual_summaries": [
            {
                "visual_summary_id": "synthetic-visual-1",
                "measurement_label": "Synthetic measurement",
                "attention_items": [],
                "plot": {
                    "candidate_position": 1,
                    "kind": "declared_xy_series",
                    "duplicate_candidate": False,
                    "source": "measurements/synthetic/primary.csv",
                    "x_axis": {"label": "Drive", "unit": "GHz"},
                    "y_axis": {"label": "Signal", "unit": "a.u."},
                    "series": {
                        "point_count": 3,
                        "points": [
                            {"x": "1.0", "y": "0.1"},
                            {"x": "2.0", "y": "0.4"},
                            {"x": "3.0", "y": "0.2"},
                        ],
                    },
                },
                "structured_context": {
                    "experiment_type": "rabi",
                    "target": "qA",
                    "primary_table": {"row_count": 3},
                    "preview_table": {"row_count": 3},
                    "linked_context_refs": [
                        {
                            "label": "Synthetic context",
                            "kind": "parameter_state",
                            "materialization": "reference_only",
                            "link_id": "synthetic-context",
                        }
                    ],
                },
            }
        ],
        "measurement_index": [
            {
                "measurement_record_id": "synthetic",
                "label": "Synthetic measurement",
                "experiment_type": "rabi",
                "target": "qA",
                "visual_summary_ids": ["synthetic-visual-1"],
                "attention_items": [],
            }
        ],
    }


class HandoffPackageVisualArtifactCandidateTest(unittest.TestCase):
    def test_static_html_renders_plot_first_review_surface(self) -> None:
        html = build_handoff_package_visual_review_html(_visual_model())

        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertLess(html.index("Visual Review"), html.index("Measurement Index"))
        self.assertIn("Rabi calibration follow-up", html)
        self.assertIn("Drive frequency (GHz)", html)
        self.assertIn("Signal (a.u.)", html)
        self.assertIn("<svg", html)
        self.assertIn("render: rendered_fixture_svg", html)
        self.assertIn("linked_context_not_packaged_visible_reference", html)
        self.assertIn("Static local review artifact", html)
        self.assertNotIn("<script", html.lower())

    def test_html_escapes_free_text_without_runtime_redaction(self) -> None:
        model = _minimal_model()
        model["package"]["display_name"] = 'Unsafe <Package> "Name"'
        model["visual_summaries"][0]["measurement_label"] = "Rabi <calibration>"
        model["visual_summaries"][0]["plot"]["candidate_position"] = "1 <img src=x>"
        model["visual_summaries"][0]["structured_context"]["linked_context_refs"][0]["label"] = (
            "Context <snapshot>"
        )

        html = build_handoff_package_visual_review_html(model)

        self.assertIn("Unsafe &lt;Package&gt; &quot;Name&quot;", html)
        self.assertIn("Rabi &lt;calibration&gt;", html)
        self.assertIn("visual 1 &lt;img src=x&gt;", html)
        self.assertIn("Context &lt;snapshot&gt;", html)
        self.assertNotIn("Unsafe <Package>", html)
        self.assertNotIn("Rabi <calibration>", html)
        self.assertNotIn("1 <img src=x>", html)
        self.assertNotIn("Context <snapshot>", html)

    def test_attention_severity_classes_are_allow_listed(self) -> None:
        model = _minimal_model()
        model["visual_summaries"][0]["attention_items"].append(
            {
                "code": "custom severity remains text",
                "severity": 'review" onclick="alert(1)',
                "subject_type": "visual_summary",
                "subject_id": "legacy-rabi-001:plot:0",
            }
        )

        html = build_handoff_package_visual_review_html(model)

        self.assertIn(
            '<span class="badge quiet">custom severity remains text</span>',
            html,
        )
        self.assertNotIn('onclick="alert(1)"', html)

    def test_static_html_generation_is_deterministic_for_same_model(self) -> None:
        self.assertEqual(
            build_handoff_package_visual_review_html(_minimal_model()),
            build_handoff_package_visual_review_html(_minimal_model()),
        )

    def test_no_declared_plots_render_as_explicit_empty_visual_state(self) -> None:
        model = _minimal_model()
        model["visual_summaries"] = []
        model["package"]["visual_summary_count"] = 0
        model["measurement_index"][0]["visual_summary_ids"] = []
        model["measurement_index"][0]["attention_items"].append(
            {
                "code": "no_declared_plot_candidates",
                "severity": "review",
                "subject_type": "measurement",
                "subject_id": "legacy-rabi-001",
            }
        )

        html = build_handoff_package_visual_review_html(model)

        self.assertIn("No declared plot candidates are available", html)
        self.assertIn("no declared plots", html)
        self.assertIn("no_declared_plot_candidates", html)

    def test_non_numeric_plot_points_do_not_claim_svg_rendering(self) -> None:
        model = _minimal_model()
        non_numeric = copy.deepcopy(model)
        non_numeric["visual_summaries"][0]["plot"]["series"]["points"][0]["y"] = "not-a-number"

        html = build_handoff_package_visual_review_html(non_numeric)

        self.assertIn("Plot points are not numeric-looking strings.", html)
        self.assertIn("render: not_rendered_non_numeric_points", html)

    def test_unbounded_numeric_plot_points_do_not_emit_svg_coordinates(self) -> None:
        model = _minimal_model()
        unbounded = copy.deepcopy(model)
        unbounded["visual_summaries"][0]["plot"]["series"]["points"] = [
            {"x": "1e308", "y": "1e308"},
            {"x": "-1e308", "y": "-1e308"},
        ]
        unbounded["visual_summaries"][0]["plot"]["series"]["point_count"] = 2

        html = build_handoff_package_visual_review_html(unbounded)

        self.assertIn("Plot points exceed the static renderer numeric range.", html)
        self.assertIn("render: not_rendered_numeric_range", html)
        self.assertNotIn("rendered_fixture_svg", html)
        self.assertNotIn("<polyline", html)

    def test_write_static_html_artifact_returns_local_review_receipt(self) -> None:
        model = _minimal_model()
        with tempfile.TemporaryDirectory() as temp_dir:
            receipt = write_handoff_package_visual_review_artifact(
                model,
                output_dir=Path(temp_dir),
            )
            artifact_path = Path(receipt["html_artifact"]["local_path"])
            html = artifact_path.read_text(encoding="utf-8")

        self.assertEqual(receipt["artifact_posture"], "review_summary")
        self.assertEqual(
            receipt["artifact_policy"]["artifact_class"],
            "local_review_surface",
        )
        self.assertEqual(
            receipt["artifact_policy"]["html_output"],
            "static_single_file",
        )
        self.assertEqual(
            receipt["artifact_policy"]["interactive_gui"],
            "not_defined",
        )
        self.assertEqual(
            receipt["html_artifact"]["filename"],
            ARTIFACT_NAME,
        )
        self.assertEqual(receipt["html_artifact"]["portable_package_member"], False)
        self.assertEqual(receipt["html_artifact"]["overwritten"], False)
        self.assertIn("Synthetic package", html)

    def test_write_rejects_package_root_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "package-manifest.json").write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "must not be in a package tree"):
                write_handoff_package_visual_review_artifact(
                    _minimal_model(),
                    output_dir=output_dir,
                )

            self.assertFalse((output_dir / ARTIFACT_NAME).exists())

    def test_write_rejects_output_dir_inside_package_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir)
            (package_root / "package-manifest.json").write_text("{}", encoding="utf-8")
            output_dir = package_root / "local-review"

            with self.assertRaisesRegex(ValueError, "must not be in a package tree"):
                write_handoff_package_visual_review_artifact(
                    _minimal_model(),
                    output_dir=output_dir,
                )

            self.assertFalse(output_dir.exists())

    def test_write_rejects_existing_artifact_without_overwrite(self) -> None:
        model = _minimal_model()
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            write_handoff_package_visual_review_artifact(model, output_dir=output_dir)
            artifact_path = output_dir / ARTIFACT_NAME
            original_html = artifact_path.read_text(encoding="utf-8")
            changed_model = _minimal_model()
            changed_model["package"]["display_name"] = "Changed package"

            with self.assertRaisesRegex(ValueError, "already exists"):
                write_handoff_package_visual_review_artifact(
                    changed_model,
                    output_dir=output_dir,
                )

            current_html = artifact_path.read_text(encoding="utf-8")

            self.assertEqual(current_html, original_html)
            self.assertNotIn("Changed package", current_html)

    def test_write_rejects_artifact_target_symlink_even_with_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "review"
            target_dir = Path(temp_dir) / "target"
            output_dir.mkdir()
            target_dir.mkdir()
            (output_dir / ARTIFACT_NAME).symlink_to(target_dir / "artifact.html")

            with self.assertRaisesRegex(ValueError, "target must not be a symlink"):
                write_handoff_package_visual_review_artifact(
                    _minimal_model(),
                    output_dir=output_dir,
                    overwrite=True,
                )

            self.assertFalse((target_dir / "artifact.html").exists())

    def test_write_allows_explicit_overwrite(self) -> None:
        model = _minimal_model()
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            first = write_handoff_package_visual_review_artifact(
                model,
                output_dir=output_dir,
            )
            second = write_handoff_package_visual_review_artifact(
                model,
                output_dir=output_dir,
                overwrite=True,
            )

        self.assertEqual(first["html_artifact"]["overwritten"], False)
        self.assertEqual(second["html_artifact"]["overwritten"], True)


if __name__ == "__main__":
    unittest.main()
