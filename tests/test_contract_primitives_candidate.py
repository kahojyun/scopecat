from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from implementation_candidates.contract_primitives import (
    PUBLIC_IDENTIFIER_MAX_LENGTH,
    relative_path_parts,
    validate_package_primary_data_path,
    validate_package_root_outside_storage,
    validate_positive_integer,
    validate_public_identifier,
    validate_redacted_display_ref,
    validate_relative_path,
    validate_sha256_digest,
    validate_strict_child_path,
    validate_text,
    validate_unique_reference_targets,
)


class ContractPrimitivesCandidateTest(unittest.TestCase):
    def test_public_identifier_accepts_tight_managed_segments(self) -> None:
        self.assertEqual(
            validate_public_identifier("handoff-package-legacy-rabi-001", "package_id"),
            "handoff-package-legacy-rabi-001",
        )
        self.assertEqual(
            validate_public_identifier("drive_frequency", "column name"), "drive_frequency"
        )

    def test_public_identifier_rejects_path_shaped_or_oversized_values(self) -> None:
        invalid_values = [
            "",
            ".",
            "/Users/lab/private",
            "records/legacy-rabi-001",
            "legacy-rabi-001\nsecret",
            "a" * (PUBLIC_IDENTIFIER_MAX_LENGTH + 1),
            {"id": "legacy-rabi-001"},
        ]
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "public-safe identifier"):
                    validate_public_identifier(value, "package_id")

    def test_relative_paths_reject_absolute_traversal_and_empty_segments(self) -> None:
        self.assertEqual(
            relative_path_parts("records/legacy-rabi-001/primary.csv"),
            ("records", "legacy-rabi-001", "primary.csv"),
        )
        for value in (
            "/private/package.csv",
            "records/../primary.csv",
            "records//primary.csv",
            r"records\primary.csv",
            "C:/records/primary.csv",
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "path must be relative"):
                    validate_relative_path(value, "storage source")

    def test_strict_child_path_requires_nested_child(self) -> None:
        self.assertEqual(
            validate_strict_child_path(
                "measurements/legacy-rabi-001/primary.csv",
                "measurements/legacy-rabi-001",
                "package primary",
            ),
            "measurements/legacy-rabi-001/primary.csv",
        )
        with self.assertRaisesRegex(ValueError, "must stay under measurements"):
            validate_strict_child_path("context/primary.csv", "measurements", "package primary")

    def test_package_primary_data_path_is_exact_generated_shape(self) -> None:
        self.assertEqual(
            validate_package_primary_data_path(
                "measurements/legacy-rabi-001/primary.csv",
                measurement_record_id="legacy-rabi-001",
                owner="handoff package primary_data",
            ),
            "measurements/legacy-rabi-001/primary.csv",
        )
        for value in (
            "measurements/legacy-rabi-001/raw/primary.csv",
            "measurements/other-record/primary.csv",
            "context/legacy-rabi-001/primary.csv",
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "primary_data path"):
                    validate_package_primary_data_path(
                        value,
                        measurement_record_id="legacy-rabi-001",
                        owner="handoff package primary_data",
                    )

    def test_reference_targets_must_be_ordered_unique_selected_identifiers(self) -> None:
        targets = validate_unique_reference_targets(
            ["legacy-rabi-001", "legacy-rabi-002"],
            selected_ids={"legacy-rabi-001", "legacy-rabi-002"},
            owner="handoff package linked context",
        )
        self.assertEqual(targets, ["legacy-rabi-001", "legacy-rabi-002"])

        cases = [
            ({"legacy-rabi-001"}, "targets must be a list"),
            (["legacy-rabi-001", "legacy-rabi-001"], "targets must be unique"),
            ([{"id": "legacy-rabi-001"}], "measurement target"),
            (["legacy-rabi-999"], "must reference selected measurements"),
        ]
        for value, pattern in cases:
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, pattern):
                    validate_unique_reference_targets(
                        value,
                        selected_ids={"legacy-rabi-001"},
                        owner="handoff package linked context",
                    )

    def test_redacted_display_refs_and_hashes_are_contract_shaped(self) -> None:
        self.assertEqual(
            validate_redacted_display_ref(
                "HANDOFF_PACKAGE:/redacted/legacy-rabi-001",
                "display_path",
                prefix="HANDOFF_PACKAGE:",
            ),
            "HANDOFF_PACKAGE:/redacted/legacy-rabi-001",
        )
        with self.assertRaisesRegex(ValueError, "redacted display reference"):
            validate_redacted_display_ref(
                "HANDOFF_PACKAGE:/Users/lab/private/package",
                "display_path",
                prefix="HANDOFF_PACKAGE:",
            )
        for value in (
            "HANDOFF_PACKAGE:/redacted/C:/lab-package",
            "HANDOFF_PACKAGE:/redacted/private",
            "HANDOFF_PACKAGE:/redacted/legacy/rabi-001",
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "redacted display reference"):
                    validate_redacted_display_ref(
                        value,
                        "display_path",
                        prefix="HANDOFF_PACKAGE:",
                    )

        digest = "sha256:" + "a" * 64
        self.assertEqual(validate_sha256_digest(digest, "digest"), digest)
        with self.assertRaisesRegex(ValueError, "sha256-prefixed"):
            validate_sha256_digest("a" * 64, "digest")

    def test_text_and_positive_integer_are_not_bool_or_structured_values(self) -> None:
        self.assertEqual(validate_text("Reviewed free text", "label"), "Reviewed free text")
        self.assertEqual(validate_positive_integer(1, "size"), 1)
        for value in (0, -1, True, "1"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "must be positive"):
                    validate_positive_integer(value, "size")

    def test_package_root_must_be_outside_storage_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir) / "storage"
            storage_root.mkdir()
            package_root = Path(temp_dir) / "packages"
            package_root.mkdir()
            validate_package_root_outside_storage(
                storage_root,
                package_root,
                owner="handoff package writer",
            )

            with self.assertRaisesRegex(ValueError, "outside measurement storage"):
                validate_package_root_outside_storage(
                    storage_root,
                    storage_root,
                    owner="handoff package writer",
                )

            nested_package_root = storage_root / "packages"
            nested_package_root.mkdir()
            with self.assertRaisesRegex(ValueError, "outside measurement storage"):
                validate_package_root_outside_storage(
                    storage_root,
                    nested_package_root,
                    owner="handoff package writer",
                )


if __name__ == "__main__":
    unittest.main()
