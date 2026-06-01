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
            full_summary = json.loads(summary_path.read_text(encoding="utf-8"))
            html = html_path.read_text(encoding="utf-8")

        self.assertEqual(console_summary["scenario"], "legacy_run_storage_gui")
        self.assertEqual(
            console_summary["workflow"],
            {
                "legacy_record_classification": "recorded_legacy_run",
                "import_classification": "imported_new_record",
                "inventory_classification": "measurement_record_storage_inventory_ready",
                "read_view_classification": "primary_table_ready",
            },
        )
        self.assertEqual(
            [entry["record_id"] for entry in full_summary["inventory"]["entries"]],
            ["imported-run-001", "legacy-run-001"],
        )
        self.assertEqual(
            [
                measurement["record_id"]
                for measurement in full_summary["measurement_review"]["measurements"]
            ],
            ["imported-run-001", "legacy-run-001"],
        )
        imported_measurement = full_summary["measurement_review"]["measurements"][0]
        self.assertEqual(
            imported_measurement["source"]["relationship"],
            "converted_from_legacy_record",
        )
        self.assertEqual(imported_measurement["source"]["legacy_record_id"], "legacy-run-001")
        self.assertEqual(
            imported_measurement["source"]["primary_locator"]["value"],
            "legacy-system/run-001.tsv",
        )
        self.assertEqual(full_summary["read_view"]["table"]["row_count"], 5)
        self.assertIn("Measurement Review", html)
        self.assertIn("Storage Diagnostics", html)
        self.assertIn("converted_from_legacy_record", html)
        self.assertIn("legacy-run-001", html)
        self.assertIn("imported-run-001", html)
        self.assertIn("legacy-system/run-001.tsv", html)
        self.assertIn("signal_counts", html)


if __name__ == "__main__":
    unittest.main()
