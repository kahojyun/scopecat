# pyright: reportUnusedImport=false, reportUnsupportedDunderAll=false
"""Lazy public facade for execution-domain compilers and runtimes."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from scopecat.sdk.domain.batch import (
        DomainBatchInputs,
        DomainBatchRequest,
    )
    from scopecat.sdk.domain.compiler import DomainCompiler
    from scopecat.sdk.domain.execution import (
        DomainStateAddress,
        DomainStateRequirement,
        PreparedDomainExecution,
    )
    from scopecat.sdk.domain.inspection import (
        CompiledArtifactInspection,
        CompiledInspectionBounds,
        CompiledInspectionFact,
        CompiledPointInspection,
        CompiledWaveformInspection,
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

_BATCH_EXPORTS = (
    "DomainBatchInputs",
    "DomainBatchRequest",
)
_EXECUTION_EXPORTS = (
    "DomainStateAddress",
    "DomainStateRequirement",
    "PreparedDomainExecution",
)
_JOB_EXPORTS = (
    "DomainInvocationSpec",
    "DomainResultValue",
)
_INSPECTION_EXPORTS = (
    "CompiledArtifactInspection",
    "CompiledInspectionBounds",
    "CompiledInspectionFact",
    "CompiledPointInspection",
    "CompiledWaveformInspection",
)
_RESULT_MAPPING_EXPORTS = (
    "DomainMappedResult",
    "DomainResultBinding",
    "DomainResultMapping",
)
_RUNTIME_EXPORTS = (
    "DomainExecutionId",
    "DomainExecutionReceipt",
    "DomainExecutionResult",
    "DomainInstrumentExecutor",
    "DomainRuntime",
    "DomainSetup",
)
_VIEW_EXPORTS = (
    "DomainCallView",
    "DomainInputPortView",
    "DomainPointRef",
    "DomainProductAxisView",
    "DomainProductContractView",
    "DomainProductUseRef",
    "DomainProgramView",
    "DomainResultBindingView",
    "DomainResultPortView",
)
_EXPORTS = {
    **{name: ("scopecat.sdk.domain.batch", name) for name in _BATCH_EXPORTS},
    **{name: ("scopecat.sdk.domain.execution", name) for name in _EXECUTION_EXPORTS},
    **{name: ("scopecat.sdk.domain.job", name) for name in _JOB_EXPORTS},
    **{name: ("scopecat.sdk.domain.inspection", name) for name in _INSPECTION_EXPORTS},
    **{
        name: ("scopecat.sdk.domain.result_mapping", name)
        for name in _RESULT_MAPPING_EXPORTS
    },
    **{name: ("scopecat.sdk.domain.runtime", name) for name in _RUNTIME_EXPORTS},
    **{name: ("scopecat.sdk.domain.view", name) for name in _VIEW_EXPORTS},
    "DomainCompiler": ("scopecat.sdk.domain.compiler", "DomainCompiler"),
    "DomainPreparationBuilder": (
        "scopecat.sdk.domain.preparation",
        "DomainPreparationBuilder",
    ),
}


def __getattr__(name: str) -> object:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = cast("object", getattr(import_module(module_name), attribute_name))
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))


__all__ = [
    "CompiledArtifactInspection",
    "CompiledInspectionBounds",
    "CompiledInspectionFact",
    "CompiledPointInspection",
    "CompiledWaveformInspection",
    "DomainBatchInputs",
    "DomainBatchRequest",
    "DomainCallView",
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
