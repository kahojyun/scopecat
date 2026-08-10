# Experiment authoring dataflow

Experiment authors describe one dataflow. They do not choose a compute engine,
postprocessor phase, or storage representation. Scopecat places each operation
at the earliest stage where all of its inputs are available, and the value
returned by the experiment defines the ordinary durable result.

## Think in availability and shape

Two independent properties explain the authoring model:

| Property | Question | Examples |
| --- | --- | --- |
| Availability | When does the value exist? | input, parameter, scan point, acquired measurement |
| Shape | What exists at one point? | scalar, fixed array, ragged array |

`ScalarType` therefore means “one value at one logical point.” It does not mean
“host-only,” “small,” or “not recordable.” `ArrayType` means that one logical
point carries an array with declared dtype, unit, and local dimensions. Both can
flow through `compute(...)` and both can become durable experiment outputs.

`compute(...)` uses its inputs to choose execution placement:

- literals, runtime inputs, parameters, and scan coordinates produce a symbolic
  value and run in the normal host value graph;
- acquired or domain-produced measurements produce a logical product and run
  point-locally after those measurements arrive;
- mixing pre-measurement values and measurement products in one call is not yet
  supported; capture the former in the function closure or make the required
  join explicit at a higher layer.

The return type follows availability, not shape. Authors normally receive a
`ValueRef` before measurement and a `ProductRef` after measurement, but they do
not construct either type themselves. A measured array is still a
`ProductRef`, while a precomputed array is still a `ValueRef`.

Measurement-dependent feedback cannot run earlier in the same invocation. If a
new scan point, instrument state, or compiled program depends on a measurement,
use a bounded adaptive stage so the completed measurement is a durable input to
the next invocation.

## Return the result you mean to keep

Returning a value, product, product bundle, dataclass, tuple, or `PerEntity`
tree from `@experiment` selects its recordable leaves automatically:

```python
from dataclasses import dataclass

import scopecat as sc
from scopecat_instruments import NetworkSweepProducts, network_sweep


@dataclass(frozen=True, slots=True)
class Spectrum:
    bias: sc.CoordinateRef[sc.Quantity]
    trace: NetworkSweepProducts


@sc.experiment
def spectrum(experiment: sc.ExperimentContext) -> Spectrum:
    bias = experiment.scan(
        "bias",
        start=sc.Quantity(-0.2, "V"),
        stop=sc.Quantity(0.2, "V"),
        points=21,
    )
    vna = network_sweep(experiment)
    return Spectrum(bias=bias, trace=vna.sweep())
```

The same logical handles select variables from the completed dataset:

```python
schema = spectrum().output
data = run.measurements()
trace = data.traces(schema.trace.s_parameter)
```

There is no parallel `*Records` dataclass to declare or maintain. Product
bundles keep their author-facing field names, and returned nested values receive
hierarchical record names. `RecordRef` remains available for the uncommon case
that one source is recorded more than once and the notebook must distinguish
the aliases.

Call `experiment.record(...)` only for recording policy that cannot be expressed
by the return structure: an explicit durable name, namespace, role override, or
metadata. Returning an already-recorded leaf does not select it twice.

## Keep the common input path short

Function parameters separate values that vary per invocation from Python values
that change the experiment structure:

```python
from typing import Annotated


@sc.experiment
def repeated(
    experiment: sc.ExperimentContext,
    shots: sc.Input[int] = 100,
    detuning: Annotated[
        sc.Input[sc.Quantity],
        sc.QuantityType(unit="MHz"),
    ] = sc.Quantity(0, "MHz"),
) -> object: ...
```

Plain scalar Python types infer their value schema. Use `Annotated` only when a
unit, bound, entity kind, payload schema, array shape, or table schema matters.
Persistent lab configuration remains a parameter rather than an input because
it has different ownership, review, and history semantics.

For the normal Cartesian point domain, `experiment.scan(...)` creates the
coordinate and adds its axis in one call. Use separate `coordinate`, `axis`,
`grid`, or `points` objects only when an invocation must edit the plan, axes are
shared externally, or the point cloud is sparse or correlated.

## Compute scalar and array data uniformly

A host calculation can return either shape and feed another compute:

```python
samples = experiment.compute(
    fn=make_window,
    inputs={"length": length},
    output_type=sc.ArrayType(
        dtype="float64",
        dimensions=(sc.ArrayDimension("sample", 128),),
        unit="ratio",
    ),
)
peak = experiment.compute(
    "peak",
    fn=lambda values: float(values.max()),
    inputs={"values": samples},
    output_type=sc.ScalarType(sc.FloatType()),
)
```

A named function supplies the default compute ID. Lambdas and repeated uses are
allocated as `compute`, `compute.2`, and so on; pass an explicit first argument
when that identity is part of a public data contract.

The same spelling accepts measured products. Native scalars or read-only NumPy
arrays are passed to the function, and its result becomes another recordable
product. A mapping of output names to types declares a structured measured
result. The internal execution model still has separate host and observation
stages, but that distinction is compiler-owned rather than a second authoring
API.

## Deliberate remaining boundaries

Some distinctions should stay visible because removing them would hide real
experiment semantics:

- runtime inputs and persistent parameters have different owners and lifecycle;
- scan coordinates describe the point domain, while local array dimensions
  describe data inside one point;
- measurement-dependent control requires a later adaptive stage;
- an explicit `record(...)` is recording policy, not ordinary dataflow.

Further convenience should be judged against complete experiments. The most
useful next candidates are typed structured compute schemas, output-type
inference from annotated functions, and a concise way to join measured products
with captured pre-measurement constants. None should introduce another kind of
value or another postprocessing API.
