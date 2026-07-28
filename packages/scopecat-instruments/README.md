# Scopecat instrument provider

`scopecat-instruments` supplies Scopecat's config-driven provider for a focused
set of real and virtual laboratory instruments. Device access is owned by the
project daemon so notebooks, the GUI, and experiment runs share the same
exclusive leases, capability validation, operation receipts, and audit trail.

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
            "network_sweep",
            start_frequency=sc.Quantity(5.9, "GHz"),
            stop_frequency=sc.Quantity(6.1, "GHz"),
            points=401,
        )
        trace = vna.collect("network_sweep", "frequency", "s_parameter")
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
  }
}
```

Connection `options` are intentionally narrow:

- Yokogawa GS200: `monitor_option` (`bool`, default `false`);
- Keysight E5080B: `channel` and `measurement` (positive integers, default `1`);
- the other included drivers accept no options.

The package supports these driver IDs:

| Driver ID | Capability |
| --- | --- |
| `scopecat.yokogawa.gs200` | DC source state and optional monitor readback |
| `scopecat.rohde_schwarz.sgs100a` | CW RF source state |
| `scopecat.lakeshore.372` | Read-only temperature and heater telemetry |
| `scopecat.keysight.e5080b` | Linear S-parameter sweep and complex trace |
| `scopecat.virtual.rf_source` | Virtual CW RF source |
| `scopecat.virtual.dc_source` | Virtual DC source |
| `scopecat.virtual.temperature_monitor` | Virtual temperature monitor |
| `scopecat.virtual.vna` | Virtual network analyzer |

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
