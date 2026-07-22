"""Public execution-domain SDK facade contracts."""

from __future__ import annotations

import scopecat as sc
import scopecat.sdk.domain as domain

_NEW_ADAPTER_VALUES = {
    "DomainFetchRequest",
    "DomainCompiledInputs",
    "DomainHostTransformBinding",
    "DomainHostTransformCall",
    "DomainHostTransformImplementation",
    "DomainInvocationSpec",
    "DomainMappedResult",
    "DomainMeasurementTransform",
    "DomainResultValue",
    "DomainSubmitRequest",
    "DomainTargetArtifactIdentity",
    "DomainTransformInputPort",
    "DomainTransformOutputPort",
}


def test_domain_facade_exports_curated_adapter_contracts() -> None:
    assert set(domain.__all__) >= _NEW_ADAPTER_VALUES
    assert {
        "DomainIterationLayout",
        "DomainLiteral",
        "DomainPointAffine",
        "DomainPointAxis",
    } <= set(domain.__all__)
    assert "DomainInputExpression" not in domain.__all__


def test_root_facade_does_not_duplicate_the_adapter_sdk() -> None:
    assert not (_NEW_ADAPTER_VALUES & set(sc.__all__))
    assert "DomainCompiler" not in sc.__all__
    assert "DomainRuntime" not in sc.__all__
    assert "PreparedDomainExecution" not in sc.__all__
