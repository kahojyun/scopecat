"""User-facing experiment authoring API."""

from scopecat.authoring._module_handles import (
    ExperimentModule,
    ModuleBuilder,
    ModuleInvocation,
    ModuleOutputs,
)
from scopecat.authoring._products import (
    ProductAxis,
    ProductOutputs,
    ProductRef,
    RecordSelection,
    entity_axis,
    product_axis,
    record_alias,
    record_product,
    shot_axis,
)
from scopecat.authoring.definitions import (
    ExperimentBody,
    Input,
    ScratchDefinition,
    experiment,
    input_ref,
    module,
    module_body,
    scratch,
    template,
)
from scopecat.authoring.domain import (
    DomainExecution,
    domain_execution,
    domain_program,
)
from scopecat.authoring.measurements import (
    MeasurementPostprocessor,
    measurement_postprocessor,
)
from scopecat.authoring.templates import (
    ExperimentInvocation,
    ExperimentTemplate,
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
    Scalar as ScalarType,
)
from scopecat.authoring.value_types import (
    String as StringType,
)
from scopecat.authoring.value_types import (
    Table as TableType,
)
from scopecat.authoring.value_types import (
    TableColumn,
    ValueType,
    ValueValidationError,
)
from scopecat.authoring.values import (
    Compute,
    ComputeInput,
    MetadataValue,
    ModuleInput,
    ParameterKeyInput,
    RuntimeInput,
    ScalarInput,
    ValueRef,
    compute,
    coordinate,
    parameter,
    parameter_lookup,
)
from scopecat.authoring.values import input as input
from scopecat.domain.program import (
    DomainInputPort,
    DomainProgramDef,
    DomainResultPort,
)

__all__ = [
    "BoolType",
    "Compute",
    "ComputeInput",
    "DomainExecution",
    "DomainInputPort",
    "DomainProgramDef",
    "DomainResultPort",
    "EntityType",
    "ExperimentBody",
    "ExperimentInvocation",
    "ExperimentModule",
    "ExperimentTemplate",
    "FloatType",
    "Input",
    "IntType",
    "MeasurementPostprocessor",
    "MetadataValue",
    "ModuleBuilder",
    "ModuleInput",
    "ModuleInvocation",
    "ModuleOutputs",
    "ParameterKeyInput",
    "PayloadType",
    "ProductAxis",
    "ProductOutputs",
    "ProductRef",
    "QuantityType",
    "RecordSelection",
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
    "compute",
    "coordinate",
    "domain_execution",
    "domain_program",
    "entity_axis",
    "experiment",
    "input",
    "input_ref",
    "measurement_postprocessor",
    "module",
    "module_body",
    "parameter",
    "parameter_lookup",
    "product_axis",
    "record_alias",
    "record_product",
    "scratch",
    "shot_axis",
    "template",
]
