# Experiment authoring dataflow

Experiment authors describe one dataflow. They do not choose a compute engine,
hidden execution phase, or storage representation. Scopecat places each
operation at the earliest stage where all of its inputs are available, and the
value returned by the experiment defines the ordinary durable result.

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
- a call that mixes the two runs after the measurements arrive and receives the
  earlier values joined by logical point.

The return type follows availability, not shape. Authors normally receive a
`ValueRef` before measurement and a `ProductRef` after measurement, but they do
not construct either type themselves. A measured array is still a
`ProductRef`, while a precomputed array is still a `ValueRef`.

Measurement-dependent feedback cannot run earlier in the same invocation. If a
new instrument state or compiled program depends on a measurement, use a
bounded run sequence so the completed measurement is a durable input to the
next invocation. Measurement-dependent points inside one executing run require
a separate adaptive point-plan abstraction.

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
result = run.result(spectrum().output)
trace = result.dataset.traces(result.output.trace.s_parameter)
```

For row-oriented fitting, load the complete returned schema once. The typed
result validates every leaf up front, and each point preserves the Python type
carried by its symbolic reference:

```python
observations = result.rows(
    lambda point: Observation(
        bias=point.value(result.output.bias),
        response=point.value(result.output.trace.response),
    )
)
```

Typed point access is strict: `point.value(...)` raises when that field is
unavailable. Filter deliberately before fitting when incomplete points are valid
input data:

```python
usable = result.where_available(
    result.output.bias,
    result.output.trace.response,
)
observations = usable.rows(build_observation)
```

With no arguments, `where_available()` requires every returned leaf. The
historical `run.result()` view offers the same operation with persisted paths.
Point-local compute uses the complementary rule: if any measured input is
unavailable, Scopecat does not call the kernel and propagates its reason and
metadata to every derived output. Filtering is therefore an explicit analysis
choice rather than a hidden acquisition policy.

This replaces independently loading columns, rejecting unavailable values, and
zipping them by position. Use `point.quantity(ref, "mV")` when a numeric leaf
should be converted to a requested unit.

Every new dataset also persists the experiment result contract itself. Historical
code can therefore inspect return paths without rebuilding the invocation that
created the run:

```python
result = run.result()
print(result.contract.id, result.contract.version, result.paths)
value = result[0].value("probabilities/probability_1")
```

`run.result(authored_output)` is the statically typed path when the originating
symbolic output is available. `run.result()` uses only the persisted contract and
is the durable historical interpretation boundary. Both expose their underlying
`dataset` for labeled slicing and ecosystem export; call `run.measurements()`
directly when the task starts from dataset variables rather than the experiment's
returned result.

There is no parallel `*Records` dataclass to declare or maintain. Product
bundles keep their author-facing field names, and returned nested values receive
hierarchical record names. These paths are the durable names: they do not change
when an internal product or compute operation is renamed. Repeating one source
at two return paths creates two aliases over the same product use. `PerEntity`
paths include both entity kind and identity.

The return tree is the ordinary durability and liveness boundary. Put explicit
names, namespaces, roles, and metadata beside returned fields rather than
adding an imperative selection call:

```python
from typing import Annotated


@dataclass(frozen=True, slots=True)
class Spectrum:
    bias: sc.CoordinateRef[sc.Quantity]
    trace: Annotated[
        NetworkSweepProducts,
        sc.Result(namespace="science", metadata={"reviewed": True}),
    ]
```

`Result(id=...)` names one leaf; `namespace`, `role`, and `metadata` can annotate
a complete nested subtree. Returning an already-recorded leaf does not select
it twice. `experiment.alias(...)` remains only for the uncommon case where one
source needs an additional dynamic durable destination; return the resulting
`RecordRef` when that alias is also part of the result contract.

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
    output_type=sc.ArrayType(
        dtype="float64",
        dimensions=(sc.ArrayDimension("sample", 128),),
        unit="ratio",
    ),
    length=length,
)


def peak_value(*, values) -> float:
    return float(values.max())


peak = experiment.compute(
    fn=peak_value,
    values=samples,
)
```

When a named function returns `bool`, `int`, `float`, or `str`, `compute`
infers the scalar output contract. Use an `Annotated` return with
`ScalarType(...)` or `ArrayType(...)` when units, bounds, dtype, or dimensions
matter. The annotation may be a reusable PEP 695 type alias, including payload
schemas used by hardware operations, so call sites do not repeat
`output_type=PayloadType(...)`. Inputs can be passed as named keywords;
`inputs={...}` remains useful when names are assembled dynamically.

The same annotations on function parameters are checked against every bound
`ValueRef` or `ProductRef` during authoring. Measurement units must match
exactly because native kernels receive numbers in the product's declared unit;
compatible-but-different units are not silently converted. Array contracts
also compare dtype, value unit, and each local dimension's ID, kind, unit, and
size. Leaving a parameter unannotated opts out when a generic kernel genuinely
accepts several schemas.

A named function supplies the default compute ID. Lambdas and repeated uses are
allocated as `compute`, `compute.2`, and so on; pass an explicit first argument
when that identity is part of a public data contract.

The same spelling accepts measured products. Native scalars or read-only NumPy
arrays are passed to the function, and its result becomes another recordable
product. An annotated product-bundle dataclass declares a typed structured
result once; `compute` returns that bundle directly, and the kernel can return a
tuple in field order:

```python
from dataclasses import dataclass
from typing import Annotated


@dataclass(frozen=True, slots=True)
class Probabilities(sc.ProductBundle):
    ground: Annotated[
        sc.DataRef[float],
        sc.ScalarType(sc.QuantityType(unit="ratio")),
    ]
    excited: Annotated[
        sc.DataRef[float],
        sc.ScalarType(sc.QuantityType(unit="ratio")),
    ]


@Probabilities.kernel
def discriminate(*, shots) -> tuple[float, float]: ...


probabilities = experiment.compute(
    fn=discriminate,
    shots=acquired.iq_shots,
)
```

Product identities are scoped below the compute identity, so repeated typed
computes only need distinct compute IDs. `ProductBundle.kernel` binds the native
tuple-, mapping-, or dataclass-returning kernel to that reusable symbolic result
schema once, so call sites do not repeat `output_type=...`. `DataRef` means that
each field follows
the compute's input availability: the same bundle schema produces `ValueRef`
fields on the host and `ProductRef` fields after acquisition. Host structured
compute is still one public compute; field projections in the scalar value graph
are compiler-owned. A mapping of names to types remains available for dynamic
schemas. The internal execution model still has separate host and observation
stages, but that distinction is compiler-owned rather than a second authoring
API.

Earlier values can be bound directly beside measured products; no closure or
parallel postprocessing API is required:

```python
classified = experiment.compute(
    fn=classify,
    trace=acquired.trace,
    threshold=threshold,
)
```

## Inspect placement and liveness before running

`lab.preview(...)` exposes the compiler's decision without leaking compiler IR:

```python
preview = lab.preview(spectrum())
for compute in preview.computes:
    print(
        compute.id,
        compute.placement,
        compute.implementation,
        compute.deterministic,
        compute.inputs,
        compute.outputs,
        compute.demanded_by,
    )

for binding in preview.bindings:
    print(binding.id, binding.kind, binding.owner, binding.origin)

for edge in preview.binding_edges:
    print(edge.source, edge.relation, edge.target)
```

Placement is either `host` (all inputs exist before acquisition) or
`observation` (at least one input is a measured product). `demanded_by` names
the returned record, downstream compute, payload, or experiment effect that
keeps the compute live. Observation computes absent from this list were removed
because no durable output or downstream compute needs them.

Saved dataset computes use the same `id`, `placement`, `implementation`,
`deterministic`, `inputs`, and `outputs` vocabulary in their
`AnalysisComputeExecution`. Their placement is `dataset`; content hashes and
full-versus-batch access remain execution facts specific to completed-data
analysis. A `python:` implementation is local and makes no replay promise, while
a `registry:` implementation identifies an explicit portable contract.

`bindings` gives runtime inputs, scan coordinates, and parameter dependencies
one common inspection shape without giving them one lifecycle. Its `owner`
states who may change the value: `invocation` for call-time inputs, `point-plan`
for coordinates, and `configuration` for persistent parameters. `origin`
explains whether an input used its default or an override and which scan form
supplied a coordinate. `binding_edges` represents parameter relationships with
typed `centers` and `overlays` edges, so consumers never need to parse strings
such as `scan-center:drive_frequency`.
The existing function arguments and scan declarations remain the authoring
API; this is a review vocabulary, not another binding DSL.

## Judge authoring against complete paths

Three executable reference paths are the acceptance baseline for authoring
changes:

- flux spectroscopy acquires point-local complex traces, returns one typed result,
  and reads and plots it without restating a measurement schema;
- DRAG calibration turns per-shot arrays into durable probabilities, binds the
  returned result for a dataset fit, and publishes one analysis outcome;
- candidate verification obtains a configuration from that saved analysis and
  runs an independent experiment without changing the accepted default.

A convenience is valuable when it removes a declaration or concept from one of
these paths while preserving typed shape, availability, result identity, and
configuration provenance. Internal generality that does not shorten a complete
path is not by itself an authoring feature.

## Deliberate remaining boundaries

Some distinctions should stay visible because removing them would hide real
experiment semantics:

- runtime inputs and persistent parameters have different owners and lifecycle;
- scan coordinates describe the point domain, while local array dimensions
  describe data inside one point;
- measurement-dependent configuration or program control requires a later run
  in a run sequence;
- an explicit `alias(...)` is an additional destination, not ordinary dataflow.

Further convenience should be judged against complete experiments. New
features should extend typed results, the shared compute model, or this
ownership vocabulary instead of introducing another kind of value or another
postprocessing API.
