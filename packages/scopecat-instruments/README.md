# Scopecat instrument provider

`scopecat-instruments` supplies Scopecat's config-driven provider for a focused
set of real and virtual laboratory instruments. Device access is owned by the
project daemon so notebooks, the GUI, and experiment runs share the same
exclusive leases, interface validation, operation receipts, and audit trail.

The configured connection kinds are:

- `virtual`, for an in-process simulated device selected by `driver_id`;
- `tcpip_socket`, for a configured host, port, and timeout.

## Notebook use

Use the project connection's `lab.instruments` API. An experiment run is not
required for direct instrument work:

```python
import scopecat as sc

with sc.open_project(".").connect(operator="alice") as lab:
    for item in lab.instruments.list().items:
        print(item.spec.id, item.availability)

    with lab.instruments.open("readout-vna") as vna:
        print(vna.describe())
        print(vna.read_state())
        vna.apply(
            "scopecat.network_sweep/v1",
            start_frequency=sc.Quantity(5.9, "GHz"),
            stop_frequency=sc.Quantity(6.1, "GHz"),
            points=401,
        )
        trace = vna.collect(
            "scopecat.network_sweep/v1",
            "sweep",
            "frequency",
            "s_parameter",
        )
```

The context manager opens a renewable daemon-owned session and closes it on
exit. Runs and interactive sessions compete for the same instrument lease.
Consequential calls accept an explicit `operation_id` when a caller needs to
retry the same logical operation.

## Configuration

Virtual instrument:

```json
{
  "id": "flux",
  "driver_id": "scopecat.virtual.dc_source",
  "connection": {
    "kind": "virtual"
  },
  "run_preparation": {
    "kind": "apply_defaults",
    "properties": [
      {
        "interface_id": "scopecat.dc_source/v2",
        "property_id": "source_mode",
        "value": "voltage"
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
    ]
  }
}
```

TCP/IP instrument:

```json
{
  "id": "readout-lo",
  "driver_id": "scopecat.rohde_schwarz.sgs100a",
  "connection": {
    "kind": "tcpip_socket",
    "host": "192.0.2.10",
    "port": 5025,
    "timeout_seconds": 5
  },
  "run_preparation": {
    "kind": "preserve"
  }
}
```

Every run first synchronizes the device. `preserve` retains that observed
state; `apply_defaults` then applies declared interface properties. It does not
perform a factory reset.

Connection `options` are intentionally narrow:

- Yokogawa GS200: `monitor_option` (`bool`, default `false`);
- Keysight E5080B: `channel` and `measurement` (positive integers, default `1`);
- the other included drivers accept no options.

The package supports these driver IDs:

| Driver ID | Interface |
| --- | --- |
| `scopecat.yokogawa.gs200` | `scopecat.dc_source/v2`; optional `scopecat.dc_monitor/v1` |
| `scopecat.rohde_schwarz.sgs100a` | `scopecat.rf_output/v1` |
| `scopecat.lakeshore.372` | `scopecat.temperature_readout/v1` |
| `scopecat.keysight.e5080b` | `scopecat.network_sweep/v1` |
| `scopecat.virtual.rf_source` | `scopecat.rf_output/v1` |
| `scopecat.virtual.dc_source` | `scopecat.dc_source/v2`, `scopecat.dc_monitor/v1` |
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
