# Instrument control and authoring

Scopecat presents one typed capability vocabulary in two time models: a live
client performs work now, while a symbolic client records the same device verbs
inside an experiment. Drivers implement that capability without receiving run,
entity, point, product, or dataset concepts.

Daemon ownership and failure handling live in the [lab daemon model](lab-daemon.md).
Execution ordering and physical authority live in the
[execution semantics](experiment-execution-model.md). Provider registration,
generation, configuration, and driver tests live in the
[instrument provider README](../packages/scopecat-instruments/README.md).

## Use a configured device now

Create a typed physical reference from the configured instrument id, then open
it through a lab session:

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

`apply(...)` performs a sparse state transition during the call. `sweep()`
triggers hardware and returns typed readback with receipt evidence. The session
owns synchronization and the same exclusive claim used by experiment runs; it
does not create a one-point experiment.

A genuinely temporary diagnostic device can use a session-only binding without
publishing configuration or defining entity routes:

```python
import scopecat as sc
from scopecat.records.config import TcpipSocketInstrumentConnection
from scopecat_instruments import network_sweep


BENCH_VNA = sc.temporary_instrument(
    network_sweep("temporary-bench-vna"),
    driver_id="scopecat.keysight.e5080b",
    connection=TcpipSocketInstrumentConnection(
        host="192.0.2.40",
        port=5025,
    ),
)

with sc.open_project(".").connect(operator="alice") as lab:
    with lab.instruments.open(BENCH_VNA) as devices:
        trace = devices[BENCH_VNA].sweep()
```

The daemon probes the installed driver, owns the connection, and claims a stable
identity for the session. The attachment disappears when the session closes and
does not enter experiment routing. Keep transient cable and operator intent in
the notebook cell. When a diagnostic should become a reproducible run, add the
device to inventory, write a small named experiment, and record its meaningful
result.

## Declare the same work for an experiment

Passing an experiment context to the same factory creates its symbolic client:

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

`ensure(...)` records coherent desired state. Fixed values, inputs, parameters,
and other permitted symbolic values may supply its fields; omitted fields remain
unspecified. Consecutive ensures retain effect order. The symbolic acquisition
returns a typed product bundle, and defining the experiment touches no hardware.

An experiment can coordinate several instrument clients, reusable modules, and
domain calls. `@module` is an extraction boundary for work that is genuinely
reused or composed, rather than a prerequisite for device use.

Product namespaces derive from the capability and effect occurrence. Supply an
explicit acquisition `id=` when an occurrence is part of a durable data
contract. Recording a complete result bundle preserves its declared coordinate,
observable, axis, and acquisition-group relationships. The
[measurement data guide](measurement-data.md#define-what-should-be-recorded) is the
canonical recording reference.

### Select equivalent resources by role

Logical resource identities are allocated automatically. A stable lab role
expresses purpose when one entity has several resources implementing the same
interface:

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

The accepted configuration attaches each role to a selectable route. A route
groups all endpoints chosen together:

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
      "entity_ids": ["q0"],
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

A string selects that exact cataloged role. Omitting `role` selects an unlabelled
route. Code that intentionally accepts the unique compatible route regardless
of role may pass `sc.ANY_RESOURCE_ROLE`.

`entity_ids` lists the logical entities served by the complete route. An
endpoint `entity_id` narrows one channel or command binding to an entity. A
shared LO, sequencer, or waveform endpoint omits the endpoint entity while the
route still lists every entity it serves. Entityless routes support bench work
selected by role or an unscoped experiment.

### Mount shared state on its physical owner

Mutable state belongs to its physical owner: device-wide properties at the
interface root, bank-wide properties on a bank component, LO frequency on an LO
component, and channel properties on channel components. Endpoint
`component_path` mounts a logical interface member at that owner.

When several routes resolve a property to the same physical address, they form
one effective shared-state group for that property. Equal requirements coalesce
into one command; unequal requirements produce
`experiment_conflicting_desired_state` before execution. Group membership is
capability-specific, so channels may share an LO while belonging to different
clock or trigger domains. Components such as `lo_groups/0`, `clock_domains/1`,
and `trigger_domains/0` express those distinct owners.

Roles select hardware by purpose. Component paths express shared mutable state.
Logical entity ids remain provenance and do not create copies of a physical
state slot.

### Use signed IF for specialized LO scans

Common experiments express physical carrier intent and use reviewed lab
frequency composition. A specialized fixed-IF LO scan can stay lab-local with
the single convention `RF = LO + signed IF`; positive and negative IF values
select the IQ sideband directly.

The scanned LO is already a durable point coordinate. Record the derived carrier
as another coordinate so plots and exports retain both the requested control and
its physical meaning. The reference lab's
[`xy_drive` workflow](../examples/reference_lab/src/reference_lab/workflows/xy_drive.py)
shows this composition, and the
[`fixed-IF quantum sweep`](../examples/reference_lab/notebooks/36_q0_fixed_if_lo_sweep.py)
shows an LO host effect bounding domain batches.

Routing determines which source is changed. Equal requests to one resolved LO
owner coalesce; distinct LO owners remain independently schedulable. Only a lab
that deliberately coordinates a scan per physical owner needs additional local
grouping logic.

### Address one or many entities

Entity cardinality is selected at the factory boundary:

```python
single = network_sweep(
    experiment,
    for_=sc.one("q0", kind="logical_device"),
)

targets = sc.each("q0", "q1", kind="logical_device")
many = network_sweep(experiment, for_=targets)
```

`one(...)` creates one scalar symbolic client. Its entity may be concrete or
point-resolved. `each(...)` holds concrete authoring-time identities and returns
a group client with the same verbs. Scalar arguments broadcast; `PerEntity[T]`
supplies values by exact `(kind, id)` identity:

```python
points = sc.PerEntity((entity, 501 if entity.id == "q0" else 801) for entity in targets)

many.ensure(
    start_frequency=sc.Quantity(4.9, "GHz"),
    stop_frequency=sc.Quantity(5.1, "GHz"),
    points=points,
    s_parameter="S21",
)
traces = many.sweep()
experiment.record(traces)
```

Alignment is an identity join, so mapping order is irrelevant and missing,
extra, or duplicate identities fail before effects are recorded. Group authoring
expands to independently routed scalar resources; it does not ask a driver to
perform an implicit vector operation.

## Extend an instrument capability

An interface author declares concrete state and result records, then decorates a
Python `Protocol` or abstract base class:

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
        role="coordinate", dtype="float64", unit="Hz", axes=("frequency",)
    )
    s_parameter: list[complex] = result_field(
        dtype="complex128", unit="ratio", axes=("frequency",)
    )


@instrument_interface("example.network_sweep/v1", state=NetworkSweepState)
class NetworkSweep(Protocol):
    @acquisition(axes={"frequency": axis(size="points", unit="Hz")})
    def sweep(self) -> NetworkSweepResults: ...
```

State fields describe complete hardware state with concrete types. Generated
sparse patch and target carriers represent omission. Result declarations own
roles and axes. The declaration compiler produces the wire contract, while the
provider generator produces typed clients, member references, projections, and
driver adapters.

A driver subclasses the generated adapter and implements typed hooks. The
adapter handles member dispatch and wire conversion; the driver owns command
ordering, device-specific limits, temporary setup/restoration, and response
interpretation.

An operation that can disturb persistent state lists the affected property refs
in `invalidates`. This withdraws prior state knowledge without asserting the
post-operation value. A later `ensure` establishes a new guarantee; an ordinary
acquisition remains runtime evidence. The `operation(...)` docstring defines the
exact local contract, and planning diagnostics identify which effect invalidated
a missing requirement.

See [driver authoring](../packages/scopecat-instruments/README.md#driver-authoring)
for the implementation boundary and
[typed client source generation](../packages/scopecat-instruments/README.md#typed-client-source-generation)
for the generator workflow.

## Compact rule set

1. Declare device meaning once with concrete Python state, operations, and
   results.
2. Use `apply` for an immediate sparse transition and `ensure` for symbolic
   desired state; use the same operation and acquisition verbs in both modes.
3. Let generated clients add time and cardinality: live or symbolic, one entity
   or `PerEntity`.
4. Mount mutable state at its physical owner and select equivalent resources by
   stable lab purpose.
5. Return typed values or product bundles and let dependencies determine order.
6. Record values and bundles directly; declared roles, axes, groups, and entity
   identity carry the dataset mapping.
