"""Stable facade for execution-domain compilers and runtimes.

Domain packages compile typed residual semantics into target jobs, then bind
those jobs to runtime resources through the preparation context.

Core retains submission identity, effect journaling, uncertainty states, and
result-contract closure. A domain runtime implements provider effects; it does
not drive durable orchestration itself.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from scopecat.sdk.domain.compiler import (
        DomainBoundPoint,
        DomainCompilation,
        DomainCompiledJob,
        DomainCompiler,
        DomainCompileRequest,
        DomainResidualInput,
        compiled_jobs,
        validate_domain_compilation,
    )
    from scopecat.sdk.domain.context import DomainBatchContext
    from scopecat.sdk.domain.execution import PreparedDomainExecution
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
        DomainCallView,
        DomainExecutionPointView,
        DomainExecutionView,
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


_EXECUTION_EXPORTS = ("PreparedDomainExecution",)
_COMPILER_EXPORTS = (
    "DomainBoundPoint",
    "DomainCompilation",
    "DomainCompiledJob",
    "DomainCompiler",
    "DomainCompileRequest",
    "DomainResidualInput",
    "compiled_jobs",
    "validate_domain_compilation",
)
_CONTEXT_EXPORTS = ("DomainBatchContext",)
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
    "DomainCallView",
    "DomainExecutionPointView",
    "DomainExecutionView",
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
    **{name: ("scopecat.sdk.domain.compiler", name) for name in _COMPILER_EXPORTS},
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


def __getattr__(name: str) -> object:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = cast("object", getattr(import_module(module_name), attribute_name))
    globals()[name] = value
    return value


__all__ = [
    "CorrelatedDomainFetch",
    "DomainBatchContext",
    "DomainBatchView",
    "DomainBoundPoint",
    "DomainCallView",
    "DomainCompilation",
    "DomainCompileRequest",
    "DomainCompiledJob",
    "DomainCompiler",
    "DomainEntryPointBinding",
    "DomainExecutionPointView",
    "DomainExecutionView",
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
    "DomainResidualInput",
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
    "compiled_jobs",
    "validate_domain_compilation",
]
