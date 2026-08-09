"""Public contracts for execution-domain compilers and runtimes."""

from scopecat.sdk.domain.batch import (
    DomainBatchInputs,
    DomainBatchPartition,
    DomainBatchRequest,
    DomainCompileRequest,
)
from scopecat.sdk.domain.compiler import DomainCompiler
from scopecat.sdk.domain.execution import (
    DomainStateAddress,
    DomainStateRequirement,
    PreparedDomainExecution,
)
from scopecat.sdk.domain.job import (
    DomainInvocationSpec,
    DomainResultValue,
)
from scopecat.sdk.domain.preparation import DomainPreparationBuilder
from scopecat.sdk.domain.result_mapping import (
    DomainMappedResult,
    DomainResultBinding,
    DomainResultMapping,
)
from scopecat.sdk.domain.runtime import (
    DomainExecutionId,
    DomainExecutionReceipt,
    DomainExecutionResult,
    DomainInstrumentExecutor,
    DomainRuntime,
    DomainSetup,
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
    "DomainBatchInputs",
    "DomainBatchPartition",
    "DomainBatchRequest",
    "DomainCallView",
    "DomainCompileRequest",
    "DomainCompiler",
    "DomainExecutionId",
    "DomainExecutionReceipt",
    "DomainExecutionResult",
    "DomainInputPortView",
    "DomainInstrumentExecutor",
    "DomainInvocationSpec",
    "DomainMappedResult",
    "DomainPointRef",
    "DomainPreparationBuilder",
    "DomainProductAxisView",
    "DomainProductContractView",
    "DomainProductUseRef",
    "DomainProgramView",
    "DomainResultBinding",
    "DomainResultBindingView",
    "DomainResultMapping",
    "DomainResultPortView",
    "DomainResultValue",
    "DomainRuntime",
    "DomainSetup",
    "DomainStateAddress",
    "DomainStateRequirement",
    "PreparedDomainExecution",
]
