# Extend instruments

The `scopecat-instruments` package demonstrates the supported provider pattern:
interface declarations define typed capabilities, generated live and symbolic
clients expose them to notebooks and experiments, and drivers implement the
capability without receiving run or dataset concepts.

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
roles and axes. Generation produces the wire contract, typed clients, member
references, state projections, and driver adapters.

A driver subclasses the generated adapter and implements typed hooks. The
adapter handles dispatch and wire conversion; the driver owns command ordering,
device limits, temporary setup and restoration, and response interpretation.
An operation that disturbs persistent state lists the affected property refs in
`invalidates`; a later `ensure` establishes a new guarantee.

Use the package's source-adjacent guides for the exact extension workflow:

- [driver authoring](https://github.com/kahojyun/scopecat/blob/main/packages/scopecat-instruments/README.md#driver-authoring)
- [typed client source generation](https://github.com/kahojyun/scopecat/blob/main/packages/scopecat-instruments/README.md#typed-client-source-generation)
- [configuration](https://github.com/kahojyun/scopecat/blob/main/packages/scopecat-instruments/README.md#configuration)
- [testing](https://github.com/kahojyun/scopecat/blob/main/packages/scopecat-instruments/README.md#testing)

The [instrument control guide](../how-to/control-instruments.md) shows the
resulting live and symbolic user experience. Keep driver-specific command and
transport details beside their code; only cross-cutting user concepts belong in
the main documentation site.
