# Scopecat instrument provider

`scopecat-instruments` supplies Scopecat's config-driven provider for a focused
set of real and virtual laboratory instruments. Device access is owned by the
project daemon so notebooks, the GUI, and experiment runs share the same
exclusive claims, interface validation, operation receipts, and audit trail.

The configured connection kinds are:

- `virtual`, for a deterministic simulated device selected by `driver_id`;
- `tcpip_socket`, for a configured host, port, and timeout.

## Using the package

The [instrument-control guide](../../docs/how-to/control-instruments.md) is the canonical
user guide for live sessions, symbolic experiments, temporary devices, routing,
roles, shared physical state, and multi-entity clients. The
[reference-lab gallery](../../examples/reference_lab/README.md) contains runnable
examples against coupled virtual devices and bare AWG/scope workflows.

Generated clients preserve concrete Python names and value types across both
time models. Live `apply`, operations, and acquisitions act within a
daemon-owned session; symbolic `ensure`, operations, and acquisitions record
ordered experiment effects. Runs and interactive sessions compete for the same
instrument claims.

Successful acquisitions return named typed readback. A rejected collection
raises `InstrumentCollectFailure` with its receipt and outcome certainty.
`MeasurementUnavailable` represents a successful acquisition whose individual
value was unavailable. Raw snapshots and lower-level receipt channels remain
available for diagnostics.

## Typed client source generation

Decorated Python interface declarations are the shared source for the wire
contract and typed Python surfaces. `PACKAGE_MANIFEST` is the authoritative list
of interfaces, composites, public types, provider identity, and lazy driver
registrations. The generator and provider both derive their catalogs from it.

Run the generator from the repository root after changing a supported
declaration, and use its check mode in validation or CI:

```console
uv run --locked python scripts/generate_instrument_clients.py
uv run --locked python scripts/generate_instrument_clients.py --check
```

Generated modules and the package facade are committed build outputs; edit the
declarations or manifest and regenerate them. Static descriptors make imports
independent of declaration compilation. Writable interfaces receive sparse
member projections; generated clients own wire conversion and exact
`PerEntity` joins. Driver dispatch is supplied once by
`ObjectInstrumentDriver` and does not generate a handler class per device.

One group `ensure(...)` remains a coherent state intent so routing can batch
channels that resolve to the same instrument. Group operations expand to scalar
invocations after validating every entity mapping, preventing partial effects
from a missing or extra identity. Composite client families are package
presentation metadata over existing wire interfaces. When two constituents use
the same Python member name for different property identities, keep both wire
interfaces unchanged and name the package-local view explicitly:

```python
CompositeSurfaceRegistration(
    name="SourceMonitor",
    interface_types=(SourceInterface, MonitorInterface),
    member_name_overrides=(
        (SourceInterface.enabled, "source_enabled"),
        (MonitorInterface.enabled, "monitor_enabled"),
    ),
)
```

These names apply consistently to member accessors and generated patch/target
fields; recording, restoration, routing, and driver dispatch continue to use
the original interface and property identities. Operation and acquisition
collisions use the parallel `method_name_overrides` surface:

```python
method_name_overrides = (
    (TriggerInterface.fire, "fire_trigger"),
    (GateInterface.fire, "fire_gate"),
)
```

An override changes live, symbolic, and group client method names together but
not their operation or acquisition refs. Use aliases only when the methods are
genuinely different concepts. If they are the same portable capability, model
that capability once in a shared interface. Interface authors should also avoid
framework-owned client verbs such as `apply` and `ensure`; those names are a
normal authoring convention rather than a second runtime validation system.

Generated acquisition carrier names use the acquisition declaration as their
key on both individual and composite surfaces:

```python
acquisition_names = (
    AcquisitionPublicNames(
        SensorInterface.sample,
        readback="SensorSampleReadback",
        products="SensorSampleProducts",
    ),
)
```

Either carrier name may be omitted when its declaration-derived default is
already unambiguous. This is also the explicit escape hatch when different
composite acquisitions happen to reuse the same result-class name; it does not
change acquisition or result refs.

The generator currently requires schema-specific client carriers before
exposing payload-bearing operations. The declaration compiler and driver
adapter already accept decoded payloads. Reusable instrument components compile
to nested interface members; resource routes mount root client members at their
physical `component_path`.

## Driver authoring

The shortest driver workflow is:

1. Declare members, results, and a `Protocol` or ABC with the helpers in
   `interface_declarations.py`.
2. Register any new surface and the lazy driver implementation in
   `PACKAGE_MANIFEST`.
3. Run `uv run --locked python scripts/generate_instrument_clients.py`.
4. Subclass `ObjectInstrumentDriver` and bind explicit read/write/query/update
   methods to the declared members.

For example, an RF implementation does not handle member refs or generic
requests:

```python
from typing import Protocol

from scopecat.kernel.quantity import Quantity
from scopecat.sdk.instruments import (
    Change,
    DeviceMember,
    Member,
    ObjectInstrumentDriver,
    device_member,
    instrument_driver,
    member_policy,
    read,
    update,
)
from scopecat.sdk.instruments.declarations import instrument_interface, member


@instrument_interface("example.rf_output/v1")
class RFOutput(Protocol):
    frequency: Member[Quantity] = member(
        access="read_write",
        restore=True,
        unit="Hz",
    )
    output_enabled: Member[bool] = member(access="read_write")


@instrument_driver(
    "example.rf_source",
    "1",
    interfaces=(RFOutput,),
    member_policies=(member_policy(RFOutput.frequency, restore=False),),
    device_schema_id="example.rf_source/v1",
)
class MyRfSource(ObjectInstrumentDriver):
    reference_locked: DeviceMember[bool] = device_member(
        access="read_only",
        capture=True,
        restore=False,
    )

    def __init__(self, instrument_id: str) -> None:
        self.instrument_id = instrument_id

    @read(RFOutput.frequency)
    def read_frequency(self) -> Quantity:
        return self._query_frequency()

    @update(
        RFOutput.frequency,
        RFOutput.output_enabled,
    )
    def update_output(
        self,
        *,
        frequency: Change[Quantity],
        output_enabled: Change[bool],
    ) -> None:
        if frequency.requested:
            self._set_frequency(frequency.value)
        if output_enabled.requested:
            self._set_output(output_enabled.value)

    @read(RFOutput.output_enabled)
    def read_output_enabled(self) -> bool:
        return self._query_output()

    @read(reference_locked)
    def read_reference_locked(self) -> bool:
        return self._query_reference_lock()
```

The base class supplies `describe`, `read_state`, `apply_state`, `invoke`, and
`collect` at the worker boundary. `@read`/`@write` expose independent I/O;
`@query`/`@update` preserve hardware batching and sequencing without creating
aggregate state. A driver overrides a worker method only for routing or a
failure model that these bindings cannot express.

An interface declares the maximum portable member surface. The concrete
driver's I/O bindings declare what one model actually implements. If a model can
report an interface member but cannot change it, bind only `@read`; the emitted
instrument description narrows that physical member to `read_only` and disables
restoration automatically. Do not add a writer whose only behavior is rejecting
changes. Mounted drivers preserve these implementation semantics independently
at every physical component path.

For the less common case where a member remains readable and writable but one
model must not participate in an interface lifecycle policy, add an
exception-only `member_policy(..., capture=False)` or
`member_policy(..., restore=False)` to `@instrument_driver`. The policy cannot
widen the interface and does not repeat its identity, type, units, or bounds.
Generated member clients expose the resolved result through
`member.implementation()` and `member.is_writable()`; `member.set(...)` checks
the concrete endpoint rather than only the portable interface.

`device_member(...)` records model-specific background information without
inventing a one-device interface; its `capture`/`restore` policy is independent
for every member. All four real and four virtual first-party drivers use this
pattern.

## Configuration

The Instruments workspace reads the provider's driver catalog to add or
configure a device. It exposes only supported connection kinds and typed driver
options, can test a candidate connection before publishing it, and derives
sparse startup-default fields from the probed interface description.

Virtual instrument:

```json
{
  "id": "flux",
  "exclusivity_key": "flux",
  "driver_id": "scopecat.virtual.dc_source",
  "connection": {
    "kind": "virtual"
  },
  "default_state": [
    {
      "interface_id": "scopecat.dc_source/v3",
      "property_id": "output_enabled",
      "value": false
    }
  ],
  "run_start": "apply_default_state",
  "success_action": "restore_baseline",
  "failure_action": "abort_and_release"
}
```

TCP/IP instrument:

```json
{
  "id": "readout-lo",
  "exclusivity_key": "readout-lo",
  "driver_id": "scopecat.rohde_schwarz.sgs100a",
  "connection": {
    "kind": "tcpip_socket",
    "host": "192.0.2.10",
    "port": 5025,
    "timeout_seconds": 5
  },
  "run_start": "preserve",
  "success_action": "release",
  "failure_action": "abort_and_release"
}
```

Every run first synchronizes the device. `preserve` retains that observed
state; `apply_default_state` then applies the saved partial public state.
Unspecified and private driver settings remain untouched. After authored
normal-completion state, `release` leaves the resulting state in place;
`restore_baseline` restores the writable portion of the synchronized,
run-start-adjusted baseline before terminal readback and release. Failure always
aborts first; `abort_then_safe_state` may additionally apply the configured
sparse safe state when the device remains commandable.

Lifecycle snapshots capture the requested public and model-specific members
independently. Experiment entity and channel bindings are routing provenance,
not fields a driver reads back.

The DC monitor exposes `measure_current()` and `measure_voltage()` as separate
acquisitions. A concrete driver rejects the call at runtime when its
source mode or hardware configuration is incompatible.

Each registered driver declares its connection kind and a strict options model.
Unknown fields and coerced scalar values are rejected during configuration
discovery:

- Yokogawa GS200: `monitor_option` requests `/MON` support (`bool`, default
  `false`) and is verified with `*OPT?` when the connection opens;
- Yokogawa GS200: `remote_sense` and `guard_enabled` (`bool`, both default
  `false`) declare the expected physical wiring profile. The driver verifies
  them and never switches either setting automatically. Remote sense rejects
  voltage ranges below 1 V;
- Keysight E5080B: `channel` and `measurement` (positive integers, default `1`);
- the other included drivers accept no options.

The package supports these driver IDs:

| Driver ID | Interface |
| --- | --- |
| `scopecat.yokogawa.gs200` | `scopecat.dc_source/v3`; optional `scopecat.dc_monitor/v4` |
| `scopecat.rohde_schwarz.sgs100a` | `scopecat.rf_output/v1` |
| `scopecat.lakeshore.372` | `scopecat.temperature_readout/v1` |
| `scopecat.keysight.e5080b` | `scopecat.network_sweep/v1` |
| `scopecat.virtual.rf_source` | `scopecat.rf_output/v1` |
| `scopecat.virtual.dc_source` | `scopecat.dc_source/v3`, `scopecat.dc_monitor/v4` |
| `scopecat.virtual.temperature_monitor` | `scopecat.temperature_readout/v1` |
| `scopecat.virtual.vna` | `scopecat.network_sweep/v1` |

The real-device implementations are deliberately minimal. Verify firmware,
installed options, limits, cabling, and interlocks for the specific laboratory
before enabling hardware outputs.

SCPI drivers depend on the transport protocol and typed query helpers in
`scopecat.sdk.instruments.scpi`; this package supplies the concrete TCP
transport. Parsing failures therefore retain the command that produced the
invalid response.

## Application composition

Projects install one configured provider at their daemon composition root:

```python
from scopecat_instruments import ConfiguredInstrumentProvider

provider = ConfiguredInstrumentProvider(seed=7)
```

Virtual drivers created by one provider share a deterministic virtual lab
world, so bias, RF heating, temperature, and the VNA response interact across
sessions.

## Testing

The explicit testing module provides strict SCPI transcript helpers:

```python
from scopecat_instruments.testing import ScriptedExchange, ScriptedTransport
```

Their docstrings define the transport contract; driver tests keep exact device
sequences beside the implementations they verify.
