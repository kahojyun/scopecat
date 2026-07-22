"""High-level experiment authoring template invocations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

from scopecat.authoring._frozen_values import (
    empty_frozen_mapping,
    freeze_runtime_input,
    freeze_runtime_inputs,
)
from scopecat.authoring._validation import validate_template_bound_inputs
from scopecat.authoring._value_refs import ValueRef
from scopecat.authoring.scans import (
    Scan,
    ScanCenter,
    ScanValue,
    build_scan,
)
from scopecat.authoring.values import (
    MetadataValue,
    RuntimeInput,
    runtime_input_is_valid,
)
from scopecat.kernel.frozen import freeze_json_mapping
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter import Quantity

if TYPE_CHECKING:
    from scopecat.authoring._products import (
        RecordSelection,
    )
    from scopecat.authoring.assembly import ExperimentModule

    type TemplateModule = ExperimentModule
    type TemplateRecordSelection = RecordSelection
else:
    type TemplateModule = object
    type TemplateRecordSelection = object

type ConfigProfileInput = str | Path | ConfigProfileSnapshot


class _InputDefaultMissing:
    __slots__ = ()


_INPUT_DEFAULT_MISSING = _InputDefaultMissing()


@dataclass(frozen=True)
class InputDescription:
    id: str
    default: RuntimeInput | _InputDefaultMissing = _INPUT_DEFAULT_MISSING
    label: str | None = None
    description: str | None = None
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)

    def __post_init__(self) -> None:
        if not self.id:
            msg = "template input id must be non-empty"
            raise ValueError(msg)
        if self.has_default and not runtime_input_is_valid(self.default):
            msg = f"template input {self.id!r} default is not closed runtime data"
            raise TypeError(msg)
        if self.has_default:
            object.__setattr__(self, "default", freeze_runtime_input(self.default))
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))

    @property
    def has_default(self) -> bool:
        return self.default is not _INPUT_DEFAULT_MISSING


@dataclass(frozen=True, slots=True, repr=False)
class ExperimentTemplate:
    id: str
    kind: str
    module: TemplateModule
    record_selections: tuple[TemplateRecordSelection, ...] = ()
    inputs: tuple[InputDescription, ...] = ()
    default_scans: tuple[Scan, ...] = ()
    label: str | None = None
    description: str | None = None
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)

    def __post_init__(self) -> None:
        if not self.id:
            msg = "experiment template id must be non-empty"
            raise ValueError(msg)
        if not self.kind:
            msg = "experiment template requires kind"
            raise ValueError(msg)

    def bind(self, **inputs: RuntimeInput) -> ExperimentInvocation:
        _validate_runtime_inputs(inputs)
        validate_template_bound_inputs(
            module=self.module,
            descriptions=self.inputs,
            default_scans=self.default_scans,
            inputs=inputs,
        )
        return ExperimentInvocation(
            template=self,
            inputs=cast("Mapping[str, RuntimeInput]", freeze_runtime_inputs(inputs)),
        )

    def __call__(self, **inputs: RuntimeInput) -> ExperimentInvocation:
        """Bind this closed template through normal Python call syntax."""

        return self.bind(**inputs)


@dataclass(frozen=True, slots=True, repr=False)
class ExperimentInvocation:
    template: ExperimentTemplate
    inputs: Mapping[str, RuntimeInput] = field(default_factory=empty_frozen_mapping)
    scans: tuple[Scan, ...] = ()

    def bind(self, **inputs: RuntimeInput) -> ExperimentInvocation:
        _validate_runtime_inputs(inputs)
        selected = dict(self.inputs)
        selected.update(inputs)
        validate_template_bound_inputs(
            module=self.template.module,
            descriptions=self.template.inputs,
            default_scans=self.template.default_scans,
            inputs=selected,
        )
        return replace(
            self,
            inputs=freeze_runtime_inputs(selected),
        )

    def scan(
        self,
        target: ValueRef | Scan,
        values: Sequence[ScanValue] = (),
        *,
        unit: str | None = None,
        center: ScanCenter | None = None,
        span: Quantity | str | None = None,
        points: int | None = None,
    ) -> ExperimentInvocation:
        selected = build_scan(
            target,
            values,
            unit=unit,
            center=center,
            span=span,
            points=points,
        )
        return replace(self, scans=(*self.scans, selected))


def _validate_runtime_inputs(inputs: Mapping[str, RuntimeInput]) -> None:
    invalid = sorted(
        input_id
        for input_id, value in inputs.items()
        if not input_id or not runtime_input_is_valid(value)
    )
    if invalid:
        selected = ", ".join(repr(input_id) for input_id in invalid)
        msg = (
            "template inputs require non-empty names and closed runtime data: "
            f"{selected}"
        )
        raise TypeError(msg)
