"""Ordered product and symbolic-value selections for experiment datasets."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from scopecat.kernel.frozen import freeze_json_mapping
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.value_types import Scalar
from scopecat.measurements.results import MeasurementVariableRole
from scopecat.program.input_capture import empty_program_mapping
from scopecat.program.products import RecordSelection
from scopecat.program.value_graph import ValueId
from scopecat.program.value_refs import ValueRef


@dataclass(frozen=True, slots=True)
class ValueRecordSelection:
    """Experiment-owned request to persist one symbolic scalar value."""

    value: ValueRef
    record_id: str | None = None
    namespace: tuple[str, ...] = ()
    role: MeasurementVariableRole = "observable"
    metadata: Mapping[str, JsonValue] = field(default_factory=empty_program_mapping)

    def __post_init__(self) -> None:
        if self.record_id is not None and not self.record_id:
            raise ValueError("record id must be non-empty when provided")
        if self.record_id is not None and self.namespace:
            raise ValueError("record id and namespace cannot be used together")
        if any(not segment for segment in self.namespace):
            raise ValueError("record namespace segments must be non-empty")
        object.__setattr__(self, "namespace", tuple(self.namespace))
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class LogicalValueRecordSelection:
    """Resolved value identity and durable destination in a logical program."""

    id: str
    value_id: ValueId
    source_value_id: str
    value_type: Scalar
    role: MeasurementVariableRole = "observable"
    metadata: Mapping[str, JsonValue] = field(default_factory=empty_program_mapping)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("value record id must be non-empty")
        if not self.source_value_id:
            raise ValueError("source value id must be non-empty")
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))


type ProgramRecordSelection = RecordSelection | ValueRecordSelection
type LogicalRecordSelection = RecordSelection | LogicalValueRecordSelection


__all__ = [
    "LogicalRecordSelection",
    "LogicalValueRecordSelection",
    "ProgramRecordSelection",
    "ValueRecordSelection",
]
