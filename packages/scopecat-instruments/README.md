# Scopecat instrument provider

`scopecat-instruments` supplies Scopecat's config-driven provider for a focused
set of real and virtual laboratory instruments. Device access is owned by the
project daemon so notebooks, the GUI, and experiment runs share the same
exclusive claims, interface validation, operation receipts, and audit trail.

The configured connection kinds are:

- `virtual`, for a deterministic simulated device selected by `driver_id`;
- `tcpip_socket`, for a configured host, port, and timeout.

## Using the package

The [instrument-control guide](../../docs/instrument-control.md) is the canonical
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
patches and canonical snapshot encoders; generated adapters own generic worker
dispatch, wire conversion, and exact `PerEntity` joins.

One group `ensure(...)` remains a coherent state intent so routing can batch
channels that resolve to the same instrument. Group operations expand to scalar
invocations after validating every entity mapping, preventing partial effects
from a missing or extra identity. Composite client families are package
presentation metadata over existing wire interfaces.

The generator currently requires schema-specific client carriers before
exposing payload-bearing operations. The declaration compiler and driver
handlers already accept decoded payloads. Reusable instrument components compile
to nested interface members; resource routes mount root client members at their
physical `component_path`.

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

Driver snapshots contain complete public physical state. Experiment entity and
channel bindings are routing provenance, not fields a driver reads back.

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

## Driver tests

The worker exchanges generic `DriverState`, `DriverStatePatch`,
`DriverOperation`, `DriverAcquisition`, and `DriverReadback` values with generated
adapters. A concrete driver receives typed patches or composite patches, decoded
operation arguments, and one typed hook per acquisition, and returns complete
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
