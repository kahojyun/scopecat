from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "adapter_authored_parameter_state_import_preview"
    / "json_and_xlsx_sources"
)


def _input_fixture() -> dict:
    return json.loads(
        (FIXTURE / "adapter-parameter-import-manifest.json").read_text(encoding="utf-8")
    )


def _expected_summary() -> dict:
    return json.loads(
        (FIXTURE / "expected-adapter-parameter-import-preview-summary.json").read_text(
            encoding="utf-8"
        )
    )


class AdapterAuthoredParameterStateImportPreviewFixtureTest(unittest.TestCase):
    def test_fixture_json_files_are_valid(self) -> None:
        for path in [
            FIXTURE / "adapter-parameter-import-manifest.json",
            FIXTURE / "expected-adapter-parameter-import-preview-summary.json",
        ]:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_fixture_represents_adapter_output_not_legacy_input(self) -> None:
        summary = _expected_summary()
        candidate = summary["candidate_summary"]
        attention = {item["code"]: item for item in candidate["attention"]}

        self.assertIn("adapter output", summary["boundary_notes"][0])
        self.assertEqual(
            candidate["adapter_parameter_import_policy"]["legacy_source_parsing"],
            "not_performed_by_scopecat",
        )
        self.assertEqual(
            attention["legacy_parameter_parser_not_in_core"]["does_not_claim"],
            "core_parameters_json_or_xlsx_reader",
        )

    def test_json_and_xlsx_sources_are_declared_not_parsed(self) -> None:
        source = _input_fixture()
        candidate = _expected_summary()["candidate_summary"]
        source_formats = [item["source_format"] for item in candidate["legacy_sources"]]

        self.assertEqual(source_formats, ["legacy_parameters_json", "xlsx_parameter_table"])
        self.assertEqual(
            [item["reference_state"] for item in candidate["legacy_sources"]],
            ["adapter_declared_available", "adapter_declared_available"],
        )
        self.assertEqual(
            source["legacy_sources"][0]["display_path"],
            "LEGACY_PARAMETER_SOURCE:/redacted/settings/parameters.json",
        )

    def test_candidate_entries_and_skipped_values_are_separate(self) -> None:
        candidate = _expected_summary()["candidate_summary"]
        entries = {entry["path"]: entry for entry in candidate["candidate_entries"]}

        self.assertEqual(
            candidate["entry_state_counts"],
            {"candidate_entry": 2, "skipped_schema_limited": 1, "skipped_untrusted": 1},
        )
        self.assertEqual(entries["qubits.qA.drive_frequency_hz"]["entry_state"], "candidate_entry")
        self.assertEqual(
            entries["qubits.qA.pi_amp"]["source_ids"], ["legacy-xlsx-parameter-table-001"]
        )
        self.assertEqual(entries["readout.qA.frequency_hz"]["entry_state"], "skipped_untrusted")
        self.assertNotIn("value", entries["readout.qA.frequency_hz"])
        self.assertEqual(
            entries["readout.qA.calibration_table"]["entry_state"],
            "skipped_schema_limited",
        )
        self.assertNotIn("value", entries["readout.qA.calibration_table"])

    def test_preview_does_not_create_parameter_state_or_write_hardware(self) -> None:
        candidate = _expected_summary()["candidate_summary"]

        self.assertEqual(candidate["classification"], "preview_ready_with_findings")
        self.assertEqual(candidate["import_acceptance"], "not_accepted")
        self.assertEqual(candidate["parameter_state_creation"], "not_performed")
        self.assertEqual(candidate["hardware_write_back"], "not_performed")
        self.assertIn(
            "Scopecat-managed parameter state creation", _expected_summary()["decisions_not_earned"]
        )


if __name__ == "__main__":
    unittest.main()
