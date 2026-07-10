"""User-facing experiment authoring API."""

from scopecat.authoring.assembly import (
    BindingIntent,
    ComputeResultRef,
    DerivedVariableIntent,
    ExperimentBindingIntent,
    ExperimentModule,
    ExperimentStateIntent,
    ExplicitVariableIntent,
    ModuleBuilder,
    ModuleInputPort,
    ModuleInvocation,
    ModuleProductPort,
    ProductSelectionIntent,
    RecordAxisIntent,
    RecordIntent,
    ResourcePort,
    ResourceSelector,
    RouteBindingRef,
    StateEachIntent,
    VariableIntent,
    bind,
    compute_result,
    derive,
    entity_axis,
    input_ref,
    input_series,
    input_table,
    module,
    observable,
    param_ref,
    record_axis,
    record_product,
    requires,
    resource_port,
    route,
    shot_axis,
    var_ref,
    variable,
)
from scopecat.authoring.context import ExperimentAuthoringContext
from scopecat.authoring.resolution import (
    ResolvedExperiment,
    resolve_experiment,
    resolve_experiment_with_config,
)
from scopecat.authoring.templates import (
    ExperimentInvocation,
    ExperimentTemplate,
    InputDescription,
    TemplateBuilder,
)
from scopecat.authoring.value_types import (
    Bool as BoolType,
)
from scopecat.authoring.value_types import (
    Entity as EntityType,
)
from scopecat.authoring.value_types import (
    Float as FloatType,
)
from scopecat.authoring.value_types import (
    Int as IntType,
)
from scopecat.authoring.value_types import (
    Payload as PayloadType,
)
from scopecat.authoring.value_types import (
    Quantity as QuantityType,
)
from scopecat.authoring.value_types import (
    Record as RecordType,
)
from scopecat.authoring.value_types import (
    RecordField,
    TableColumn,
    ValueType,
    ValueValidationError,
)
from scopecat.authoring.value_types import (
    Scalar as ScalarType,
)
from scopecat.authoring.value_types import (
    Series as SeriesType,
)
from scopecat.authoring.value_types import (
    String as StringType,
)
from scopecat.authoring.value_types import (
    Table as TableType,
)
from scopecat.experiments import (
    ComputeNodeContext as ComputeContext,
)

__all__ = [
    "BindingIntent",
    "BoolType",
    "ComputeContext",
    "ComputeResultRef",
    "DerivedVariableIntent",
    "EntityType",
    "ExperimentAuthoringContext",
    "ExperimentBindingIntent",
    "ExperimentInvocation",
    "ExperimentModule",
    "ExperimentStateIntent",
    "ExperimentTemplate",
    "ExplicitVariableIntent",
    "FloatType",
    "InputDescription",
    "IntType",
    "ModuleBuilder",
    "ModuleInputPort",
    "ModuleInvocation",
    "ModuleProductPort",
    "PayloadType",
    "ProductSelectionIntent",
    "QuantityType",
    "RecordAxisIntent",
    "RecordField",
    "RecordIntent",
    "RecordType",
    "ResolvedExperiment",
    "ResourcePort",
    "ResourceSelector",
    "RouteBindingRef",
    "ScalarType",
    "SeriesType",
    "StateEachIntent",
    "StringType",
    "TableColumn",
    "TableType",
    "TemplateBuilder",
    "ValueType",
    "ValueValidationError",
    "VariableIntent",
    "bind",
    "compute_result",
    "derive",
    "entity_axis",
    "input_ref",
    "input_series",
    "input_table",
    "module",
    "observable",
    "param_ref",
    "record_axis",
    "record_product",
    "requires",
    "resolve_experiment",
    "resolve_experiment_with_config",
    "resource_port",
    "route",
    "shot_axis",
    "var_ref",
    "variable",
]
