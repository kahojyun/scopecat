from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from implementation_candidates.supporting_artifact_observation import (
    observe_supporting_artifact,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "supporting_artifact_observation" / "basic_observation"
ARTIFACT_ROOT = FIXTURE


def _load_input() -> dict:
    return json.loads((FIXTURE / "artifact-observation-input.json").read_text(encoding="utf-8"))


class SupportingArtifactObservationSummaryCandidateTest(unittest.TestCase):
    def test_observes_expected_artifact_without_payload_claims(self) -> None:
        summary = observe_supporting_artifact(_load_input(), artifact_root=ARTIFACT_ROOT)
        expected = json.loads(
            (FIXTURE / "expected-artifact-observation-summary.json").read_text(encoding="utf-8")
        )["candidate_summary"]

        self.assertEqual(summary, expected)
        self.assertNotIn("payload", summary["artifact"])
        self.assertNotIn("reference_semantics", summary)

    def test_input_is_not_mutated(self) -> None:
        source = _load_input()
        original = copy.deepcopy(source)

        observe_supporting_artifact(source, artifact_root=ARTIFACT_ROOT)

        self.assertEqual(source, original)

    def test_file_observation_does_not_parse_artifact_or_sources(self) -> None:
        summary = observe_supporting_artifact(_load_input(), artifact_root=ARTIFACT_ROOT)
        policy = summary["artifact_observation_policy"]
        attention = {item["code"]: item for item in summary["attention"]}

        self.assertEqual(policy["payload_import"], "not_performed")
        self.assertEqual(policy["artifact_parsing"], "not_performed")
        self.assertEqual(policy["preview_generation"], "not_performed")
        self.assertEqual(policy["source_payload_observation"], "not_performed")
        self.assertEqual(
            attention["validity_not_claimed"]["does_not_claim"],
            "artifact_or_measurement_validity",
        )

    def test_unavailable_artifact_is_review_finding(self) -> None:
        source = _load_input()
        source["observation_request"]["artifact_path"] = "artifacts/missing.json"
        source["supporting_artifact_provenance_summary"]["artifact"]["declared_reference"][
            "value"
        ] = "artifacts/missing.json"

        summary = observe_supporting_artifact(source, artifact_root=ARTIFACT_ROOT)

        self.assertEqual(
            summary["artifact"]["classification"],
            "supporting_artifact_unavailable_for_review",
        )
        self.assertEqual(summary["observed_artifact"]["status"], "unavailable")
        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            ["supporting_artifact_unavailable"],
        )

    def test_digest_and_size_mismatches_are_review_findings(self) -> None:
        source = _load_input()
        source["observation_request"]["expected_digest"] = (
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
        source["observation_request"]["expected_size_bytes"] = 5

        summary = observe_supporting_artifact(source, artifact_root=ARTIFACT_ROOT)

        self.assertEqual(
            summary["artifact"]["classification"],
            "supporting_artifact_observed_with_file_fact_mismatch",
        )
        self.assertEqual(
            [finding["code"] for finding in summary["review_findings"]],
            ["supporting_artifact_digest_mismatch", "supporting_artifact_size_mismatch"],
        )

    def test_declared_file_facts_are_optional(self) -> None:
        source = _load_input()
        source["observation_request"]["expected_digest"] = None
        source["observation_request"]["expected_size_bytes"] = None

        summary = observe_supporting_artifact(source, artifact_root=ARTIFACT_ROOT)

        self.assertEqual(
            summary["artifact"]["classification"],
            "supporting_artifact_observed_without_declared_file_facts",
        )
        self.assertEqual(summary["review_findings"], [])
        self.assertIsNone(summary["observed_artifact"]["expected_digest"])

    def test_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["artifact_observation_policy"]["artifact_parsing"] = "performed"

        with self.assertRaisesRegex(ValueError, "artifact_parsing"):
            observe_supporting_artifact(source, artifact_root=ARTIFACT_ROOT)

        source = _load_input()
        source["artifact_observation_policy"]["measurement_validity"] = "claimed"

        with self.assertRaisesRegex(ValueError, "measurement_validity"):
            observe_supporting_artifact(source, artifact_root=ARTIFACT_ROOT)

    def test_extra_policy_claims_are_rejected(self) -> None:
        source = _load_input()
        source["artifact_observation_policy"]["artifact_reader"] = "available"

        with self.assertRaisesRegex(ValueError, "expected shape"):
            observe_supporting_artifact(source, artifact_root=ARTIFACT_ROOT)

    def test_provenance_boundary_is_enforced(self) -> None:
        source = _load_input()
        source["supporting_artifact_provenance_summary"]["artifact_provenance_policy"][
            "artifact_file_observation"
        ] = "performed"

        with self.assertRaisesRegex(ValueError, "artifact_file_observation"):
            observe_supporting_artifact(source, artifact_root=ARTIFACT_ROOT)

    def test_request_must_match_provenance_artifact(self) -> None:
        source = _load_input()
        source["observation_request"]["artifact_id"] = "other-artifact"

        with self.assertRaisesRegex(ValueError, "artifact_id"):
            observe_supporting_artifact(source, artifact_root=ARTIFACT_ROOT)

        source = _load_input()
        source["observation_request"]["artifact_path"] = "artifacts/other.json"

        with self.assertRaisesRegex(ValueError, "artifact_path"):
            observe_supporting_artifact(source, artifact_root=ARTIFACT_ROOT)

    def test_artifact_reference_must_be_observable_relative_path(self) -> None:
        source = _load_input()
        source["supporting_artifact_provenance_summary"]["artifact"]["declared_reference"][
            "reference_state"
        ] = "redacted"

        with self.assertRaisesRegex(ValueError, "declared available"):
            observe_supporting_artifact(source, artifact_root=ARTIFACT_ROOT)

        source = _load_input()
        source["supporting_artifact_provenance_summary"]["artifact"]["declared_reference"][
            "kind"
        ] = "opaque_uri"

        with self.assertRaisesRegex(ValueError, "relative artifact reference"):
            observe_supporting_artifact(source, artifact_root=ARTIFACT_ROOT)

    def test_expected_digest_must_be_sha256_prefixed(self) -> None:
        source = _load_input()
        source["observation_request"]["expected_digest"] = "abc123"

        with self.assertRaisesRegex(ValueError, "sha256-prefixed"):
            observe_supporting_artifact(source, artifact_root=ARTIFACT_ROOT)

    def test_target_symlink_is_refused_without_following(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            artifact_root = Path(temp_dir)
            target = artifact_root / "artifacts" / "rabi-fit-review.json"
            target.parent.mkdir(parents=True)
            target.symlink_to("redirected.json")

            with self.assertRaisesRegex(ValueError, "target is a symlink"):
                observe_supporting_artifact(source, artifact_root=artifact_root)

            self.assertTrue(target.is_symlink())
            self.assertFalse((target.parent / "redirected.json").exists())

    def test_parent_symlink_is_refused_without_following(self) -> None:
        source = _load_input()
        with tempfile.TemporaryDirectory() as temp_dir:
            artifact_root = Path(temp_dir)
            outside = artifact_root / "outside"
            outside.mkdir()
            (artifact_root / "artifacts").symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent is a symlink"):
                observe_supporting_artifact(source, artifact_root=artifact_root)

            self.assertTrue((artifact_root / "artifacts").is_symlink())


if __name__ == "__main__":
    unittest.main()
