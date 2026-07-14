"""Stable facade for execution-domain adapters and runtimes.

Adapter packages should import their supported protocol surface from this
module. Compiler-owned linked-plan types do not cross this facade. Adapters
first offer support for a core-owned batch view, then prepare only the exact
context selected by the backend. Context-scoped point and product references
prevent adapters from manufacturing graph identities or choosing a convenient
result subset.

Core retains submission identity, effect journaling, uncertainty states, and
result-contract closure. A domain runtime implements provider effects; it does
not drive durable orchestration itself.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scopecat.sdk.domain.context import DomainBatchContext, DomainExecutionOffer
    from scopecat.sdk.domain.execution import (
        DomainExecutionAdapter,
        PreparedDomainExecution,
    )
    from scopecat.sdk.domain.job import (
        DomainInvocationSpec,
        DomainResourceClaim,
        DomainResourceKind,
        DomainResultValue,
        DomainTargetArtifactIdentity,
    )
    from scopecat.sdk.domain.measurements import (
        DomainHostTransformBinding,
        DomainHostTransformCall,
        DomainHostTransformImplementation,
        DomainTransformRate,
        MeasurementTransformSemanticContract,
    )
    from scopecat.sdk.domain.preparation import (
        DomainEntryPointBinding,
        DomainMappedEntry,
        DomainMappedResult,
        DomainMeasurementPlan,
        DomainPreparationBuilder,
        DomainResultMapping,
        DomainResultUseBinding,
        DomainTargetEntry,
    )
    from scopecat.sdk.domain.runtime import (
        CorrelatedDomainFetch,
        DomainFetchCandidate,
        DomainFetchReceipt,
        DomainFetchRequest,
        DomainReceiptIdentity,
        DomainReconcileReceipt,
        DomainReconcileRequest,
        DomainRuntime,
        DomainSubmissionId,
        DomainSubmitReceipt,
        DomainSubmitRequest,
    )
    from scopecat.sdk.domain.view import (
        DomainBatchView,
        DomainCallPointView,
        DomainCallView,
        DomainInputPortView,
        DomainMeasurementTransform,
        DomainPointRef,
        DomainProductAxisView,
        DomainProductContractView,
        DomainProductKind,
        DomainProductUseRef,
        DomainProgramView,
        DomainResultBindingView,
        DomainResultPortView,
        DomainTransformInputPort,
        DomainTransformOutputPort,
    )


_EXECUTION_EXPORTS = (
    "DomainExecutionAdapter",
    "PreparedDomainExecution",
)
_CONTEXT_EXPORTS = ("DomainBatchContext", "DomainExecutionOffer")
_JOB_EXPORTS = (
    "DomainInvocationSpec",
    "DomainResourceClaim",
    "DomainResourceKind",
    "DomainResultValue",
    "DomainTargetArtifactIdentity",
)
_MEASUREMENT_EXPORTS = (
    "DomainHostTransformBinding",
    "DomainHostTransformCall",
    "DomainHostTransformImplementation",
    "DomainTransformRate",
    "MeasurementTransformSemanticContract",
)
_PREPARATION_EXPORTS = (
    "DomainEntryPointBinding",
    "DomainMappedEntry",
    "DomainMappedResult",
    "DomainMeasurementPlan",
    "DomainPreparationBuilder",
    "DomainResultMapping",
    "DomainResultUseBinding",
    "DomainTargetEntry",
)
_RUNTIME_EXPORTS = (
    "CorrelatedDomainFetch",
    "DomainFetchCandidate",
    "DomainFetchReceipt",
    "DomainFetchRequest",
    "DomainReceiptIdentity",
    "DomainReconcileReceipt",
    "DomainReconcileRequest",
    "DomainRuntime",
    "DomainSubmissionId",
    "DomainSubmitReceipt",
    "DomainSubmitRequest",
)
_VIEW_EXPORTS = (
    "DomainBatchView",
    "DomainCallPointView",
    "DomainCallView",
    "DomainInputPortView",
    "DomainMeasurementTransform",
    "DomainProductAxisView",
    "DomainProductContractView",
    "DomainProductKind",
    "DomainPointRef",
    "DomainProductUseRef",
    "DomainProgramView",
    "DomainResultBindingView",
    "DomainResultPortView",
    "DomainTransformInputPort",
    "DomainTransformOutputPort",
)

_EXPORTS = {
    **{name: ("scopecat.sdk.domain.execution", name) for name in _EXECUTION_EXPORTS},
    **{name: ("scopecat.sdk.domain.context", name) for name in _CONTEXT_EXPORTS},
    **{name: ("scopecat.sdk.domain.job", name) for name in _JOB_EXPORTS},
    **{
        name: ("scopecat.sdk.domain.measurements", name)
        for name in _MEASUREMENT_EXPORTS
    },
    **{
        name: ("scopecat.sdk.domain.preparation", name) for name in _PREPARATION_EXPORTS
    },
    **{name: ("scopecat.sdk.domain.runtime", name) for name in _RUNTIME_EXPORTS},
    **{name: ("scopecat.sdk.domain.view", name) for name in _VIEW_EXPORTS},
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


__all__ = [
    "CorrelatedDomainFetch",
    "DomainBatchContext",
    "DomainBatchView",
    "DomainCallPointView",
    "DomainCallView",
    "DomainEntryPointBinding",
    "DomainExecutionAdapter",
    "DomainExecutionOffer",
    "DomainFetchCandidate",
    "DomainFetchReceipt",
    "DomainFetchRequest",
    "DomainHostTransformBinding",
    "DomainHostTransformCall",
    "DomainHostTransformImplementation",
    "DomainInputPortView",
    "DomainInvocationSpec",
    "DomainMappedEntry",
    "DomainMappedResult",
    "DomainMeasurementPlan",
    "DomainMeasurementTransform",
    "DomainPointRef",
    "DomainPreparationBuilder",
    "DomainProductAxisView",
    "DomainProductContractView",
    "DomainProductKind",
    "DomainProductUseRef",
    "DomainProgramView",
    "DomainReceiptIdentity",
    "DomainReconcileReceipt",
    "DomainReconcileRequest",
    "DomainResourceClaim",
    "DomainResourceKind",
    "DomainResultBindingView",
    "DomainResultMapping",
    "DomainResultPortView",
    "DomainResultUseBinding",
    "DomainResultValue",
    "DomainRuntime",
    "DomainSubmissionId",
    "DomainSubmitReceipt",
    "DomainSubmitRequest",
    "DomainTargetArtifactIdentity",
    "DomainTargetEntry",
    "DomainTransformInputPort",
    "DomainTransformOutputPort",
    "DomainTransformRate",
    "MeasurementTransformSemanticContract",
    "PreparedDomainExecution",
]
