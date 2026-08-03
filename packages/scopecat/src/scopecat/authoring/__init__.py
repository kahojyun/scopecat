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
from scopecat.authoring._module_results import ProductBundle
from scopecat.authoring.definitions import (
    ExperimentContext,
    ExperimentFactory,
    Input,
    experiment_factory,
    input_ref,
    module,
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
from scopecat.authoring.scans import PointRow, Scan, axis, param_axis, points
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
    "ExperimentFactory",
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
    "PointRow",
    "ProductBundle",
    "ProductRef",
    "QuantityType",
    "RuntimeInput",
    "ScalarInput",
    "ScalarType",
    "Scan",
    "StringType",
    "TableColumn",
    "TableType",
    "ValueRef",
    "ValueType",
    "ValueValidationError",
    "axis",
    "coordinate",
    "each",
    "entity_key",
    "experiment_factory",
    "input_ref",
    "module",
    "one",
    "param_axis",
    "parameter",
    "parameter_column",
    "parameter_lookup",
    "points",
    "template",
]
