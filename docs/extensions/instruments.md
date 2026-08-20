# Extend instruments

The `scopecat-instruments` package demonstrates the supported provider pattern:
interface declarations define typed capabilities, generated live and symbolic
clients expose them to notebooks and experiments, and drivers implement the
capability without receiving run or dataset concepts.

An interface author declares portable members directly on a Python `Protocol`
or abstract base class. A distinct acquisition adds one decorated result
dataclass:

```python
from typing import Protocol

from scopecat import Quantity
from scopecat.sdk.instruments import Member
from scopecat.sdk.instruments.declarations import (
    acquisition,
    axis,
    instrument_interface,
    instrument_result,
    member,
    result_field,
)


@instrument_result
class NetworkSweepResults:
    frequency: list[float] = result_field(
        role="coordinate", dtype="float64", unit="Hz", axes=("frequency",)
    )
    s_parameter: list[complex] = result_field(
        dtype="complex128", unit="ratio", axes=("frequency",)
    )


@instrument_interface("example.network_sweep/v1")
class NetworkSweep(Protocol):
    start_frequency: Member[Quantity] = member(
        access="read_write", restore=True, unit="Hz"
    )
    stop_frequency: Member[Quantity] = member(
        access="read_write", restore=True, unit="Hz"
    )
    points: Member[int] = member(access="read_write", restore=True, minimum=2)
    s_parameter: Member[str] = member(access="read_write", restore=True)

    @acquisition(axes={"frequency": axis(size=points, unit="Hz")})
    def sweep(self) -> NetworkSweepResults: ...
```

Members are independently queryable and cacheable state facts. Generated sparse
patch and target carriers represent omission. Result declarations own
measurement roles and axes. Generation produces the wire contract, typed
clients, member references, state projections, and measurement-valued driver
observation carriers.

A driver subclasses `ObjectInstrumentDriver` and binds typed methods to member
declarations with `@read`, `@write`, `@query`, or `@update`. The base class
handles dispatch and wire conversion; the driver owns command ordering, device
limits, temporary setup and restoration, and response interpretation. A true
operation or acquisition is attached to its interface declaration with
`@implements(...)`; acquisition methods return their generated class from
`scopecat_instruments.driver_observations`. Class creation rejects missing,
duplicate, or signature-incompatible behavior bindings.

When the values to record are already members, declare an `observation(...)`
on those members instead of repeating their schema in a result dataclass. The
framework performs a fresh coherent state read and records it as acquisition
products. Reserve `@acquisition` for a distinct measurement procedure, arrays,
or acquisition-specific failure and evidence.

Model-specific background state belongs on the concrete driver as a
`device_member(...)`; it can be captured or restored without inventing a
single-device portable interface. An operation that disturbs persistent state
lists the affected members in `invalidates`; a later `ensure` establishes a new
guarantee.

Use the package's source-adjacent guides for the exact extension workflow:

- [driver authoring](https://github.com/scopecat-project/scopecat/blob/main/packages/scopecat-instruments/README.md#driver-authoring)
- [typed client source generation](https://github.com/scopecat-project/scopecat/blob/main/packages/scopecat-instruments/README.md#typed-client-source-generation)
- [configuration](https://github.com/scopecat-project/scopecat/blob/main/packages/scopecat-instruments/README.md#configuration)
- [testing](https://github.com/scopecat-project/scopecat/blob/main/packages/scopecat-instruments/README.md#testing)

The [instrument control guide](../how-to/control-instruments.md) shows the
resulting live and symbolic user experience. Keep driver-specific command and
transport details beside their code; only cross-cutting user concepts belong in
the main documentation site.
