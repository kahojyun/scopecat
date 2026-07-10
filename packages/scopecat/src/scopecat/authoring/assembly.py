"""Public module authoring facade."""

from scopecat.authoring._module_construction import (
    module as module,
)
from scopecat.authoring._module_handles import (
    ExperimentModule as ExperimentModule,
)
from scopecat.authoring._module_handles import (
    ModuleBuilder as ModuleBuilder,
)
from scopecat.authoring._module_handles import (
    ModuleInvocation as ModuleInvocation,
)

__all__ = [
    "ExperimentModule",
    "ModuleBuilder",
    "ModuleInvocation",
    "module",
]
