# Scopecat instrument provider

`scopecat-instruments` supplies Scopecat's config-driven provider for a focused
set of real and virtual laboratory instruments. Device access is owned by the
project daemon so notebooks, the GUI, and experiment runs share the same
exclusive claims, interface validation, operation receipts, and audit trail.

The configured connection kinds are:

- `virtual`, for a deterministic simulated device selected by `driver_id`;
- `tcpip_socket`, for a configured host, port, and timeout.

## Notebook use

Use the project connection's `lab.instruments` API. An experiment run is not
required for direct instrument work:

```python
import scopecat as sc
from scopecat_instruments import network_sweep

READOUT_VNA = network_sweep("readout-vna")

with sc.open_project(".").connect(operator="alice") as lab:
    for item in lab.instruments.list().items:
        print(item.instrument_id, item.availability)

    with lab.instruments.open(READOUT_VNA) as devices:
        vna = devices[READOUT_VNA]
        print(vna.describe())
        print(vna.observed_state())
        vna.apply(
            start_frequency=sc.Quantity(5.9, "GHz"),
            stop_frequency=sc.Quantity(6.1, "GHz"),
            points=401,
        )
        trace = vna.sweep()
```

Typed physical references retain project-owned instrument identity and bind a
statically known client inside the daemon-owned session. Generated keyword
signatures keep property names, concrete Python value types, and explicit field
presence correlated; reusable generated patches remain available when a state
transition should be composed or passed around. Acquisition clients return
complete named readback fields on success. A rejected collection raises
`InstrumentCollectFailure` with the original receipt and whether non-execution
is known or the outcome is indeterminate; the lower-level channel still returns
the receipt directly. `MeasurementUnavailable` remains a valid field value when
the acquisition succeeded but a measurement itself was unavailable. The
lower-level member catalog continues to carry
interface, component, and member identity for drivers and experiment lowering.

Read-only declarations also return named state instead of forcing callers to
decode property ids. A temperature client exposes `observation()` for the
session-opening cached `TemperatureReadoutObservation` and
`refresh_observation()` for an explicit device read; `observed_state()` and
`refresh()` remain the raw snapshot escape hatch.

Experiment modules use generated symbolic targets from the same concrete
interface schema. Target fields accept either fixed values or typed Scopecat
value references:

```python
from typing import Annotated

import scopecat as sc
from scopecat_instruments import dc_source

DC_BIAS = sc.coordinate(
    "dc_bias",
    sc.ScalarType(sc.QuantityType(unit="V")),
)

@sc.module(id="capture")
def capture(
    module: sc.ModuleContext,
    dc_bias: Annotated[
        sc.Input[sc.Quantity],
        sc.QuantityType(unit="V"),
    ],
) -> None:
    flux = dc_source(module, "flux")
    flux.source_voltage(
        range=sc.Quantity(1, "V"),
        level=dc_bias,
    )
    flux.ensure(output_enabled=True)
```

`@module` is an optional extraction boundary for work that is genuinely reused
or composed. A one-off root template can instantiate the same symbolic clients
directly, as shown in the
[instrument-control guide](../../docs/instrument-control.md) and the
[flux-spectroscopy workflow](../../examples/instruments/src/instrument_demo/workflows/flux_spectroscopy.py).

The verb carries the distinction: `source_voltage(...)` records an ordered
mode/range/level transition, `apply(...)` updates persistent state now, and
`ensure(...)` makes persistent fields true at each experiment point.
Unspecified state fields are preserved, while coordinate- and parameter-backed
arguments resolve per point.

The context manager opens a durable daemon-owned session and closes it on exit.
Runs and interactive sessions compete for the same exclusive resource claim.
Consequential calls retain their replay identity automatically while retrying a
transient transport failure.

## Typed client source generation

Decorated Python interface declarations are the shared source for the wire
contract and typed Python surfaces. `PACKAGE_MANIFEST` is the authoritative list
of generated interfaces/composites, public types, provider identity, and lazy driver
registrations; both the generator and provider derive their catalogs from it.
The committed output covers complete `TemperatureReadout`, `RFOutput`, and
`NetworkSweep` families plus source-only and source-with-monitor `DCSource` live,
symbolic single-entity, and group clients.

One generation pass writes the six public runtime modules—`clients.py`,
`members.py`, `interfaces.py`, `states.py`, `driver_states.py`, and
`driver_handlers.py`—plus the typed, lazy package facade. Client acquisition and
observation descriptors, member refs, state projection layouts, and wire specs
are static generated data, so importing these modules does not compile interface
declarations. Interface factories parse generated JSON into a fresh
`InterfaceSpec`.

Writable interfaces receive sparse concrete `TypedDict` patches and exact
canonical snapshot encoders. Generated adapters own the worker's generic
request/ref ABI; a composite adapter accepts one validated batch and calls the
concrete driver once with one typed composite patch. Observed-only state generates
snapshot and acquisition hooks but no artificial writable patch. DC source
protection and output form one flat persistent state; the reported source mode
is read-only observation, while typed `source_voltage(...)` and
`source_current(...)` operations carry the required range and level.

Run the generator from the repository root after changing a supported
declaration, and use its check mode in validation or CI:

```console
uv run --locked python scripts/generate_instrument_clients.py
uv run --locked python scripts/generate_instrument_clients.py --check
```

Do not edit those modules or the package facade directly. The generated source
includes nested component operation proxies for supported declarations. A live
operation accepts concrete arguments and returns `InvokeReceipt`; the scalar
symbolic form projects each concrete `T` argument to `T | ValueRef` and adds an
`effect_id`. Its group form accepts a scalar or `PerEntity` value
independently for every argument, performs exact
identity joins for all mappings before recording any effect, and then records
one scalar invocation per entity. Mapping order is therefore irrelevant, while
missing or extra entity identities fail before partial effects are created.

The optional `DCSource`/`DCMonitor` composition is package presentation metadata
over two existing wire interfaces. The generator emits the explicit
`dc_source_monitor(...)` family instead of a boolean facade with union return
types. Group state and operation arguments still accept broadcasts or
`PerEntity` mappings with exact identity joins.

Payload-bearing operations are currently rejected only by the client source
generator, until their schema-specific live and symbolic carriers are defined.
The declaration compiler and generated driver handlers already support decoded
payload operations. Component-owned state and component acquisitions also remain
outside the generated client surface.

## Driver authoring

The shortest driver workflow is:

1. Declare state/results and a `Protocol` or ABC with the decorators in
   `interface_declarations.py`.
2. Register any new surface and the lazy driver implementation in
   `PACKAGE_MANIFEST`.
3. Run `uv run --locked python scripts/generate_instrument_clients.py`.
4. Subclass the generated adapter and implement its typed hooks.

For example, an RF implementation handles Python field names rather than member
refs or generic requests:

```python
from typing import override

from scopecat.sdk.instruments import DriverOutcome, DriverSuccess
from scopecat_instruments.driver_handlers import (
    RFOutputDriverAdapter,
    RFOutputDriverSnapshot,
)
from scopecat_instruments.driver_states import RFOutputDriverPatch


class MyRfSource(RFOutputDriverAdapter):
    instrument_id: str

    @override
    def read_rf_output_state(self) -> RFOutputDriverSnapshot:
        return RFOutputDriverSnapshot(state=self._read_hardware_state())

    @override
    def apply_rf_output_state(
        self,
        patch: RFOutputDriverPatch,
        /,
    ) -> DriverOutcome[None]:
        if "frequency" in patch:
            self._set_frequency(patch["frequency"])
        return DriverSuccess(None)
```

The adapter supplies `read_state`, `apply_state`, `invoke`, and `collect` at the
worker boundary; the implementation supplies device policy plus normal
description and lifecycle methods. All four real and four virtual first-party
drivers use this pattern.

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
  "run_start": "apply_default_state"
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
  "run_start": "preserve"
}
```

Every run first synchronizes the device. `preserve` retains that observed
state; `apply_default_state` then applies the saved partial public state.
Unspecified and private driver settings remain untouched.

Driver snapshots contain complete public physical state. Experiment entity and
channel bindings are routing provenance, not fields a driver reads back.

The DC monitor exposes `measure_current()` and `measure_voltage()` as separate
fixed acquisitions. A concrete driver rejects the call at runtime when its
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

## Driver tests

The worker exchanges generic `DriverState`, `DriverStatePatch`,
`DriverOperation`, `DriverAcquisition`, and `DriverReadback` values with generated
adapters. A concrete driver receives typed patches or composite patches, decoded
operation arguments, and one fixed hook per acquisition, and returns complete
typed snapshots or readbacks inside `DriverSuccess`, `DriverRejected`, or
`DriverUnknown`. Adapters own generic envelopes and ref mapping; SCPI sequencing,
temporary output or measurement changes, hardware-profile checks, and
device-specific validation remain driver policy.

Transcript helpers live in the explicit testing module:

```python
from scopecat_instruments.testing import ScriptedExchange, ScriptedTransport
```

`ScriptedTransport` asserts an ordered command/response transcript and verifies
that every expected exchange was consumed.
