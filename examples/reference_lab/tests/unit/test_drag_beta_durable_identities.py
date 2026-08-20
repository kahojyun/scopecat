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
            "version": "3",
            "fingerprint": (
                "sha256:3e57593d5fb0a7e5b0ab20c26d7fb0ca"
                "e21235d6e4c9565793a19dd82af43b61"
            ),
        },
        "verification_procedure": {
            "id": "reference-lab.drag-beta-verification",
            "version": "2",
            "fingerprint": (
                "sha256:857949c1756143e99bc48e68ff2d75dd"
                "c8e2fbc1cbe895e612feaa00987ee82e"
            ),
        },
        "calibration": {
            "id": "reference-lab.drag-beta-freshness",
            "version": "3",
            "fingerprint": (
                "sha256:5d47bcdffea0e6decd2f30ae097257930"
                "e6850352cc1a7a7ffe3cf9caea48d4b"
            ),
            "success_policy": "published_result",
        },
        "composition": {
            "id": "reference-lab.drag-beta-cohort-composition",
            "version": "3",
            "fingerprint": (
                "sha256:668d488539865f3545ffc4043126061c2"
                "22c9fb06fb9e06f82b3e92710204fc8"
            ),
        },
        "automatic_publication": {
            "id": "reference-lab.drag-beta-automatic-publication",
            "version": "3",
            "fingerprint": (
                "sha256:3cee34f34058701cbb723b3e8764e244"
                "e10988999cef62696e42b54cd38f38fa"
            ),
            "calibration": {
                "id": "reference-lab.drag-beta-freshness",
                "version": "3",
                "fingerprint": (
                    "sha256:5d47bcdffea0e6decd2f30ae097257930"
                    "e6850352cc1a7a7ffe3cf9caea48d4b"
                ),
                "success_policy": "published_result",
            },
            "composition_policy": {
                "id": "reference-lab.drag-beta-cohort-composition",
                "version": "3",
                "fingerprint": (
                    "sha256:668d488539865f3545ffc4043126061c2"
                    "22c9fb06fb9e06f82b3e92710204fc8"
                ),
            },
        },
    }
