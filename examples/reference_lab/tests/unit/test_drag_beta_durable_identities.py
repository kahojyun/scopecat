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
                "sha256:0e1da1de6806bdeb091c849bd9b02e62"
                "adbf1ec5e1e92a8b4b1bbd8235e435dc"
            ),
        },
        "verification_procedure": {
            "id": "reference-lab.drag-beta-verification",
            "version": "1",
            "fingerprint": (
                "sha256:fc42a5868472f4164f5be4d51eb7c398"
                "b9d6d910d3aba8d8cff3a8d70e6551f3"
            ),
        },
        "calibration": {
            "id": "reference-lab.drag-beta-freshness",
            "version": "2",
            "fingerprint": (
                "sha256:e2c85b91a001664a784f44502a03841a"
                "9ffd8c7b01c90ee1d6d254c904f42cdc"
            ),
            "success_policy": "published_result",
        },
        "composition": {
            "id": "reference-lab.drag-beta-cohort-composition",
            "version": "2",
            "fingerprint": (
                "sha256:936255bcb4dc933bebbde7cd52805ddf"
                "4d300f1124b5c5e8be81af007a598959"
            ),
        },
        "automatic_publication": {
            "id": "reference-lab.drag-beta-automatic-publication",
            "version": "2",
            "fingerprint": (
                "sha256:5bb79a2da22eca33c26c30ff49bc5c7"
                "f746d5a04f0f073dac0e2ecb7aeb1a085"
            ),
            "calibration": {
                "id": "reference-lab.drag-beta-freshness",
                "version": "2",
                "fingerprint": (
                    "sha256:e2c85b91a001664a784f44502a03841a"
                    "9ffd8c7b01c90ee1d6d254c904f42cdc"
                ),
                "success_policy": "published_result",
            },
            "composition_policy": {
                "id": "reference-lab.drag-beta-cohort-composition",
                "version": "2",
                "fingerprint": (
                    "sha256:936255bcb4dc933bebbde7cd52805ddf"
                    "4d300f1124b5c5e8be81af007a598959"
                ),
            },
        },
    }
