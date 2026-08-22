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
            "version": "4",
            "fingerprint": (
                "sha256:f905025d6f798d6703957437fa7dee483"
                "58578597882903a584d95bb81347de5"
            ),
        },
        "verification_procedure": {
            "id": "reference-lab.drag-beta-verification",
            "version": "3",
            "fingerprint": (
                "sha256:bb7b36fe9991e872cbfdecae1f5eb64e"
                "5ff4d825a85cf0289c1b281fecefdd4d"
            ),
        },
        "calibration": {
            "id": "reference-lab.drag-beta-freshness",
            "version": "4",
            "fingerprint": (
                "sha256:2a548b0d1bffb72ca68aef188a3fa8f4"
                "f7a771112878403612e556faf78b4077"
            ),
            "success_policy": "published_result",
        },
        "composition": {
            "id": "reference-lab.drag-beta-cohort-composition",
            "version": "4",
            "fingerprint": (
                "sha256:e5eaa7fffca617c470bac8683c363ab97"
                "48906e79036357b29b413a41a76730f"
            ),
        },
        "automatic_publication": {
            "id": "reference-lab.drag-beta-automatic-publication",
            "version": "4",
            "fingerprint": (
                "sha256:0fb03eaaf63c928bcc13f0fa8db864e7"
                "eea3ff26b3eb8ffc307ea54f8475d3ce"
            ),
            "calibration": {
                "id": "reference-lab.drag-beta-freshness",
                "version": "4",
                "fingerprint": (
                    "sha256:2a548b0d1bffb72ca68aef188a3fa8f4"
                    "f7a771112878403612e556faf78b4077"
                ),
                "success_policy": "published_result",
            },
            "composition_policy": {
                "id": "reference-lab.drag-beta-cohort-composition",
                "version": "4",
                "fingerprint": (
                    "sha256:e5eaa7fffca617c470bac8683c363ab97"
                    "48906e79036357b29b413a41a76730f"
                ),
            },
        },
    }
