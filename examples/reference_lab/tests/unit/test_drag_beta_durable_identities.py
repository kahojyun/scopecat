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
            "version": "2",
            "fingerprint": (
                "sha256:07b086321f339d3de44a115087b5adc8"
                "a9fc7bd93dc8daaebf59ab1f0db145c5"
            ),
        },
        "verification_procedure": {
            "id": "reference-lab.drag-beta-verification",
            "version": "1",
            "fingerprint": (
                "sha256:21b242d83bb71f4d604aa554628e238b"
                "2c4c3c0086d021ae31a017b2a264eef2"
            ),
        },
        "calibration": {
            "id": "reference-lab.drag-beta-freshness",
            "version": "2",
            "fingerprint": (
                "sha256:01da6f92abbb7ad05e64648ca0ea52c7"
                "8c4ca9ddef0b41d2bb859179a58e6991"
            ),
            "success_policy": "published_result",
        },
        "composition": {
            "id": "reference-lab.drag-beta-cohort-composition",
            "version": "2",
            "fingerprint": (
                "sha256:4e52b0457af08b13edb26d886e275e1b"
                "e454b08c479155d45fbccf6570a7987a"
            ),
        },
        "automatic_publication": {
            "id": "reference-lab.drag-beta-automatic-publication",
            "version": "2",
            "fingerprint": (
                "sha256:ca3532b7be554211adc721c3ea3041dc"
                "bc2e5638b682390236f2e807e61bb319"
            ),
            "calibration": {
                "id": "reference-lab.drag-beta-freshness",
                "version": "2",
                "fingerprint": (
                    "sha256:01da6f92abbb7ad05e64648ca0ea52c7"
                    "8c4ca9ddef0b41d2bb859179a58e6991"
                ),
                "success_policy": "published_result",
            },
            "composition_policy": {
                "id": "reference-lab.drag-beta-cohort-composition",
                "version": "2",
                "fingerprint": (
                    "sha256:4e52b0457af08b13edb26d886e275e1b"
                    "e454b08c479155d45fbccf6570a7987a"
                ),
            },
        },
    }
