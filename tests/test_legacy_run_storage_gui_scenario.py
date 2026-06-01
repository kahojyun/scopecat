from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "scripts" / "scenarios" / "legacy_run_storage_gui.py"


class LegacyRunStorageGuiScenarioTest(unittest.TestCase):
    def test_script_runs_full_legacy_to_gui_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "scenario"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCENARIO),
                    "--workspace",
                    str(workspace),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            console_summary = json.loads(completed.stdout)
            summary_path = Path(console_summary["scenario_summary"])
            html_path = Path(console_summary["html_review"])
            operator_review_html_path = Path(console_summary["operator_review_html"])
            full_summary = json.loads(summary_path.read_text(encoding="utf-8"))
            html = html_path.read_text(encoding="utf-8")
            operator_review_html = operator_review_html_path.read_text(encoding="utf-8")

        self.assertEqual(console_summary["scenario"], "legacy_run_storage_gui")
        self.assertEqual(
            console_summary["workflow"],
            {
                "legacy_record_classifications": [
                    "recorded_legacy_run",
                    "recorded_legacy_run",
                ],
                "primary_attach_classifications": [
                    "attached_legacy_primary_data",
                    "attached_legacy_primary_data",
                ],
                "context_attach_classifications": [
                    "attached_measurement_record_context",
                    "attached_measurement_record_context",
                ],
                "inventory_classification": "measurement_record_storage_inventory_ready",
                "read_view_classifications": [
                    "primary_table_ready",
                    "primary_table_ready",
                ],
            },
        )
        self.assertEqual(
            full_summary["user_input"],
            [
                {
                    "legacy_system_id": "legacy-labview",
                    "legacy_run_id": "lv-run-001",
                    "label": "Legacy LabVIEW Run 001",
                    "experiment_type": "rabi",
                    "primary_locator": "legacy-system/run-001.tsv",
                    "notebook_locator": "legacy-notebook://operator-workstation/run-001",
                    "run_started_at": "2026-06-01T08:50:00Z",
                    "run_completed_at": "2026-06-01T08:55:00Z",
                    "created_at": "2026-06-01T09:00:00Z",
                },
                {
                    "legacy_system_id": "legacy-labview",
                    "legacy_run_id": "lv-run-002",
                    "label": "Legacy LabVIEW Run 002",
                    "experiment_type": "ramsey",
                    "primary_locator": "legacy-system/run-002.tsv",
                    "notebook_locator": "legacy-notebook://operator-workstation/run-002",
                    "run_started_at": "2026-06-01T09:45:00Z",
                    "run_completed_at": "2026-06-01T09:52:00Z",
                    "created_at": "2026-06-01T10:00:00Z",
                },
            ],
        )
        self.assertEqual(
            set(entry["record_id"] for entry in full_summary["inventory"]["entries"]),
            {
                "rec-legacy-labview-lv-run-001",
                "rec-legacy-labview-lv-run-002",
            },
        )
        self.assertEqual(
            full_summary["operator_review"]["catalog"]["entry_count"],
            2,
        )
        self.assertEqual(
            len(full_summary["operator_review"]["context_attachments"]["entries"]),
            2,
        )
        self.assertEqual(
            full_summary["operator_review_artifact"]["html_artifact"]["filename"],
            "measurement-record-review.html",
        )
        self.assertFalse(
            full_summary["operator_review_artifact"]["html_artifact"]["durable_storage_member"],
        )
        self.assertEqual(
            [
                measurement["measurement_id"]
                for measurement in full_summary["measurement_review"]["measurements"]
            ],
            [
                "meas-legacy-labview-lv-run-001",
                "meas-legacy-labview-lv-run-002",
            ],
        )
        measurement, second_measurement = full_summary["measurement_review"]["measurements"]
        self.assertEqual(
            measurement["conversion"]["relationship"],
            "attached_converted_primary_data",
        )
        self.assertEqual(
            second_measurement["conversion"]["relationship"],
            "attached_converted_primary_data",
        )
        self.assertEqual(measurement["legacy"]["legacy_run_id"], "lv-run-001")
        self.assertEqual(second_measurement["legacy"]["legacy_run_id"], "lv-run-002")
        self.assertEqual(
            measurement["legacy"]["primary_locator"]["value"],
            "legacy-system/run-001.tsv",
        )
        self.assertEqual(
            second_measurement["legacy"]["primary_locator"]["value"],
            "legacy-system/run-002.tsv",
        )
        self.assertEqual(
            measurement["storage_artifacts"]["record_id"],
            "rec-legacy-labview-lv-run-001",
        )
        self.assertEqual(
            second_measurement["storage_artifacts"]["record_id"],
            "rec-legacy-labview-lv-run-002",
        )
        self.assertEqual(
            [artifact["role"] for artifact in full_summary["record_diagnostics"][0]["artifacts"]],
            [
                "creation_shell",
                "legacy_facts_receipt",
                "attached_primary_data",
                "writer_receipt",
                "finalization_receipt",
                "read_model_projection",
                "context_attachment_receipt",
            ],
        )
        self.assertEqual(
            {
                artifact["role"]: artifact["state"]
                for artifact in full_summary["record_diagnostics"][0]["artifacts"]
            },
            {
                "creation_shell": "present",
                "legacy_facts_receipt": "present",
                "attached_primary_data": "present",
                "writer_receipt": "present",
                "finalization_receipt": "present",
                "read_model_projection": "present",
                "context_attachment_receipt": "present",
            },
        )
        self.assertEqual(
            full_summary["record_diagnostics"][0]["diagnostics_policy"]["history_semantics"],
            "not_claimed",
        )
        self.assertEqual(
            [read_view["table"]["row_count"] for read_view in full_summary["read_views"]],
            [5, 4],
        )
        self.assertIn("Measurement Review", html)
        self.assertIn("Legacy LabVIEW Run 002", html)
        self.assertIn("Storage Diagnostics", html)
        self.assertIn("Record Artifacts", html)
        self.assertIn("Recorded Context", html)
        self.assertIn("Legacy parameter file", html)
        self.assertIn("Legacy setup binding file", html)
        self.assertIn("Legacy acquisition code directory", html)
        self.assertIn("Initial analysis summary", html)
        self.assertIn("Attached converted primary data", html)
        self.assertIn("attached_converted_primary_data", html)
        self.assertIn("legacy-labview / lv-run-001", html)
        self.assertIn("legacy-labview / lv-run-002", html)
        self.assertIn("legacy-system/run-001.tsv", html)
        self.assertIn("legacy-system/run-002.tsv", html)
        self.assertIn("signal_counts", html)
        self.assertIn("Measurement Records Review", operator_review_html)
        self.assertIn("Context Attachments", operator_review_html)
        self.assertIn("Legacy parameter file", operator_review_html)
        self.assertIn("rec-legacy-labview-lv-run-001", operator_review_html)
        self.assertIn("rec-legacy-labview-lv-run-002", operator_review_html)


if __name__ == "__main__":
    unittest.main()
