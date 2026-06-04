from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scopecat.handoff._contracts import validate_package_primary_data_path
from scopecat.handoff._manifest_preview import preview_handoff_manifest

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = (
    ROOT
    / "tests"
    / "fixtures"
    / "prototypes"
    / "handoff"
    / "handoff_package_opener"
    / "basic_package"
    / "package"
    / "handoff-package-legacy-rabi-001"
)
HANDOFF_MODULE = ROOT / "src" / "scopecat" / "handoff"


def _load_manifest() -> dict:
    return json.loads((PACKAGE / "package-manifest.json").read_text(encoding="utf-8"))


class HandoffEngineeringPrototypeContractsTest(unittest.TestCase):
    def test_manifest_preview_is_route_local_product_state(self) -> None:
        preview = preview_handoff_manifest(_load_manifest())

        self.assertEqual(preview.package_id, "handoff-package-legacy-rabi-001")
        self.assertEqual(preview.classification, "needs_review_before_acceptance")
        self.assertEqual(preview.findings[0].code, "linked_context_not_packaged_visible_reference")
        self.assertEqual(preview.findings[0].subject_type, "linked_context")

        measurement = preview.measurements[0]
        self.assertEqual(measurement.measurement_record_id, "legacy-rabi-001")
        self.assertEqual(
            measurement.primary_data.package_path,
            "measurements/legacy-rabi-001/primary.csv",
        )
        self.assertEqual(
            measurement.preview_metadata.declared_column_names,
            ("drive_frequency", "signal"),
        )
        self.assertEqual(preview.linked_context[0].link_id, "package-legacy-001-parameter-snapshot")
        self.assertEqual(
            preview.linked_context[0].reason,
            "The accepted legacy import preserved this linked context as a reference-only fact; "
            "the package writer does not include its payload.",
        )

    def test_manifest_preview_fragments_are_copy_safe(self) -> None:
        manifest = _load_manifest()
        preview = preview_handoff_manifest(manifest)
        preview_metadata = preview.measurements[0].preview_metadata

        manifest["selected_measurements"][0]["declared_preview_metadata"]["declared_columns"][0][
            "name"
        ] = "mutated"
        preview_metadata.declared_columns[0]["name"] = "also_mutated"

        self.assertEqual(
            preview.measurements[0].preview_metadata.declared_column_names[0], "drive_frequency"
        )
        self.assertEqual(
            preview.findings[0].basis,
            "The accepted legacy import preserved this linked context as a reference-only fact; "
            "the package writer does not include its payload.",
        )

    def test_preview_contract_rejects_plot_candidates_outside_declared_columns(self) -> None:
        manifest = _load_manifest()
        measurement = manifest["selected_measurements"][0]
        measurement["declared_preview_metadata"] = copy.deepcopy(
            measurement["declared_preview_metadata"]
        )
        measurement["declared_preview_metadata"]["plot_candidates"][0]["y"] = "missing_signal"

        with self.assertRaisesRegex(ValueError, "axes must reference declared columns"):
            preview_handoff_manifest(manifest)

    def test_manifest_preview_rejects_non_packaged_primary_data(self) -> None:
        manifest = _load_manifest()
        primary = manifest["selected_measurements"][0]["primary_data"]
        primary["include_status"] = "visible_excluded"
        primary["package_state"] = "not_packaged_visible_reference"
        primary["package_path"] = None
        primary["reason"] = "Primary data was not packaged."

        with self.assertRaisesRegex(ValueError, "primary_data"):
            preview_handoff_manifest(manifest)

    def test_primary_data_path_contract_is_canonical_for_handoff_route(self) -> None:
        validate_package_primary_data_path(
            "measurements/legacy-rabi-001/primary.csv",
            measurement_record_id="legacy-rabi-001",
            owner="primary data",
        )

        with self.assertRaisesRegex(ValueError, "path must be"):
            validate_package_primary_data_path(
                "records/legacy-rabi-001/primary.csv",
                measurement_record_id="legacy-rabi-001",
                owner="primary data",
            )

    def test_handoff_prototype_no_longer_imports_implementation_candidates(self) -> None:
        self.assertTrue(HANDOFF_MODULE.is_dir())
        offenders = []
        for path in HANDOFF_MODULE.glob("*.py"):
            if "implementation_candidates" in path.read_text(encoding="utf-8"):
                offenders.append(path.name)

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
