"""Public contracts for execution-domain compilers and runtimes."""

from scopecat.sdk.domain.compiler import (
    DomainBatchInputs,
    DomainBatchRequest,
    DomainCompiler,
    DomainResolvedInputs,
)
from scopecat.sdk.domain.execution import PreparedDomainExecution
from scopecat.sdk.domain.job import (
    DomainInvocationSpec,
    DomainResultValue,
    DomainTargetArtifactIdentity,
)
from scopecat.sdk.domain.preparation import DomainPreparationBuilder
from scopecat.sdk.domain.result_mapping import (
    DomainMappedResult,
    DomainResultBinding,
    DomainResultMapping,
)
from scopecat.sdk.domain.runtime import (
    CorrelatedDomainFetch,
    DomainFetchCandidate,
    DomainFetchReceipt,
    DomainFetchRequest,
    DomainRuntime,
    DomainSubmissionId,
    DomainSubmitReceipt,
    DomainSubmitRequest,
)
from scopecat.sdk.domain.view import (
    DomainCallView,
    DomainInputPortView,
    DomainPointRef,
    DomainProductAxisView,
    DomainProductContractView,
    DomainProductUseRef,
    DomainProgramView,
    DomainResultBindingView,
    DomainResultPortView,
)

__all__ = [
    "CorrelatedDomainFetch",
    "DomainBatchInputs",
    "DomainBatchRequest",
    "DomainCallView",
    "DomainCompiler",
    "DomainFetchCandidate",
    "DomainFetchReceipt",
    "DomainFetchRequest",
    "DomainInputPortView",
    "DomainInvocationSpec",
    "DomainMappedResult",
    "DomainPointRef",
    "DomainPreparationBuilder",
    "DomainProductAxisView",
    "DomainProductContractView",
    "DomainProductUseRef",
    "DomainProgramView",
    "DomainResolvedInputs",
    "DomainResultBinding",
    "DomainResultBindingView",
    "DomainResultMapping",
    "DomainResultPortView",
    "DomainResultValue",
    "DomainRuntime",
    "DomainSubmissionId",
    "DomainSubmitReceipt",
    "DomainSubmitRequest",
    "DomainTargetArtifactIdentity",
    "PreparedDomainExecution",
]
