# Instrument authoring

Scopecat uses one typed instrument capability across four activities:

1. declare the capability as ordinary Python;
2. implement it in a driver;
3. control a configured device immediately;
4. use the same verbs symbolically while defining an experiment.

The interface is the shared vocabulary. Live control and experiment authoring
have different time models, but they should not require users to learn different
device models.

The decorated interface lowers in three directions: to `InterfaceSpec` and
member refs for the daemon and driver adapter, to a live client that produces
values and receipts now, and to a symbolic client that records effects and
product refs for later execution.

Daemon ownership, replay, failure handling, and process boundaries live in
[Lab Daemon](lab-daemon.md). Driver registration, configuration, generation,
and tests live in the [instrument provider README](../packages/scopecat-instruments/README.md).
Execution ordering and physical-resource semantics live in
[Experiment Execution Semantics](experiment-execution-model.md).

## Declare one capability

An interface author writes concrete state and result records, then decorates a
Python `Protocol` or abstract base class. The declaration describes what the
capability means; it does not contain session or experiment behavior.

```python
from typing import Protocol

from scopecat import Quantity
from scopecat.sdk.instruments.declarations import (
    acquisition,
    axis,
    instrument_interface,
    instrument_result,
    instrument_state,
    member_field,
    result_field,
)


@instrument_state
class NetworkSweepState:
    start_frequency: Quantity = member_field(unit="Hz")
    stop_frequency: Quantity = member_field(unit="Hz")
    points: int = member_field(minimum=2)
    s_parameter: str = member_field()


@instrument_result
class NetworkSweepResults:
    frequency: list[float] = result_field(
        role="coordinate",
        dtype="float64",
        unit="Hz",
        axes=("frequency",),
    )
    s_parameter: list[complex] = result_field(
        dtype="complex128",
        unit="ratio",
        axes=("frequency",),
    )


@instrument_interface(
    "example.network_sweep/v1",
    state=NetworkSweepState,
)
class NetworkSweep(Protocol):
    @acquisition(
        axes={"frequency": axis(size="points", unit="Hz")},
    )
    def sweep(self) -> NetworkSweepResults: ...
```

The Python types are intentionally concrete:

- state fields describe complete hardware state and contain `T`, not
  `T | None` or `ValueRef`;
- omission belongs to generated sparse `Patch` and `Target` carriers;
- acquisition result roles and axes belong to the result declaration;
- interface and method decorators attach contract metadata without replacing
  the authored `Protocol` or ABC.

The compiler lowers this declaration to the stable wire contract. The provider
generator derives typed clients, member refs, state projections, and driver
adapters from the same source.

## Implement the driver

A driver implements the generated typed adapter hooks. It receives concrete
patches, operation arguments, and acquisition selections expressed in Python
field names. It returns complete typed state or readback records.

The adapter owns generic member-ref dispatch and wire conversion. The driver
continues to own device policy: command ordering, model-specific limits,
temporary setup and restoration, and interpretation of device responses. Run,
entity, point, product, and dataset concepts do not enter the driver API.

See [Driver authoring](../packages/scopecat-instruments/README.md#driver-authoring)
for the provider boundary and
[Typed client source generation](../packages/scopecat-instruments/README.md#typed-client-source-generation)
for generated source and commands.

## Use the capability now

Passing a configured instrument id to the typed factory creates a physical
reference. Opening it through a lab session returns the live client:

```python
import scopecat as sc
from scopecat_instruments import network_sweep


READOUT_VNA = network_sweep("readout-vna")

with sc.open_project(".").connect(operator="alice") as lab:
    with lab.instruments.open(READOUT_VNA) as devices:
        vna = devices[READOUT_VNA]
        vna.apply(
            start_frequency=sc.Quantity(4.9, "GHz"),
            stop_frequency=sc.Quantity(5.1, "GHz"),
            points=751,
            s_parameter="S21",
        )
        trace = vna.sweep()
```

`apply(...)` changes hardware during the call and accepts concrete values.
`sweep()` triggers hardware and returns named readback plus its receipt. The
session owns synchronization and exclusive access; opening a client is not an
experiment with one point.

## Declare the same work for later

Passing an experiment context and logical resource id to the same factory
creates the symbolic client. Its verbs retain the device meaning while recording
work instead of executing it:

```python
import scopecat as sc
from scopecat_instruments import network_sweep


@sc.experiment(id="resonator.capture", kind="resonator")
def capture(experiment: sc.ExperimentContext) -> None:
    vna = network_sweep(experiment, "readout")
    vna.ensure(
        start_frequency=sc.Quantity(4.9, "GHz"),
        stop_frequency=sc.Quantity(5.1, "GHz"),
        points=751,
        s_parameter="S21",
    )
    trace = vna.sweep()
    experiment.record(trace)
```

`ensure(...)` records a coherent state intention. Fixed values, inputs,
parameters, and other permitted `ValueRef` values may supply its fields.
Omitted fields remain unspecified. Consecutive ensures remain ordered effects;
they are not merged into an unordered desired-state bag.

The symbolic `sweep()` records an acquisition and returns a typed product
bundle. Defining the experiment touches no hardware. A reusable `@module` is an
optional extraction for shared or composed work, not a prerequisite for using
an instrument.

The experiment is the orchestration boundary, not a single-device runner. One
experiment may coordinate several typed instrument clients, reusable modules,
and domain calls; their value and effect dependencies determine the executable
order while the lab configuration supplies physical resources.

### Record the result as a bundle

Record the acquisition result directly:

```python
trace = vna.sweep()
experiment.record(trace, namespace="calibration")
```

The declaration already says that `frequency` is a coordinate and
`s_parameter` is an observable sharing the frequency axis. Recording the whole
bundle preserves that relationship in the dataset without separate
`record_coordinate(...)`, `record(...)`, or string-based product wiring.

The dataset remains columnar: the two fields become separate qualified
variables with a shared acquisition group and dimensions. If one member is
genuinely the desired data, `experiment.record(trace.frequency)` retains its
declared coordinate role.

## One entity and many entities

Entity cardinality is selected at the factory boundary:

```python
single = network_sweep(
    experiment,
    "readout",
    for_=sc.one("q0", kind="logical_device"),
)

targets = sc.each("q0", "q1", kind="logical_device")
many = network_sweep(experiment, "readout", for_=targets)
```

`one(...)` returns one scalar symbolic client. Its entity may be concrete or a
point-resolved symbolic entity. `each(...)` contains concrete identities known
while authoring and returns a group client with the same `ensure(...)` and
`sweep()` verbs.

For every group argument, a scalar broadcasts and `PerEntity[T]` supplies
different values by entity:

```python
points = sc.PerEntity(
    (entity, 501 if entity.id == "q0" else 801)
    for entity in targets
)

many.ensure(
    start_frequency=sc.Quantity(4.9, "GHz"),  # broadcast
    stop_frequency=sc.Quantity(5.1, "GHz"),   # broadcast
    points=points,                              # mapped by entity
    s_parameter="S21",                         # broadcast
)
traces = many.sweep()  # PerEntity[NetworkSweepProducts]
experiment.record(traces)
```

`PerEntity` is an immutable identity-keyed mapping. Alignment is an exact join
on `(kind, id)`, never a positional zip. Missing, extra, and duplicate identities
are errors before effects are recorded. `one(...)` and `each(...)` describe
target cardinality only; parameter lookup remains an explicit scalar dependency
instead of introducing a second table-schema and row-indexing API.

Group authoring expands to independently routable scalar resources and effects.
It does not ask one driver to perform an implicit vector operation. Recording a
`PerEntity` acquisition result preserves entity order, result roles, and the
bundle relationship for every entity.

## The compact rule set

1. Declare device meaning once with concrete Python state, methods, and results.
2. Let generated boundaries add time and cardinality: live versus symbolic,
   one entity versus `PerEntity`.
3. Use `apply` for an immediate sparse transition and `ensure` for a symbolic
   state effect; use the same operation and acquisition verbs on both clients.
4. Return typed values or product bundles from producers and let dependencies
   determine execution order.
5. Record values or complete bundles directly; declared roles, axes, groups,
   and entity identity carry the dataset mapping.
