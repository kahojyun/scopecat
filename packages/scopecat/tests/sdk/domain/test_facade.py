"""Public execution-domain SDK facade contracts."""

from __future__ import annotations

import scopecat as sc
import scopecat.sdk.domain as domain

_NEW_ADAPTER_VALUES = {
    "DomainFetchRequest",
    "DomainHostTransformBinding",
    "DomainHostTransformCall",
    "DomainHostTransformImplementation",
    "DomainInvocationSpec",
    "DomainMappedEntry",
    "DomainMappedResult",
    "DomainMeasurementPlan",
    "DomainMeasurementTransform",
    "DomainReconcileRequest",
    "DomainResourceClaim",
    "DomainResourceKind",
    "DomainResultValue",
    "DomainSubmitRequest",
    "DomainTargetArtifactIdentity",
    "DomainTransformInputPort",
    "DomainTransformOutputPort",
    "DomainTransformRate",
}


def test_domain_facade_exports_curated_adapter_contracts() -> None:
    assert set(domain.__all__) >= _NEW_ADAPTER_VALUES


def test_root_facade_reexports_complete_adapter_construction_values() -> None:
    expected = {
        *_NEW_ADAPTER_VALUES,
        "CorrelatedDomainFetch",
        "DomainEntryPointBinding",
        "DomainFetchCandidate",
        "DomainFetchReceipt",
        "DomainReceiptIdentity",
        "DomainReconcileReceipt",
        "DomainResultMapping",
        "DomainResultUseBinding",
        "DomainRuntime",
        "DomainSubmissionId",
        "DomainSubmitReceipt",
        "DomainTargetEntry",
        "MeasurementTransformSemanticContract",
    }

    assert expected <= set(sc.__all__)
    for name in expected:
        assert getattr(sc, name) is getattr(domain, name)
