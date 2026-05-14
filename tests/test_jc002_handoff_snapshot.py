import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "jc002-handoff-snapshot"
PROTOTYPE = ROOT / "prototypes" / "jc002_handoff_snapshot.py"


def load_prototype():
    spec = importlib.util.spec_from_file_location("jc002_handoff_snapshot", PROTOTYPE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fixture_hashes(fixture=FIXTURE):
    hashes = {}
    for path in sorted(fixture.rglob("*")):
        if path.is_file():
            hashes[path.relative_to(fixture).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return hashes


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def artifact_by_id(manifest, artifact_id):
    return next(
        artifact for artifact in manifest["artifacts"] if artifact["artifact_id"] == artifact_id
    )


def refresh_artifact_integrity(snapshot_root, manifest, artifact_id):
    artifact = artifact_by_id(manifest, artifact_id)
    artifact_path = snapshot_root / artifact["path"]
    artifact["size_bytes"] = artifact_path.stat().st_size
    artifact["sha256"] = hashlib.sha256(artifact_path.read_bytes()).hexdigest()


def copy_fixture(tmp_dir):
    copied_snapshot = Path(tmp_dir) / "snapshot"
    shutil.copytree(FIXTURE, copied_snapshot)
    return copied_snapshot


class HandoffSnapshotPrototypeTest(unittest.TestCase):
    def test_summary_and_reader_cover_handoff_acceptance_without_mutating_fixture(self):
        prototype = load_prototype()
        before = fixture_hashes()

        snapshot = prototype.HandoffSnapshot.open(FIXTURE)
        summary = snapshot.summary()
        baseline = snapshot.load_run("run-baseline")
        group = snapshot.load_group()

        self.assertEqual(before, fixture_hashes())
        self.assertEqual(summary["identity"]["snapshot_id"], "handoff-fixture-a")
        self.assertEqual(summary["can_open"]["status"], "pass")
        self.assertEqual(summary["can_open"]["included_artifact_count"], 5)
        self.assertEqual(summary["can_open"]["required_sidecar_count"], 1)
        self.assertEqual(summary["selection"]["group_order"], ["run-baseline", "run-sample"])
        self.assertEqual(
            prototype.status_value(summary["selection"]["selected_reason"]),
            "baseline and sample runs selected for analysis handoff smoke testing",
        )

        run_ids = [run["run_id"] for run in summary["runs"]]
        self.assertEqual(run_ids, ["run-baseline", "run-sample"])
        for run in summary["runs"]:
            self.assertEqual(run["source_namespace"], "redacted-station-a")
            self.assertIn("sample_label:not_provided", run["warnings"])
            self.assertIn("important_parameters.temperature:unknown", run["warnings"])

        self.assertEqual(baseline["condition_label"], "baseline")
        self.assertEqual(baseline["per_run_note"]["value"], "baseline condition")
        self.assertEqual(baseline["shape"], [4, 2])
        self.assertEqual(baseline["axes"][0]["unit"], "Hz")
        self.assertEqual(baseline["values"][0]["unit"], "V")
        self.assertEqual(len(baseline["sidecars"]), 1)
        self.assertEqual(baseline["sidecars"][0]["sidecar_id"], "sidecar-baseline-columns")
        self.assertEqual(len(baseline["derived_inputs"]), 1)
        self.assertEqual(baseline["derived_inputs"][0]["artifact_id"], "derived-window-a")

        self.assertEqual(group["group_title"], "public handoff fixture group")
        self.assertEqual(group["run_order"], ["run-baseline", "run-sample"])
        self.assertEqual(group["per_run_notes"]["run-sample"]["value"], "sample condition")
        self.assertEqual([run["condition_label"] for run in group["runs"]], ["baseline", "sample"])
        self.assertEqual(len(group["runs"][1]["sidecars"]), 0)
        self.assertEqual(len(group["derived_inputs"]), 1)

        included_roles = {artifact["role"] for artifact in summary["artifacts"]["included"]}
        self.assertGreaterEqual(
            included_roles,
            {
                "primary_data",
                "required_read_sidecar",
                "handoff_context",
                "user_attached_derived_input",
            },
        )
        excluded = {
            artifact["artifact_id"]: artifact for artifact in summary["artifacts"]["excluded"]
        }
        self.assertEqual(excluded["unknown-array-a"]["role"], "unknown")
        self.assertEqual(excluded["report-artifact-a"]["role"], "report_artifact")
        self.assertEqual(
            excluded["internal-verification-ref-a"]["role"],
            "internal_verification_reference",
        )

        derived = [
            artifact
            for artifact in snapshot.artifacts
            if artifact["artifact_id"] == "derived-window-a"
        ][0]
        self.assertEqual(derived["role"], "user_attached_derived_input")
        self.assertEqual(derived["source_run_relation"], ["run-baseline", "run-sample"])
        self.assertEqual(derived["processed_status"], "processed-lossless-subset")
        self.assertTrue(derived["sha256"])
        self.assertGreater(derived["size_bytes"], 0)

        missing_paths = {field["path"]: field["status"] for field in summary["missing_fields"]}
        self.assertEqual(missing_paths["runs.run-baseline.sample_label"], "not_provided")
        self.assertEqual(
            missing_paths["runs.run-baseline.important_parameters.temperature"],
            "unknown",
        )
        self.assertEqual(missing_paths["runs.run-baseline.original_path_evidence"], "redacted")
        self.assertEqual(summary["redaction"]["status"], "export_declared_redacted_fixture")
        self.assertEqual(summary["shareability"]["status"], "not_assessed_by_reader")
        self.assertTrue(all(value is False for value in summary["safety_evidence"].values()))

    def test_copied_snapshot_opens_and_outputs_are_generated_outside_snapshot(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            copied_snapshot = tmp_path / "copied" / "snapshot"
            shutil.copytree(FIXTURE, copied_snapshot)
            before = fixture_hashes(copied_snapshot)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            outputs = prototype.write_outputs(snapshot, tmp_path / "outputs")

            self.assertEqual(before, fixture_hashes(copied_snapshot))
            self.assertEqual(
                {path.name for path in outputs},
                {
                    "handoff-summary.json",
                    "handoff-summary.md",
                    "reader-group.json",
                    "single-run-plot.svg",
                    "group-sanity-plot.svg",
                },
            )
            for path in outputs:
                self.assertTrue(path.exists())
                self.assertNotIn(copied_snapshot, path.parents)

            summary = read_json(tmp_path / "outputs" / "handoff-summary.json")
            group = read_json(tmp_path / "outputs" / "reader-group.json")
            markdown = (tmp_path / "outputs" / "handoff-summary.md").read_text(encoding="utf-8")
            self.assertEqual(summary["redaction"]["status"], "export_declared_redacted_fixture")
            self.assertEqual(group["run_order"], ["run-baseline", "run-sample"])
            self.assertIn("## Missing And Redacted", markdown)
            self.assertIn("## Shareability", markdown)
            plot_svg = (tmp_path / "outputs" / "group-sanity-plot.svg").read_text()
            self.assertIn("<polyline", plot_svg)
            self.assertIn("frequency (Hz)", plot_svg)
            self.assertIn("response (V)", plot_svg)

    def test_rejects_outputs_inside_snapshot(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "output directory must be outside snapshot",
            ):
                prototype.write_outputs(snapshot, copied_snapshot / "outputs")

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "output directory must be outside snapshot",
            ):
                prototype.write_outputs(snapshot, copied_snapshot)

    def test_direct_plot_writer_rejects_outputs_inside_snapshot(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "output file must be outside snapshot",
            ):
                prototype.render_svg_plot(snapshot.load_group(), copied_snapshot / "plot.svg")

    def test_direct_plot_writer_rejects_symlinked_parent_into_snapshot(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            copied_snapshot = copy_fixture(tmp_path)
            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            link_to_data = tmp_path / "link-to-data"
            link_to_data.symlink_to(copied_snapshot / "data", target_is_directory=True)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "output file must be outside snapshot",
            ):
                prototype.render_svg_plot(snapshot.load_group(), link_to_data / "plot.svg")

    def test_rejects_symlink_output_targets_into_snapshot(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            copied_snapshot = copy_fixture(tmp_path)
            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            out_dir = tmp_path / "outputs"
            out_dir.mkdir()
            (copied_snapshot / "existing-summary.json").write_text("snapshot data")
            (out_dir / "handoff-summary.json").symlink_to(copied_snapshot / "existing-summary.json")

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "output file must not be a symlink",
            ):
                prototype.write_outputs(snapshot, out_dir)

    def test_plot_outputs_replace_hardlinks_without_mutating_snapshot(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            copied_snapshot = copy_fixture(tmp_path)
            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            out_dir = tmp_path / "outputs"
            out_dir.mkdir()
            snapshot_file = copied_snapshot / "context" / "readme-note.txt"
            before = snapshot_file.read_text(encoding="utf-8")
            os.link(snapshot_file, out_dir / "group-sanity-plot.svg")

            prototype.write_outputs(snapshot, out_dir)

            self.assertEqual(snapshot_file.read_text(encoding="utf-8"), before)
            self.assertIn("<polyline", (out_dir / "group-sanity-plot.svg").read_text())

    def test_direct_plot_writer_rejects_symlink_output_targets(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            copied_snapshot = copy_fixture(tmp_path)
            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            target = tmp_path / "target.svg"
            target.write_text("target", encoding="utf-8")
            link = tmp_path / "plot.svg"
            link.symlink_to(target)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "output file must not be a symlink",
            ):
                prototype.render_svg_plot(snapshot.load_group(), link)

    def test_direct_plot_writer_does_not_check_redaction(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            copied_snapshot = copy_fixture(tmp_path)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["selection"]["group_title"] = "Checked on control-pc-alpha"
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            prototype.render_svg_plot(snapshot.load_group(), tmp_path / "plot.svg")

            self.assertTrue((tmp_path / "plot.svg").exists())

    def test_cli_writes_summary_reader_and_consumer_side_plots(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = subprocess.run(
                [sys.executable, str(PROTOTYPE), str(FIXTURE), "--out-dir", tmp_dir],
                check=True,
                capture_output=True,
                text=True,
            )

            output_dir = Path(tmp_dir)
            self.assertIn("handoff-summary.json", result.stdout)
            self.assertNotIn(tmp_dir, result.stdout)
            self.assertTrue((output_dir / "handoff-summary.json").exists())
            self.assertTrue((output_dir / "reader-group.json").exists())
            self.assertTrue((output_dir / "single-run-plot.svg").exists())
            self.assertTrue((output_dir / "group-sanity-plot.svg").exists())

    def test_rejects_invalid_manifest_json_with_snapshot_error(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            (copied_snapshot / "snapshot-manifest.json").write_text("{not-json", encoding="utf-8")

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "could not be read as JSON",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_json_read_errors_do_not_expose_absolute_paths(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest_path.write_text("{not-json", encoding="utf-8")

            with self.assertRaises(prototype.HandoffSnapshotError) as context:
                prototype.HandoffSnapshot.open(copied_snapshot)

            self.assertIn(
                "snapshot-manifest.json could not be read as JSON",
                str(context.exception),
            )
            self.assertNotIn(str(copied_snapshot), str(context.exception))

    def test_rejects_non_standard_json_constants(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            text = manifest_path.read_text(encoding="utf-8")
            text = text.replace(
                '"baseline and sample runs selected for analysis handoff smoke testing"',
                "NaN",
            )
            manifest_path.write_text(text, encoding="utf-8")

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "snapshot-manifest.json could not be read as JSON",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_symlinked_manifest(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            copied_snapshot = copy_fixture(tmp_path)
            external_manifest = tmp_path / "external-manifest.json"
            (copied_snapshot / "snapshot-manifest.json").replace(external_manifest)
            (copied_snapshot / "snapshot-manifest.json").symlink_to(external_manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "snapshot-manifest.json must not be a symlink",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_reader_does_not_scan_manifest_for_redaction(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["original_path_evidence"] = {
                "status": "provided",
                "value": "/Users/fixtureuser/private-lab/run-0001",
            }
            manifest["selection"]["selected_reason"] = {
                "status": "provided",
                "value": "Checked on control-pc-alpha. Do not share.",
            }
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            summary = snapshot.summary()

            self.assertEqual(summary["redaction"]["status"], "export_declared_redacted_fixture")
            self.assertEqual(summary["shareability"]["status"], "not_assessed_by_reader")
            self.assertNotIn("findings", summary["redaction"])

    def test_reader_ignores_user_defined_redaction_terms(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["redaction_policy"]["forbidden_content"].append("project-token-alpha")
            manifest["redaction_policy"]["forbidden_content"].append(
                {"kind": "literal", "value": "/Users/alice/private-run"}
            )
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            self.assertEqual(
                snapshot.summary()["redaction"]["status"],
                "export_declared_redacted_fixture",
            )

    def test_markdown_summary_escapes_active_markdown_fields(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["selection"]["group_title"] = "![x](https://example.test/pixel)"
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            markdown = prototype.render_markdown(snapshot.summary())

            self.assertIn(r"\!\[x\]\(https://example\.test/pixel\)", markdown)
            self.assertNotIn("![x](https://example.test/pixel)", markdown)

    def test_write_outputs_does_not_check_redaction(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            copied_snapshot = copy_fixture(tmp_path)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["selection"]["selected_reason"] = {
                "status": "provided",
                "value": "Checked on control-pc-alpha. Do not share.",
            }
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            outputs = prototype.write_outputs(snapshot, tmp_path / "outputs")

            self.assertTrue((tmp_path / "outputs" / "handoff-summary.json").exists())
            self.assertTrue(outputs)

    def test_cli_renders_summary_without_redaction_checks(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["selection"]["selected_reason"] = {
                "status": "provided",
                "value": "Checked on control-pc-alpha. Do not share.",
            }
            write_json(manifest_path, manifest)

            result = subprocess.run(
                [sys.executable, str(PROTOTYPE), str(copied_snapshot)],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0)
            self.assertIn(r"control\-pc\-alpha", result.stdout)
            self.assertEqual(result.stderr, "")

    def test_rejects_artifact_path_traversal(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "primary-baseline")["path"] = "../outside.csv"
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "must stay inside snapshot",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_windows_drive_relative_artifact_paths(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            drive_relative_path = copied_snapshot / "C:baseline.csv"
            shutil.copyfile(copied_snapshot / "data" / "baseline.csv", drive_relative_path)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact = artifact_by_id(manifest, "primary-baseline")
            artifact["path"] = "C:baseline.csv"
            refresh_artifact_integrity(copied_snapshot, manifest, "primary-baseline")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "must not use Windows drive path",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_missing_artifact_id_with_snapshot_error(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            del manifest["artifacts"][0]["artifact_id"]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "artifact requires artifact_id",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_empty_run_group_at_load_time(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"] = []
            manifest["selection"]["group_order"] = []
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "snapshot requires at least one run",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_malformed_run_artifact_ids_with_snapshot_error(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][1]["primary_artifact_id"] = {}
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "requires primary_artifact_id",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["required_sidecar_artifact_ids"] = [{}]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "required sidecars must use IDs",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_group_order_can_differ_from_manifest_run_order(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["selection"]["group_order"] = ["run-sample", "run-baseline"]
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            group = snapshot.load_group()

            self.assertEqual(group["run_order"], ["run-sample", "run-baseline"])
            self.assertEqual(
                [run["run_id"] for run in group["runs"]],
                ["run-sample", "run-baseline"],
            )

    def test_rejects_duplicate_group_order_entries(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["selection"]["group_order"] = ["run-baseline", "run-baseline"]
            manifest["selection"]["per_run_notes"].pop("run-sample")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "selection.group_order must not contain duplicates",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_invalid_status_value_semantics(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["sample_label"] = {
                "status": "unknown",
                "value": "sample-should-not-travel",
            }
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "status unknown must not carry value",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_non_object_important_parameter(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["important_parameters"] = ["bad"]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "run run-baseline parameter must be an object",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_primary_data_shape_mismatch(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "primary-baseline")["shape"] = [99, 2]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "shape mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_empty_primary_data(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            data_path = copied_snapshot / "data" / "baseline.csv"
            data_path.write_text("frequency_hz,response_v\n", encoding="utf-8")
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "primary-baseline")
            artifact_by_id(manifest, "primary-baseline")["shape"] = [0, 2]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "requires data rows",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_non_numeric_primary_data(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            data_path = copied_snapshot / "data" / "baseline.csv"
            data_path.write_text("frequency_hz,response_v\n1.0,not-a-number\n", encoding="utf-8")
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "primary-baseline")
            artifact_by_id(manifest, "primary-baseline")["shape"] = [1, 2]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "must be numeric",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_non_utf8_primary_data_with_snapshot_error(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            data_path = copied_snapshot / "data" / "baseline.csv"
            data_path.write_bytes(b"\xff\xfe\x00\x00")
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "primary-baseline")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "could not be read as CSV",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_non_finite_primary_data(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            data_path = copied_snapshot / "data" / "baseline.csv"
            data_path.write_text("frequency_hz,response_v\n1.0,NaN\n", encoding="utf-8")
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "primary-baseline")
            artifact_by_id(manifest, "primary-baseline")["shape"] = [1, 2]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "must be finite",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_duplicate_primary_data_columns(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            data_path = copied_snapshot / "data" / "baseline.csv"
            data_path.write_text(
                "frequency_hz,response_v,response_v\n1.0,0.1,0.2\n",
                encoding="utf-8",
            )
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "primary-baseline")
            artifact_by_id(manifest, "primary-baseline")["shape"] = [1, 3]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "duplicate columns",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_empty_primary_data_column_names(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            data_path = copied_snapshot / "data" / "sample.csv"
            data_path.write_text(",response_v\n1.0,0.1\n", encoding="utf-8")
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "primary-sample")
            sample_artifact = artifact_by_id(manifest, "primary-sample")
            sample_artifact["shape"] = [1, 2]
            sample_artifact["axes"][0]["column"] = ""
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "requires column names",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_undeclared_primary_data_columns(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            data_path = copied_snapshot / "data" / "baseline.csv"
            data_path.write_text(
                "frequency_hz,response_v,extra_numeric\n1.0,0.1,42\n",
                encoding="utf-8",
            )
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "primary-baseline")
            artifact_by_id(manifest, "primary-baseline")["shape"] = [1, 3]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "undeclared columns",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_missing_sidecar_file_raises_snapshot_error(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            (copied_snapshot / "sidecars" / "baseline-columns.json").unlink()

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "included artifact sidecar-baseline-columns is missing",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_sidecar_payload_id_mismatch(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            sidecar_path = copied_snapshot / "sidecars" / "baseline-columns.json"
            sidecar = read_json(sidecar_path)
            sidecar["sidecar_id"] = "different-sidecar"
            write_json(sidecar_path, sidecar)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "sidecar-baseline-columns")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "sidecar sidecar-baseline-columns ID mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_sidecar_column_metadata_mismatch(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            sidecar_path = copied_snapshot / "sidecars" / "baseline-columns.json"
            sidecar = read_json(sidecar_path)
            sidecar["columns"][0]["unit"] = "GHz"
            write_json(sidecar_path, sidecar)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "sidecar-baseline-columns")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "column unit mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            sidecar_path = copied_snapshot / "sidecars" / "baseline-columns.json"
            sidecar = read_json(sidecar_path)
            sidecar["columns"][0]["axis"] = "y"
            write_json(sidecar_path, sidecar)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "sidecar-baseline-columns")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "column axis mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_duplicate_sidecar_columns(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            sidecar_path = copied_snapshot / "sidecars" / "baseline-columns.json"
            sidecar = read_json(sidecar_path)
            sidecar["columns"].insert(
                0,
                {
                    "name": "frequency_hz",
                    "quantity": "drive_frequency",
                    "unit": "GHz",
                    "axis": "y",
                },
            )
            write_json(sidecar_path, sidecar)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "sidecar-baseline-columns")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "duplicate columns",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_malformed_primary_metadata_raises_snapshot_error(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            del artifact_by_id(manifest, "primary-baseline")["axes"][0]["column"]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "axis column mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_unknown_source_run_relation(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "derived-window-a")["source_run_relation"] = [
                "run-baseline",
                "run-missing",
            ]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "relation references unknown run",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_primary_artifact_relation_overclaiming_runs(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "primary-sample")["source_run_relation"] = [
                "run-sample",
                "run-baseline",
            ]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "primary artifact relation mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_malformed_derived_input_payload_at_load_time(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            derived_path = copied_snapshot / "derived" / "selected-window.json"
            derived_path.write_text("{bad-json", encoding="utf-8")
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "derived-window-a")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "could not be read as JSON",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_derived_input_payload_identity_mismatch(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            derived_path = copied_snapshot / "derived" / "selected-window.json"
            derived = read_json(derived_path)
            derived["derived_input_id"] = "wrong-id"
            write_json(derived_path, derived)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "derived-window-a")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "derived input derived-window-a ID mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            derived_path = copied_snapshot / "derived" / "selected-window.json"
            derived = read_json(derived_path)
            derived["source_run_relation"] = ["run-missing"]
            write_json(derived_path, derived)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "derived-window-a")
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "derived input derived-window-a relation mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_non_string_source_run_relation(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "derived-window-a")["source_run_relation"] = [{}]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "source_run_relation must use run IDs",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_sidecar_relation_that_omits_requiring_run(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            artifact_by_id(manifest, "sidecar-baseline-columns")["source_run_relation"] = [
                "run-sample"
            ]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "sidecar sidecar-baseline-columns relation mismatch",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_unrequired_required_sidecar_artifact(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["required_sidecar_artifact_ids"] = []
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "sidecar sidecar-baseline-columns is not required by run-baseline",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_missing_required_nested_manifest_fields(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            del manifest["source_system"]["type"]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "source_system requires type",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            del manifest["redaction_policy"]["profile"]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "redaction_policy requires profile",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            del manifest["redaction_status"]["produced_by"]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "redaction_status requires produced_by",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_partial_safety_evidence(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            del manifest["safety_evidence"]["network_or_cloud_dependency"]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "missing safety evidence",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_unknown_safety_evidence(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["safety_evidence"]["extra_flag"] = False
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "unknown safety evidence",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_missing_per_run_notes_appear_in_summary_warnings(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["selection"]["per_run_notes"]["run-baseline"] = {"status": "not_provided"}
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            summary = snapshot.summary()
            missing_paths = {field["path"]: field["status"] for field in summary["missing_fields"]}

            self.assertEqual(
                missing_paths["selection.per_run_notes.run-baseline"],
                "not_provided",
            )

    def test_rejects_missing_condition_label_at_load_time(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            del manifest["runs"][0]["condition_label"]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "requires condition_label",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_rejects_missing_group_title_at_load_time(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            del manifest["selection"]["group_title"]
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "selection requires group_title",
            ):
                prototype.HandoffSnapshot.open(copied_snapshot)

    def test_reader_does_not_scan_included_payloads_for_redaction(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            context_path = copied_snapshot / "context" / "readme-note.txt"
            context_path.write_text(
                "Public note accidentally mentions TCPIP::10.2.3.4::INSTR\n",
                encoding="utf-8",
            )
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "handoff-context-note")
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            summary = snapshot.summary()

            self.assertEqual(summary["redaction"]["status"], "export_declared_redacted_fixture")
            self.assertNotIn("findings", summary["redaction"])

    def test_reader_does_not_decode_binary_payloads_for_redaction(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            context_path = copied_snapshot / "context" / "readme-note.txt"
            context_path.write_bytes(b"\xff\xfe\x00\x00")
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            refresh_artifact_integrity(copied_snapshot, manifest, "handoff-context-note")
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            summary = snapshot.summary()

            self.assertEqual(summary["redaction"]["status"], "export_declared_redacted_fixture")
            self.assertNotIn("findings", summary["redaction"])

    def test_reader_does_not_classify_sensitive_categories(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            manifest["runs"][0]["device_label"] = {
                "status": "provided",
                "value": "sample ID = alpha-private-001",
            }
            manifest["selection"]["selected_reason"] = {
                "status": "provided",
                "value": "Checked on control-pc-alpha. Do not share.",
            }
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            summary = snapshot.summary()

            self.assertEqual(summary["redaction"]["status"], "export_declared_redacted_fixture")
            self.assertNotIn("findings", summary["redaction"])

    def test_plot_uses_manifest_declared_axis_and_value_metadata(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            for artifact_id in ("primary-baseline", "primary-sample"):
                artifact = artifact_by_id(manifest, artifact_id)
                artifact["axes"][0]["name"] = "declared detuning"
                artifact["axes"][0]["unit"] = "MHz"
                artifact["values"][0]["name"] = "declared signal"
                artifact["values"][0]["unit"] = "arb"
            sidecar_path = copied_snapshot / "sidecars" / "baseline-columns.json"
            sidecar = read_json(sidecar_path)
            sidecar["columns"][0]["unit"] = "MHz"
            sidecar["columns"][1]["unit"] = "arb"
            write_json(sidecar_path, sidecar)
            refresh_artifact_integrity(copied_snapshot, manifest, "sidecar-baseline-columns")
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            output_path = Path(tmp_dir) / "plot.svg"
            prototype.render_svg_plot(snapshot.load_group(), output_path)
            svg = output_path.read_text(encoding="utf-8")

            self.assertIn("declared detuning (MHz)", svg)
            self.assertIn("declared signal (arb)", svg)

    def test_group_plot_handles_different_run_column_names(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            sample_data = copied_snapshot / "data" / "sample.csv"
            sample_data.write_text(
                "sample_frequency_hz,sample_response_v\n1.0,0.13\n2.0,0.29\n",
                encoding="utf-8",
            )
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            sample_artifact = artifact_by_id(manifest, "primary-sample")
            sample_artifact["axes"][0]["column"] = "sample_frequency_hz"
            sample_artifact["values"][0]["column"] = "sample_response_v"
            sample_artifact["shape"] = [2, 2]
            refresh_artifact_integrity(copied_snapshot, manifest, "primary-sample")
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            output_path = Path(tmp_dir) / "plot.svg"
            prototype.render_svg_plot(snapshot.load_group(), output_path)

            self.assertIn("<polyline", output_path.read_text(encoding="utf-8"))

    def test_group_plot_rejects_mixed_units_under_one_label(self):
        prototype = load_prototype()
        with tempfile.TemporaryDirectory() as tmp_dir:
            copied_snapshot = copy_fixture(tmp_dir)
            manifest_path = copied_snapshot / "snapshot-manifest.json"
            manifest = read_json(manifest_path)
            sample_artifact = artifact_by_id(manifest, "primary-sample")
            sample_artifact["axes"][0]["unit"] = "MHz"
            sample_artifact["values"][0]["unit"] = "mV"
            write_json(manifest_path, manifest)

            snapshot = prototype.HandoffSnapshot.open(copied_snapshot)
            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "matching axis and value metadata",
            ):
                prototype.render_svg_plot(snapshot.load_group(), Path(tmp_dir) / "plot.svg")

    def test_plot_handles_constant_x_values(self):
        prototype = load_prototype()
        group = {
            "group_title": "constant x fixture",
            "runs": [
                {
                    "run_id": "run-constant-x",
                    "condition_label": "single-point",
                    "axes": [{"name": "frequency", "column": "frequency_hz", "unit": "Hz"}],
                    "values": [{"name": "response", "column": "response_v", "unit": "V"}],
                    "data": [{"frequency_hz": 1.0, "response_v": 0.2}],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "plot.svg"

            prototype.render_svg_plot(group, output_path)

            svg = output_path.read_text(encoding="utf-8")
            self.assertIn("<polyline", svg)
            self.assertIn("frequency (Hz)", svg)

    def test_plot_handles_large_constant_y_values(self):
        prototype = load_prototype()
        group = {
            "group_title": "large constant y fixture",
            "runs": [
                {
                    "run_id": "run-large-y",
                    "condition_label": "large-y",
                    "axes": [{"name": "frequency", "column": "frequency_hz", "unit": "Hz"}],
                    "values": [{"name": "response", "column": "response_v", "unit": "V"}],
                    "data": [
                        {"frequency_hz": 1.0, "response_v": 1e20},
                        {"frequency_hz": 2.0, "response_v": 1e20},
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "plot.svg"

            prototype.render_svg_plot(group, output_path)

            svg = output_path.read_text(encoding="utf-8")
            self.assertIn("<polyline", svg)

    def test_plot_rejects_extreme_ranges_that_overflow(self):
        prototype = load_prototype()
        group = {
            "group_title": "overflow y fixture",
            "runs": [
                {
                    "run_id": "run-overflow-y",
                    "condition_label": "overflow-y",
                    "axes": [{"name": "frequency", "column": "frequency_hz", "unit": "Hz"}],
                    "values": [{"name": "response", "column": "response_v", "unit": "V"}],
                    "data": [
                        {"frequency_hz": 1.0, "response_v": -1e308},
                        {"frequency_hz": 2.0, "response_v": 1e308},
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaisesRegex(
                prototype.HandoffSnapshotError,
                "plot ranges must be finite",
            ):
                prototype.render_svg_plot(group, Path(tmp_dir) / "plot.svg")


if __name__ == "__main__":
    unittest.main()
