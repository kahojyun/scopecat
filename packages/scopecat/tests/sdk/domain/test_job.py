from __future__ import annotations

import pytest

from scopecat.records.parameter import Quantity
from scopecat.sdk.domain.job import (
    DomainInvocationSpec,
    DomainResourceClaim,
    DomainResultValue,
    DomainTargetArtifactIdentity,
)


def _target() -> DomainTargetArtifactIdentity:
    return DomainTargetArtifactIdentity(
        target_id="test.target",
        compiler_id="test.compiler",
        capability_fingerprint="capabilities-v1",
        artifact_id="artifact-1",
        artifact_fingerprint="artifact-v1",
    )


def test_domain_invocation_spec_retains_only_lab_owned_declarations() -> None:
    payload = object()
    spec = DomainInvocationSpec(
        invocation_id="invoke-1",
        target=_target(),
        adapter_intent={"mode": "list"},
        payload=payload,
    )

    assert spec.target.target_id == "test.target"
    assert spec.payload is payload


def test_domain_job_values_validate_ingress() -> None:
    value = DomainResultValue("result-1", Quantity(value=1.0, unit="ratio"))
    claim = DomainResourceClaim("target", "test.target")

    assert value.result_address == "result-1"
    assert claim == DomainResourceClaim("target", "test.target")

    with pytest.raises(ValueError, match="non-empty"):
        DomainTargetArtifactIdentity("", "compiler", "cap", "artifact", "hash")
    with pytest.raises(ValueError, match="non-empty"):
        DomainInvocationSpec("", _target(), {}, payload=None)
    with pytest.raises(ValueError, match="non-empty"):
        DomainResourceClaim("target", "")
