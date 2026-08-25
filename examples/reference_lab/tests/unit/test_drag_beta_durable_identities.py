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
            "version": "5",
            "fingerprint": (
                "sha256:97069018e3dae9f04488de42de367b54"
                "b8e6e7c0f4a59413c7258c074cf46289"
            ),
        },
        "verification_procedure": {
            "id": "reference-lab.drag-beta-verification",
            "version": "4",
            "fingerprint": (
                "sha256:1a44b6b281f4ae71f3687daad99a99ab"
                "5ee986efc5e7fb6a38d0ffee40e929b5"
            ),
        },
        "calibration": {
            "id": "reference-lab.drag-beta-freshness",
            "version": "5",
            "fingerprint": (
                "sha256:20a70c50c9f005596c61f95f29eabbc8"
                "5b3fe5ec5913ba82215e37825d68d101"
            ),
            "success_policy": "published_result",
        },
        "composition": {
            "id": "reference-lab.drag-beta-cohort-composition",
            "version": "5",
            "fingerprint": (
                "sha256:2e7d249ef76840dad0c1d4efd5bd72bf"
                "3979544ae3ec9dc61edd168ac230bbd2"
            ),
        },
        "automatic_publication": {
            "id": "reference-lab.drag-beta-automatic-publication",
            "version": "5",
            "fingerprint": (
                "sha256:00a96d3ba0d7aac81e595f7679a4b2d9"
                "e87bb8977e2e9608f78483ad9c10430e"
            ),
            "calibration": {
                "id": "reference-lab.drag-beta-freshness",
                "version": "5",
                "fingerprint": (
                    "sha256:20a70c50c9f005596c61f95f29eabbc8"
                    "5b3fe5ec5913ba82215e37825d68d101"
                ),
                "success_policy": "published_result",
            },
            "composition_policy": {
                "id": "reference-lab.drag-beta-cohort-composition",
                "version": "5",
                "fingerprint": (
                    "sha256:2e7d249ef76840dad0c1d4efd5bd72bf"
                    "3979544ae3ec9dc61edd168ac230bbd2"
                ),
            },
        },
    }
