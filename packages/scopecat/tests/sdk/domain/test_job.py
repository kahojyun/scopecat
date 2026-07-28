from __future__ import annotations

from scopecat.kernel.quantity import Quantity
from scopecat.sdk.domain.job import (
    DomainInvocationSpec,
    DomainResultValue,
)


def test_domain_invocation_spec_retains_only_lab_owned_declarations() -> None:
    payload = object()
    spec = DomainInvocationSpec(
        invocation_id="invoke-1",
        target_id="test.target",
        compiler_id="test.compiler",
        capability_fingerprint="interfaces-v1",
        artifact_id="artifact-1",
        artifact_fingerprint="artifact-v1",
        target_intent={"mode": "list"},
        payload=payload,
    )

    assert spec.target_id == "test.target"
    assert spec.artifact_id == "artifact-1"
    assert spec.payload is payload


def test_domain_result_values_retain_lab_owned_addresses() -> None:
    value = DomainResultValue("result-1", Quantity(value=1.0, unit="ratio"))

    assert value.result_address == "result-1"
