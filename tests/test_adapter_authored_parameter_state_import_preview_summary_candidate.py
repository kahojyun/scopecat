from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from implementation_candidates.adapter_authored_parameter_state_import_preview import (
    build_adapter_authored_parameter_state_import_preview_summary,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "adapter_authored_parameter_state_import_preview"
    / "json_and_xlsx_sources"
)


def _load_input() -> dict:
    return json.loads(
        (FIXTURE / "adapter-parameter-import-manifest.json").read_text(encoding="utf-8")
    )


class AdapterAuthoredParameterStateImportPreviewSummaryCandidateTest(unittest.TestCase):
    def test_builds_expected_structured_summary(self) -> None:
        summary = build_adapter_authored_parameter_state_import_preview_summary(_load_input())
        expected = json.loads(
            (FIXTURE / "expected-adapter-parameter-import-preview-summary.json").read_text(
                encoding="utf-8"
            )
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("reference_semantics", summary)
        self.assertNotIn("source_fixture", summary)
        self.assertNotIn("status", summary)

    def test_output_does_not_alias_input_nested_objects(self) -> None:
        source = _load_input()
        summary = build_adapter_authored_parameter_state_import_preview_summary(source)

        source["adapter_parameter_import_policy"]["hardware_write_back"] = "performed"
        source["candidate_entries"][0]["value"] = {"mutated": ["value"]}
        source["candidate_parameter_state"]["lineage_hint"]["target_scope"].append("mutated")

        self.assertEqual(
            summary["adapter_parameter_import_policy"]["hardware_write_back"], "not_performed"
        )
        self.assertEqual(summary["candidate_entries"][0]["value"], 5012500000)
        self.assertEqual(
            summary["candidate_parameter_state"]["lineage_hint"]["target_scope"],
            ["sample-alpha", "qA", "default_bias"],
        )

    def test_manifest_schema_is_intentionally_versioned_as_fixture_contract(self) -> None:
        source = _load_input()
        source["manifest_schema"] = "scopecat.adapter_parameter_state_import_manifest.v1"

        with self.assertRaisesRegex(ValueError, "manifest_schema"):
            build_adapter_authored_parameter_state_import_preview_summary(source)

    def test_core_legacy_parser_claims_are_rejected(self) -> None:
        source = _load_input()
        source["adapter_parameter_import_policy"]["legacy_source_parsing"] = "performed_by_scopecat"

        with self.assertRaisesRegex(ValueError, "legacy_source_parsing"):
            build_adapter_authored_parameter_state_import_preview_summary(source)

        source = _load_input()
        source["adapter"]["parsing_authority"] = "scopecat_core"

        with self.assertRaisesRegex(ValueError, "parsing authority"):
            build_adapter_authored_parameter_state_import_preview_summary(source)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["adapter_parameter_import_policy"]["xlsx_reader"] = "available"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            build_adapter_authored_parameter_state_import_preview_summary(source)

    def test_source_display_path_must_stay_public_safe(self) -> None:
        source = _load_input()
        source["legacy_sources"][0]["display_path"] = "/Users/example/settings/parameters.json"

        with self.assertRaisesRegex(ValueError, "display path"):
            build_adapter_authored_parameter_state_import_preview_summary(source)

    def test_source_labels_must_stay_public_safe(self) -> None:
        source = _load_input()
        source["legacy_sources"][0]["external_root_label"] = "/Users/example/lab-share"

        with self.assertRaisesRegex(ValueError, "external_root_label"):
            build_adapter_authored_parameter_state_import_preview_summary(source)

    def test_duplicate_source_ids_are_rejected(self) -> None:
        source = _load_input()
        source["legacy_sources"].append(copy.deepcopy(source["legacy_sources"][0]))

        with self.assertRaisesRegex(ValueError, "duplicate source_id"):
            build_adapter_authored_parameter_state_import_preview_summary(source)

    def test_candidate_entries_must_reference_known_sources(self) -> None:
        source = _load_input()
        source["candidate_entries"][0]["source_ids"] = ["missing-source"]

        with self.assertRaisesRegex(ValueError, "missing legacy source"):
            build_adapter_authored_parameter_state_import_preview_summary(source)

    def test_candidate_entry_paths_must_not_repeat(self) -> None:
        source = _load_input()
        source["candidate_entries"][1]["path"] = "qubits.qA.drive_frequency_hz"

        with self.assertRaisesRegex(ValueError, "duplicate parameter path"):
            build_adapter_authored_parameter_state_import_preview_summary(source)

    def test_candidate_entries_must_be_trusted_scalar_values(self) -> None:
        source = _load_input()
        source["candidate_entries"][0]["trust"] = "adapter_declared_untrusted"

        with self.assertRaisesRegex(ValueError, "candidate_entry must be adapter-declared trusted"):
            build_adapter_authored_parameter_state_import_preview_summary(source)

        source = _load_input()
        source["candidate_entries"][0]["value"] = ["not", "scalar"]

        with self.assertRaisesRegex(ValueError, "value must be scalar"):
            build_adapter_authored_parameter_state_import_preview_summary(source)

    def test_skipped_entries_require_reason_and_matching_trust(self) -> None:
        source = _load_input()
        source["candidate_entries"][2]["reason"] = ""

        with self.assertRaisesRegex(ValueError, "requires reason"):
            build_adapter_authored_parameter_state_import_preview_summary(source)

        source = _load_input()
        source["candidate_entries"][3]["trust"] = "adapter_declared_trusted"

        with self.assertRaisesRegex(ValueError, "schema_limited"):
            build_adapter_authored_parameter_state_import_preview_summary(source)

    def test_blocking_adapter_finding_controls_classification(self) -> None:
        source = _load_input()
        source["adapter_findings"][1]["severity"] = "block_import"

        summary = build_adapter_authored_parameter_state_import_preview_summary(source)

        self.assertEqual(summary["classification"], "blocked_by_adapter_finding")

    def test_unavailable_source_requires_reason(self) -> None:
        source = _load_input()
        source["legacy_sources"][0]["reference_state"] = "unavailable"
        source["legacy_sources"][0]["reason"] = ""

        with self.assertRaisesRegex(ValueError, "requires reason"):
            build_adapter_authored_parameter_state_import_preview_summary(source)


if __name__ == "__main__":
    unittest.main()
