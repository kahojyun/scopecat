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

This is also the low-friction path for a genuinely temporary diagnostic device.
Wrap the normal typed reference with a session-only driver binding; no config
publication or entity mapping is required:

```python
import scopecat as sc
from scopecat.records.config import TcpipSocketInstrumentConnection
from scopecat_instruments import network_sweep


BENCH_VNA = sc.temporary_instrument(
    network_sweep("temporary-bench-vna"),
    driver_id="scopecat.e5080b",
    connection=TcpipSocketInstrumentConnection(
        host="192.0.2.40",
        port=5025,
    ),
)

with sc.open_project(".").connect(operator="alice") as lab:
    with lab.instruments.open(BENCH_VNA) as devices:
        trace = devices[BENCH_VNA].sweep()
```

The daemon still probes the installed driver, owns the connection, and claims a
stable access identity for the session. The attachment disappears when the
session ends and is not offered to experiment routing. Put transient cabling or
operator intent in the notebook cell. If the diagnostic must be retained with
other measurements, promote the device to inventory, write a small named
experiment, and record only its meaningful result. Routine device state remains
receipt and run evidence rather than becoming dataset columns automatically.

## Declare the same work for later

Passing an experiment context to the same factory creates the symbolic client.
Its verbs retain the device meaning while recording work instead of executing
it:

```python
import scopecat as sc
from scopecat_instruments import network_sweep


@sc.experiment
def capture(experiment: sc.ExperimentContext) -> None:
    vna = network_sweep(experiment)
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

Product and recording namespaces come from the instrument family and the
effect occurrence, not from the internal logical resource-port id. Pass an
explicit acquisition `id=` when that occurrence is part of a durable data
contract; inserting an unused client will not rename existing data.

The experiment is the orchestration boundary, not a single-device runner. One
experiment may coordinate several typed instrument clients, reusable modules,
and domain calls; their value and effect dependencies determine the executable
order while the lab configuration supplies physical resources.

### Distinguish equivalent resources by role

The context allocates logical resource identities automatically. When one
entity has multiple instruments implementing the same interface, use a stable
lab role to express why each one is needed:

```python
from scopecat_instruments import rf_output


drive = rf_output(
    experiment,
    for_=sc.one("q0", kind="logical_device"),
    role="drive",
)
readout = rf_output(
    experiment,
    for_=sc.one("q0", kind="logical_device"),
    role="readout",
)
```

The accepted configuration catalogs the role and attaches it to a selectable
resource route. A route groups every endpoint that must be chosen together:

```json
{
  "roles": [
    {"id": "readout", "description": "source used for qubit readout"}
  ],
  "routes": [
    {
      "id": "readout-source",
      "instrument_id": "readout-source-0",
      "role_id": "readout",
      "endpoints": [
        {
          "interface_id": "scopecat.rf_output/v1",
          "entity_id": "q0",
          "channel_id": "readout-q0",
          "component_path": ["outputs", "readout-q0"]
        }
      ]
    }
  ]
}
```

`role` is a routing qualifier, not a physical instrument id. A string selects
that exact cataloged role. Omitting `role` selects only routes with no role;
it is not a wildcard. Rare authoring code that intentionally accepts any role
can pass `sc.ANY_RESOURCE_ROLE`, after which planning must still find exactly
one complete route.

### Put shared state on its physical owner

An entity binding selects a logical user of hardware; it is not the identity
of a mutable state slot. Device-wide properties live at the interface root,
tile-wide properties at a tile component, LO frequency at an LO-group
component, and channel-only properties at a channel component. Route endpoint
`component_path` mounts the authored interface member onto that physical
owner.

Two qubits may therefore route an RF-output frequency property to the same
component path. Equal frequency requirements coalesce into one command. If the
requirements differ at one point, planning reports
`experiment_conflicting_desired_state` before hardware execution. Logical
entity ids remain command provenance but do not manufacture independent copies
of shared state.

There is no separate channel-group or LO-group topology object. For a given
property, entities belong to the same effective group precisely when their
routes resolve to the same physical property target. That distinction matters
because grouping is capability-specific: two channels can share an LO while
belonging to different clock or trigger domains. Model those owners as reusable
instrument components such as `lo_groups/0`, `clock_domains/1`, and
`trigger_domains/0`, then mount each routed interface member at the appropriate
component path.

Roles still choose hardware by logical purpose. They do not encode shared-state
membership, and LO groups are not entities merely because an experiment may
need to change their state.

### Scan LO without losing the physical RF coordinate

Most experiments should express physical RF intent and leave device-specific
mixing to their lab implementation. The uncommon experiment that deliberately
scans an LO can keep its convention in a small lab-local helper. Use a signed
IF and the single relation `RF = LO + IF`; positive and negative values select
the two IQ sidebands without a second sideband flag:

```python
def fixed_if_lo_sweep(experiment, source, *, signed_if):
    lo_frequency = experiment.scan(
        "lo_frequency",
        (4.9, 5.0, 5.1),
        unit="GHz",
    )
    rf_frequency = lo_frequency + signed_if

    source.ensure(frequency=lo_frequency)
    experiment.record(
        rf_frequency,
        record_id="rf_frequency",
        role="coordinate",
        metadata={
            "relation": "rf_frequency = lo_frequency + signed_if",
            "signed_if_hz": float(signed_if.to("Hz").value),
        },
    )
    return rf_frequency
```

The scanned LO is already a durable point coordinate. Recording the derived RF
adds a plot-ready physical coordinate while retaining the exact control value
and signed-IF convention. If IF varies by qubit, the helper can obtain it from a
normal parameter lookup; it does not require a frequency-plan or LO-topology API.

Which source is changed still comes from routing. If several selected entities
route the source-frequency property to one component path, equal requests
coalesce and differing requests fail during planning. An experiment only needs
special grouping logic when it intentionally wants to schedule distinct scans
per resolved physical owner; that remains lab policy rather than core topology.

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
    for_=sc.one("q0", kind="logical_device"),
)

targets = sc.each("q0", "q1", kind="logical_device")
many = network_sweep(experiment, for_=targets)
```

`one(...)` returns one scalar symbolic client. Its entity may be concrete or a
point-resolved symbolic entity. `each(...)` contains concrete identities known
while authoring and returns a group client with the same `ensure(...)` and
`sweep()` verbs.

For every group argument, a scalar broadcasts and `PerEntity[T]` supplies
different values by entity:

```python
points = sc.PerEntity((entity, 501 if entity.id == "q0" else 801) for entity in targets)

many.ensure(
    start_frequency=sc.Quantity(4.9, "GHz"),  # broadcast
    stop_frequency=sc.Quantity(5.1, "GHz"),  # broadcast
    points=points,  # mapped by entity
    s_parameter="S21",  # broadcast
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
