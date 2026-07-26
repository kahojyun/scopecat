"""Public contracts for execution-domain compilers and runtimes."""

from scopecat.sdk.domain.compiler import (
    DomainCompilation,
    DomainCompiledInputs,
    DomainCompiledJob,
    DomainCompiler,
    DomainCompileRequest,
    DomainInput,
    DomainInputBinder,
    DomainResolvedInputs,
    compiled_jobs,
    validate_domain_compilation,
)
from scopecat.sdk.domain.context import DomainBatchContext
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
    DomainExecutionPointView,
    DomainExecutionView,
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
    "DomainBatchContext",
    "DomainCallView",
    "DomainCompilation",
    "DomainCompileRequest",
    "DomainCompiledInputs",
    "DomainCompiledJob",
    "DomainCompiler",
    "DomainExecutionPointView",
    "DomainExecutionView",
    "DomainFetchCandidate",
    "DomainFetchReceipt",
    "DomainFetchRequest",
    "DomainInput",
    "DomainInputBinder",
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
    "compiled_jobs",
    "validate_domain_compilation",
]
