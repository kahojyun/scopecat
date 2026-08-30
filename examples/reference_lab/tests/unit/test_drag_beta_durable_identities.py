"""Golden identities for the reference calibration's durable capabilities."""

from __future__ import annotations

from reference_lab.workflows.drag_beta_automatic_publication import (
    DRAG_BETA_PUBLICATION_POLICY_REF,
)
from reference_lab.workflows.drag_beta_freshness import (
    drag_beta_freshness_calibration,
)
from reference_lab.workflows.drag_beta_procedure import (
    drag_beta_calibration_procedure,
    drag_beta_verification_procedure,
)
from reference_lab.workflows.drag_beta_publication import (
    DRAG_BETA_COMPOSITION_POLICY_REF,
)


def test_drag_beta_durable_capability_manifest_changes_explicitly() -> None:
    """Require an intentional version-and-fingerprint review for code changes."""

    assert {
        "manual_procedure": drag_beta_calibration_procedure.ref.model_dump(mode="json"),
        "verification_procedure": drag_beta_verification_procedure.ref.model_dump(
            mode="json"
        ),
        "calibration": drag_beta_freshness_calibration.ref.model_dump(mode="json"),
        "composition": DRAG_BETA_COMPOSITION_POLICY_REF.model_dump(mode="json"),
        "automatic_publication": DRAG_BETA_PUBLICATION_POLICY_REF.model_dump(
            mode="json"
        ),
    } == {
        "manual_procedure": {
            "id": "reference-lab.drag-beta-calibration",
            "version": "6",
            "fingerprint": (
                "sha256:e60f75e173c92634f3dde9e271e40c00"
                "bebf57f512d439b70e0d4ec197c3b3f2"
            ),
        },
        "verification_procedure": {
            "id": "reference-lab.drag-beta-verification",
            "version": "5",
            "fingerprint": (
                "sha256:38e0a7091688d9390db528144e256406"
                "556823b6c7faed19cb7e3c0a0d90e183"
            ),
        },
        "calibration": {
            "id": "reference-lab.drag-beta-freshness",
            "version": "6",
            "fingerprint": (
                "sha256:3b719dfb79df8a3fd20146ad4dd61ed3"
                "88874d1d3fa46e229dd3248d5d2edd1e"
            ),
            "success_policy": "published_result",
        },
        "composition": {
            "id": "reference-lab.drag-beta-cohort-composition",
            "version": "6",
            "fingerprint": (
                "sha256:38a51475ddb301e66ace3fa1d1dabdbd"
                "824dc863ba1032c7bd8fa8d1e96a78b2"
            ),
        },
        "automatic_publication": {
            "id": "reference-lab.drag-beta-automatic-publication",
            "version": "6",
            "fingerprint": (
                "sha256:4ba4edbd70e5a64e706b24b1b206b8e"
                "a29b3e6b1af25aab1edcbec8d1ab548ac"
            ),
            "calibration": {
                "id": "reference-lab.drag-beta-freshness",
                "version": "6",
                "fingerprint": (
                    "sha256:3b719dfb79df8a3fd20146ad4dd61ed3"
                    "88874d1d3fa46e229dd3248d5d2edd1e"
                ),
                "success_policy": "published_result",
            },
            "composition_policy": {
                "id": "reference-lab.drag-beta-cohort-composition",
                "version": "6",
                "fingerprint": (
                    "sha256:38a51475ddb301e66ace3fa1d1dabdbd"
                    "824dc863ba1032c7bd8fa8d1e96a78b2"
                ),
            },
        },
    }
