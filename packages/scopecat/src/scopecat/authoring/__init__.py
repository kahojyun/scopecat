"""High-level experiment authoring API.

This facade exposes the objects used to describe experiments. Domain and
generated-client implementations import lower-level schema and recorder types
from their owning modules.
"""

from scopecat.authoring._experiment_module import ExperimentModule
from scopecat.authoring._module_context import ModuleContext
from scopecat.authoring._module_invocation import (
    ModuleInvocation,
)
from scopecat.authoring.definitions import (
    ExperimentContext,
    Input,
    ScratchDefinition,
    input_ref,
    module,
    scratch,
    template,
)
from scopecat.authoring.entity_parameters import (
    ConcreteEntityInput,
    EachEntity,
    EntityInput,
    EntityKey,
    EntitySelection,
    OneEntity,
    ParameterColumn,
    ParameterRow,
    ParameterTable,
    PerEntity,
    each,
    entity_key,
    one,
    parameter_column,
)
from scopecat.authoring.finalization import (
    Finalizable,
    FinalizationTarget,
)
from scopecat.authoring.templates import (
    ExperimentInvocation,
    ExperimentTemplate,
)
from scopecat.program.products import (
    ProductRef,
)
from scopecat.program.value_types import (
    Bool as BoolType,
)
from scopecat.program.value_types import (
    Entity as EntityType,
)
from scopecat.program.value_types import (
    Float as FloatType,
)
from scopecat.program.value_types import (
    Int as IntType,
)
from scopecat.program.value_types import (
    Payload as PayloadType,
)
from scopecat.program.value_types import (
    Quantity as QuantityType,
)
from scopecat.program.value_types import (
    Scalar as ScalarType,
)
from scopecat.program.value_types import (
    String as StringType,
)
from scopecat.program.value_types import (
    Table as TableType,
)
from scopecat.program.value_types import (
    TableColumn,
    ValueType,
    ValueValidationError,
)
from scopecat.program.values import (
    ComputeInput,
    MetadataValue,
    ModuleInput,
    ParameterKeyInput,
    RuntimeInput,
    ScalarInput,
    ValueRef,
    coordinate,
    parameter,
    parameter_lookup,
)

__all__ = [
    "BoolType",
    "ComputeInput",
    "ConcreteEntityInput",
    "EachEntity",
    "EntityInput",
    "EntityKey",
    "EntitySelection",
    "EntityType",
    "ExperimentContext",
    "ExperimentInvocation",
    "ExperimentModule",
    "ExperimentTemplate",
    "Finalizable",
    "FinalizationTarget",
    "FloatType",
    "Input",
    "IntType",
    "MetadataValue",
    "ModuleContext",
    "ModuleInput",
    "ModuleInvocation",
    "OneEntity",
    "ParameterColumn",
    "ParameterKeyInput",
    "ParameterRow",
    "ParameterTable",
    "PayloadType",
    "PerEntity",
    "ProductRef",
    "QuantityType",
    "RuntimeInput",
    "ScalarInput",
    "ScalarType",
    "ScratchDefinition",
    "StringType",
    "TableColumn",
    "TableType",
    "ValueRef",
    "ValueType",
    "ValueValidationError",
    "coordinate",
    "each",
    "entity_key",
    "input_ref",
    "module",
    "one",
    "parameter",
    "parameter_column",
    "parameter_lookup",
    "scratch",
    "template",
]
