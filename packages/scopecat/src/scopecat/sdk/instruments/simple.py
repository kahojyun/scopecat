"""Callback adapter for simple, point-local peripheral instruments.

This adapter is intentionally narrower than :class:`InstrumentDriver`.  It is
for scalar desired state and direct product reads; programmable devices and
domain jobs should implement the full driver or domain execution contract.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from scopecat.kernel.problems import (
    LocationPathItem,
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.kernel.state import StateLiteral, StateValue
from scopecat.kernel.value_types import Payload
from scopecat.kernel.value_validation import coerce_literal
from scopecat.measurements.results import MeasurementValue
from scopecat.records.instrument import (
    InstrumentReadback,
    InstrumentStateField,
    InstrumentStateSnapshot,
)
from scopecat.sdk.instruments.contracts import (
    ActionReceipt,
    ApplyReceipt,
    CapabilityDescription,
    CapabilityField,
    CollectCommand,
    CollectReceipt,
    DriverFault,
    InstrumentActionCommand,
    InstrumentDescription,
    InstrumentStateCommand,
    ProductDescription,
    capability,
    validate_state_command,
)

type SimpleStateReader = Callable[[], StateLiteral | StateValue]
type SimpleStateWriter = Callable[[StateLiteral], None]
type SimpleProductReader = Callable[[], MeasurementValue]
type SimpleLifecycleCallback = Callable[[], None]


@dataclass(frozen=True, slots=True)
class SimpleStateField:
    """One scalar desired-state field backed by a getter and setter."""

    field: CapabilityField
    read: SimpleStateReader
    write: SimpleStateWriter

    def __post_init__(self) -> None:
        if isinstance(self.field.value_type.atom, Payload):
            msg = (
                "simple instrument state fields do not support payloads; "
                "implement InstrumentDriver for programmable devices"
            )
            raise ValueError(msg)
        if not callable(self.read) or not callable(self.write):
            msg = "simple instrument state read and write callbacks must be callable"
            raise TypeError(msg)


@dataclass(frozen=True, slots=True)
class SimpleProduct:
    """One directly readable product."""

    product: ProductDescription
    read: SimpleProductReader

    def __post_init__(self) -> None:
        if not callable(self.read):
            msg = "simple instrument product read callback must be callable"
            raise TypeError(msg)


@dataclass(frozen=True, slots=True)
class SimpleCapability:
    """A capability and the callbacks realizing its fields and products."""

    id: str
    fields: tuple[SimpleStateField, ...] = ()
    products: tuple[SimpleProduct, ...] = ()
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.id:
            msg = "simple instrument capability id must be non-empty"
            raise ValueError(msg)
        _require_unique(
            (binding.field.id for binding in self.fields),
            label=f"state fields in capability {self.id!r}",
        )
        _require_unique(
            (binding.product.key for binding in self.products),
            label=f"products in capability {self.id!r}",
        )


def simple_capability(
    id: str,  # noqa: A002
    *,
    fields: Sequence[SimpleStateField] = (),
    products: Sequence[SimpleProduct] = (),
    metadata: Mapping[str, Any] | None = None,
) -> SimpleCapability:
    """Declare a callback-backed capability."""

    return SimpleCapability(
        id=id,
        fields=tuple(fields),
        products=tuple(products),
        metadata=metadata,
    )


class SimpleInstrumentDriver:
    """Adapt scalar getters, setters, and readers to ``InstrumentDriver``.

    Command validation is completed before any setter or reader is called, so
    unsupported direct calls fail as known-negative receipts without partial
    device effects.  Callback exceptions remain exceptional: the execution
    engine correctly treats their effect outcome as unknown.
    """

    def __init__(
        self,
        *,
        instrument_id: str,
        implementation_id: str,
        implementation_version: str,
        capabilities: Sequence[SimpleCapability],
        metadata: Mapping[str, Any] | None = None,
        cleanup: SimpleLifecycleCallback | None = None,
        abort: SimpleLifecycleCallback | None = None,
    ) -> None:
        for value, label in (
            (instrument_id, "instrument_id"),
            (implementation_id, "implementation_id"),
            (implementation_version, "implementation_version"),
        ):
            if not value:
                msg = f"simple instrument {label} must be non-empty"
                raise ValueError(msg)
        selected_capabilities = tuple(capabilities)
        _require_unique(
            (item.id for item in selected_capabilities),
            label="capability ids",
        )

        self.instrument_id = instrument_id
        self.implementation_id = implementation_id
        self.implementation_version = implementation_version
        self._cleanup = cleanup or _no_op
        self._abort = abort or _no_op
        self._state_bindings: dict[tuple[str, str], SimpleStateField] = {}
        self._product_bindings: dict[tuple[str, str], SimpleProduct] = {}

        described_capabilities: list[CapabilityDescription] = []
        for item in selected_capabilities:
            described_fields: list[CapabilityField] = []
            for binding in item.fields:
                field = binding.field.model_copy(deep=True)
                described_fields.append(field)
                self._state_bindings[(item.id, field.id)] = SimpleStateField(
                    field=field,
                    read=binding.read,
                    write=binding.write,
                )
            described_products: list[ProductDescription] = []
            for binding in item.products:
                product = binding.product.model_copy(deep=True)
                described_products.append(product)
                self._product_bindings[(item.id, product.key)] = SimpleProduct(
                    product=product,
                    read=binding.read,
                )
            described_capabilities.append(
                capability(
                    item.id,
                    fields=described_fields,
                    products=described_products,
                    metadata=dict(item.metadata or {}),
                )
            )
        self._description = InstrumentDescription(
            instrument_id=instrument_id,
            implementation_id=implementation_id,
            implementation_version=implementation_version,
            capabilities=described_capabilities,
            metadata=dict(metadata or {}),
        )

    def describe(self) -> InstrumentDescription:
        return self._description.model_copy(deep=True)

    def read_state(self) -> InstrumentStateSnapshot:
        fields: list[InstrumentStateField] = []
        for (capability_id, field_path), binding in self._state_bindings.items():
            fields.append(
                InstrumentStateField(
                    capability_id=capability_id,
                    field_path=field_path,
                    value=_coerce_state(binding, binding.read()),
                )
            )
        return InstrumentStateSnapshot(
            instrument_id=self.instrument_id,
            fields=fields,
        )

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        problems = validate_state_command(
            command=command,
            description=self._description,
        )
        problems.extend(_simple_state_target_problems(command))
        if problems:
            return ApplyReceipt(status="not_applied", problems=tuple(problems))

        writes: list[tuple[SimpleStateWriter, StateLiteral]] = []
        for field in command.fields:
            binding = self._state_bindings[(field.capability_id, field.field_path)]
            writes.append((binding.write, _coerce_state(binding, field.value).root))
        for write, value in writes:
            write(value)
        return ApplyReceipt(status="applied")

    def action(self, command: InstrumentActionCommand) -> ActionReceipt:
        return ActionReceipt(
            status="not_performed",
            problems=(
                _problem(
                    "simple_instrument_action_unsupported",
                    f"{self.instrument_id} does not support one-shot actions",
                    "actions",
                    command.operation_id,
                ),
            ),
        )

    def collect(self, command: CollectCommand) -> CollectReceipt:
        selected: list[tuple[str, SimpleProductReader]] = []
        problems: list[Problem] = []
        if command.instrument_id != self.instrument_id:
            problems.append(
                _problem(
                    "simple_instrument_mismatch",
                    f"{self.instrument_id} cannot collect for {command.instrument_id}",
                    "instrument_id",
                )
            )
        else:
            for request in command.requests:
                binding = self._find_product(
                    capability_id=request.capability_id,
                    product_key=request.id,
                )
                if binding is None:
                    problems.append(
                        _problem(
                            "simple_instrument_product_unsupported",
                            f"{self.instrument_id} does not uniquely support product "
                            f"{request.id!r}",
                            "requests",
                            request.id,
                        )
                    )
                elif request.entity_ids or request.channel_bindings:
                    problems.append(
                        _problem(
                            "simple_instrument_routed_target_unsupported",
                            "simple instrument products do not support routed targets",
                            "requests",
                            request.id,
                        )
                    )
                else:
                    selected.append((request.id, binding.read))
        if problems:
            return CollectReceipt(status="not_collected", problems=tuple(problems))

        values = {product_id: read() for product_id, read in selected}
        return CollectReceipt(
            status="collected",
            readback=InstrumentReadback(values=values),
        )

    def cleanup(self) -> None:
        self._cleanup()

    def abort(self) -> None:
        self._abort()

    def _find_product(
        self,
        *,
        capability_id: str | None,
        product_key: str,
    ) -> SimpleProduct | None:
        if capability_id is not None:
            return self._product_bindings.get((capability_id, product_key))
        matches = [
            binding
            for (_, selected_key), binding in self._product_bindings.items()
            if selected_key == product_key
        ]
        return matches[0] if len(matches) == 1 else None


def _coerce_state(
    binding: SimpleStateField,
    value: StateLiteral | StateValue,
) -> StateValue:
    selected = value.root if isinstance(value, StateValue) else value
    try:
        coerced = coerce_literal(binding.field.value_type, selected)
        return StateValue(cast("StateLiteral", coerced))
    except ValueError as error:
        raise DriverFault(
            _problem(
                "simple_instrument_state_value_invalid",
                f"{binding.field.id}: {error}",
                "state",
                binding.field.id,
            )
        ) from error


def _simple_state_target_problems(
    command: InstrumentStateCommand,
) -> list[Problem]:
    return [
        _problem(
            "simple_instrument_routed_target_unsupported",
            "simple instrument state fields do not support routed targets",
            "fields",
            index,
        )
        for index, field in enumerate(command.fields)
        if field.entity_ids or field.channel_bindings
    ]


def _problem(
    code: str,
    message: str,
    *path: LocationPathItem,
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=ProblemCategory.PROVIDER_CONTRACT,
        phase=ProblemPhase.EXECUTION,
        location=model_location("simple_instrument", *path),
    )


def _require_unique(values: Iterable[str], *, label: str) -> None:
    selected = tuple(values)
    if len(selected) != len(set(selected)):
        msg = f"simple instrument {label} must be unique"
        raise ValueError(msg)


def _no_op() -> None:
    return None


__all__ = [
    "SimpleCapability",
    "SimpleInstrumentDriver",
    "SimpleLifecycleCallback",
    "SimpleProduct",
    "SimpleProductReader",
    "SimpleStateField",
    "SimpleStateReader",
    "SimpleStateWriter",
    "simple_capability",
]
