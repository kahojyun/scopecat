"""Public execution-domain SDK facade contracts."""

from __future__ import annotations

import inspect
from collections.abc import Iterable

import scopecat as sc
import scopecat.sdk.domain as domain
import scopecat.sdk.domain.execution as domain_execution
import scopecat.sdk.domain.runtime as domain_runtime

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

_CORE_OR_NATIVE_NAMES = {
    "AbsentDomainSubmission",
    "AdapterEntryResults",
    "ClosedDomainInvocation",
    "ClosedDomainResultMapping",
    "DomainInvocationIntent",
    "DomainSubmissionResolution",
    "EntryPointBinding",
    "KnownDomainSubmission",
    "LinkedPlan",
    "MaterializedLinkedPoints",
    "PendingDomainFetch",
    "ResultUseBinding",
    "UncertainDomainSubmission",
    "domain_receipt_identity",
    "execute_domain_invocation",
    "fetch_domain_invocation",
    "plan_domain_submission",
    "plan_domain_submission_retry",
    "project_domain_run_plan_batch",
    "project_domain_run_plan_batch_internal",
    "reconcile_domain_invocation",
    "seal_domain_result_mapping",
    "submit_domain_invocation",
}


def test_domain_facade_exports_curated_adapter_contracts() -> None:
    assert domain.DomainExecutionAdapter.__module__ == ("scopecat.sdk.domain.execution")
    assert domain.DomainRuntime.__module__ == "scopecat.sdk.domain.runtime"
    assert domain.DomainBatchContext.__module__ == "scopecat.sdk.domain.context"
    assert domain.DomainExecutionOffer.__module__ == "scopecat.sdk.domain.context"
    assert domain.DomainPreparationBuilder.__module__ == (
        "scopecat.sdk.domain.preparation"
    )
    assert domain.DomainInvocationSpec.__module__ == "scopecat.sdk.domain.job"
    assert domain.DomainMeasurementTransform.__module__ == ("scopecat.sdk.domain.view")
    assert domain.DomainSubmitRequest.__module__ == "scopecat.sdk.domain.runtime"

    assert set(domain.__all__) >= _NEW_ADAPTER_VALUES
    assert _CORE_OR_NATIVE_NAMES.isdisjoint(domain.__all__)


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


def test_domain_facade_rejects_core_or_native_escape_hatches() -> None:
    for name in _CORE_OR_NATIVE_NAMES:
        assert not hasattr(domain, name)


def test_leaf_modules_do_not_advertise_core_orchestration() -> None:
    assert _CORE_OR_NATIVE_NAMES.isdisjoint(domain_runtime.__all__)
    assert _CORE_OR_NATIVE_NAMES.isdisjoint(domain_execution.__all__)


def test_domain_facade_public_type_graph_has_no_compiler_or_closed_ir() -> None:
    rendered = "\n".join(
        _render_public_api(getattr(domain, name)) for name in domain.__all__
    )

    forbidden = (
        "AbsentDomainSubmission",
        "DomainInvocationIntent",
        "DomainSubmissionResolution",
        "KnownDomainSubmission",
        "PendingDomainFetch",
        "UncertainDomainSubmission",
        "scopecat.compiler",
        "scopecat.sdk.domain.invocation",
        "BoundDomain",
        "BoundHost",
        "BoundMeasurement",
        "ClosedDomain",
        "MaterializedLinked",
    )
    assert not any(fragment in rendered for fragment in forbidden)


def _render_public_api(value: object) -> str:
    rendered = [repr(value), getattr(value, "__module__", "")]
    rendered.extend(_render_callable(value))
    if inspect.isclass(value):
        rendered.extend(
            repr(annotation)
            for name, annotation in getattr(value, "__annotations__", {}).items()
            if not name.startswith("_")
        )
        for name, member in vars(value).items():
            if name.startswith("_"):
                continue
            candidate = member.fget if isinstance(member, property) else member
            if candidate is not None and callable(candidate):
                rendered.extend(_render_callable(candidate))
    return "\n".join(rendered)


def _render_callable(value: object) -> Iterable[str]:
    if not callable(value):
        return ()
    try:
        signature = str(inspect.signature(value))
    except (TypeError, ValueError):
        signature = ""
    annotations = (
        {} if inspect.isclass(value) else getattr(value, "__annotations__", {})
    )
    return (signature, *(repr(annotation) for annotation in annotations.values()))
