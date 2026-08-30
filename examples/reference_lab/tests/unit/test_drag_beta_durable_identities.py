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
                "sha256:b8a8cf06d8397ea006675403886b97a3"
                "ba8978812ff44433b6acb7f46d5aa24c"
            ),
        },
        "verification_procedure": {
            "id": "reference-lab.drag-beta-verification",
            "version": "5",
            "fingerprint": (
                "sha256:d4d14993afca32099046fef9a792289f"
                "6396e5a0d418208d1b9da6b93e8e5188"
            ),
        },
        "calibration": {
            "id": "reference-lab.drag-beta-freshness",
            "version": "6",
            "fingerprint": (
                "sha256:d3b15208fe03492324d3a5bb97648879"
                "5a78ddf1942786946efb5d9f753f30cd"
            ),
            "success_policy": "published_result",
        },
        "composition": {
            "id": "reference-lab.drag-beta-cohort-composition",
            "version": "6",
            "fingerprint": (
                "sha256:79c3ff8f9c916cd0e1b63c1accb73ef7"
                "730e4715b851f9ac4b8c59698ace719d"
            ),
        },
        "automatic_publication": {
            "id": "reference-lab.drag-beta-automatic-publication",
            "version": "6",
            "fingerprint": (
                "sha256:c0dfe65dca9814942443b42495defd19"
                "23f3b22fef486d581bc5b1c7d345f12f"
            ),
            "calibration": {
                "id": "reference-lab.drag-beta-freshness",
                "version": "6",
                "fingerprint": (
                    "sha256:d3b15208fe03492324d3a5bb97648879"
                    "5a78ddf1942786946efb5d9f753f30cd"
                ),
                "success_policy": "published_result",
            },
            "composition_policy": {
                "id": "reference-lab.drag-beta-cohort-composition",
                "version": "6",
                "fingerprint": (
                    "sha256:79c3ff8f9c916cd0e1b63c1accb73ef7"
                    "730e4715b851f9ac4b8c59698ace719d"
                ),
            },
        },
    }
