# Scopecat instrument provider

`scopecat-instruments` supplies Scopecat's config-driven provider for a focused
set of real and virtual laboratory instruments. Device access is owned by the
project daemon so notebooks, the GUI, and experiment runs share the same
exclusive claims, interface validation, operation receipts, and audit trail.

The configured connection kinds are:

- `virtual`, for an in-process simulated device selected by `driver_id`;
- `tcpip_socket`, for a configured host, port, and timeout.

## Notebook use

Use the project connection's `lab.instruments` API. An experiment run is not
required for direct instrument work:

```python
import scopecat as sc
from scopecat_instruments.members import (
    NETWORK_SWEEP_ACQUISITION,
    NETWORK_SWEEP_FREQUENCY_RESULT,
    NETWORK_SWEEP_POINTS,
    NETWORK_SWEEP_S_PARAMETER_RESULT,
    NETWORK_SWEEP_START_FREQUENCY,
    NETWORK_SWEEP_STOP_FREQUENCY,
)

with sc.open_project(".").connect(operator="alice") as lab:
    for item in lab.instruments.list().items:
        print(item.instrument_id, item.availability)

    with lab.instruments.open("readout-vna") as vna:
        print(vna.describe())
        print(vna.observed_state())
        vna.apply(
            {
                NETWORK_SWEEP_START_FREQUENCY: sc.Quantity(5.9, "GHz"),
                NETWORK_SWEEP_STOP_FREQUENCY: sc.Quantity(6.1, "GHz"),
                NETWORK_SWEEP_POINTS: 401,
            }
        )
        trace = vna.collect(
            NETWORK_SWEEP_ACQUISITION,
            NETWORK_SWEEP_FREQUENCY_RESULT,
            NETWORK_SWEEP_S_PARAMETER_RESULT,
        )
```

The member catalog carries interface, component, and member identity together.
Public experiment authoring, Notebook, and driver call sites use these refs.
Specs and serialized IR lower them to raw ids.

The context manager opens a durable daemon-owned session and closes it on exit.
Runs and interactive sessions compete for the same exclusive resource claim.
Consequential calls accept an explicit `command_id` when a caller needs to
retry the same logical operation.

## Configuration

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
      "interface_id": "scopecat.dc_source/v2",
      "property_id": "source_mode",
      "value": "voltage"
    },
    {
      "interface_id": "scopecat.dc_source/v2",
      "property_id": "voltage_range",
      "value": {
        "value": 1,
        "unit": "V"
      }
    },
    {
      "interface_id": "scopecat.dc_source/v2",
      "property_id": "voltage_level",
      "value": {
        "value": 0,
        "unit": "V"
      }
    },
    {
      "interface_id": "scopecat.dc_source/v2",
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

The DC monitor acquisition is selected by DC source mode: voltage-source mode
returns monitored current, while current-source mode returns monitored voltage.

Connection `options` are intentionally narrow:

- Yokogawa GS200: `monitor_option` (`bool`, default `false`);
- Keysight E5080B: `channel` and `measurement` (positive integers, default `1`);
- the other included drivers accept no options.

The package supports these driver IDs:

| Driver ID | Interface |
| --- | --- |
| `scopecat.yokogawa.gs200` | `scopecat.dc_source/v2`; optional `scopecat.dc_monitor/v2` |
| `scopecat.rohde_schwarz.sgs100a` | `scopecat.rf_output/v1` |
| `scopecat.lakeshore.372` | `scopecat.temperature_readout/v1` |
| `scopecat.keysight.e5080b` | `scopecat.network_sweep/v1` |
| `scopecat.virtual.rf_source` | `scopecat.rf_output/v1` |
| `scopecat.virtual.dc_source` | `scopecat.dc_source/v2`, `scopecat.dc_monitor/v2` |
| `scopecat.virtual.temperature_monitor` | `scopecat.temperature_readout/v1` |
| `scopecat.virtual.vna` | `scopecat.network_sweep/v1` |

The real-device implementations are deliberately minimal. Verify firmware,
installed options, limits, cabling, and interlocks for the specific laboratory
before enabling hardware outputs.

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

Transcript helpers live in the explicit testing module:

```python
from scopecat_instruments.testing import ScriptedExchange, ScriptedTransport
```

`ScriptedTransport` asserts an ordered command/response transcript, while
`RecordingTransport` records traffic around another test transport.
