# Analysis publication

Analysis replaces the run-adjacent scripts and personal file layouts that turn
measurements into fitted values, reusable datasets, plots, reports, and proposed
parameter changes. It is an atomic publication attached to one source run. It is
not a dataframe API, a compute runtime, or a multi-run workflow engine.

Users should keep doing numerical work with NumPy, pandas, Polars, Xarray,
PyArrow, SciPy, and domain libraries. Scopecat owns the durable boundary after
that work: identities, scientific meaning needed to interpret an output,
relations between outputs, content hashes, provenance, and attachment to the
run.

## Durable output ontology

Every output has a stable, analysis-local `id`. An analysis publishes five
kinds of output:

- **Fact** is a small typed conclusion, such as a fitted resonance, quality
  metric, classification, or structured fit summary. Scalars and quantities
  use first-party schemas. A structured fact requires an `AnalysisFactSchema`
  that validates its canonical JSON shape; it is not an unlabelled JSON dump.
- **Dataset** is reusable structured scientific data. Its durable schema retains
  column identities, physical types, nulls, units, coordinates, and the native
  metadata that can be represented without ambiguity.
- **Artifact** is an exact file or byte sequence, such as a report, native Xarray
  store, model checkpoint, image, or vendor format. It retains a filename, media
  type, content hash, and producer rather than depending on a user's directory
  convention.
- **View** is a bounded table or figure projection for inspection. A view refers
  to its source fact or dataset by output ID and may retain a preview cache. The
  cache is presentation, not another authoritative scientific result.
- **Proposal** is a decision output that proposes parameter changes and retains
  its validation and acceptance lineage. It may cite authoritative fact,
  dataset, or artifact outputs from the same analysis as structured evidence.

The analysis record is the manifest for this publication. Large datasets and
artifacts live as separate run content entries; the record stores typed
references. This keeps one atomic publication without embedding every payload
in one JSON record.

## Logical keys and immutable revisions

The author supplies one logical analysis `key`, not a version number. The first
publication uses `analysis-<key>`. Repeating the same logical content is an
idempotent notebook or step retry and returns that existing publication. If any
input snapshot, output content, title, metadata, or other durable meaning
changes, Scopecat appends `analysis-<key>-r2`, then `-r3`, without replacing the
earlier record.

Datasets, artifacts, and parameter proposals use the allocated analysis record
ID as part of their durable identity, so a revision never leaves a supposedly
immutable payload pointing at overwritten content. Proposal timestamps are not
part of logical content identity: rebuilding the same proposal in a later
notebook execution resolves to the already-published proposal and its original
timestamp.

Reading by logical key returns the latest revision. Reading by an exact analysis
record ID returns that historical revision. `PublishedAnalysis.revision` and
`publication_hash` expose the allocated revision and the content identity when
code needs to report or compare them; ordinary authoring code does not manage
either value.

`Analysis.save()` and `run.analyze(...)` return that same `PublishedAnalysis`
handle after persistence. There is no separate immediate outcome model: code run
in the publishing cell and code run after reopening the project use the same
typed output access and load parameter proposals from the same durable records.

## Conversion policy

Adapters may perform an automatic conversion only when Scopecat can preserve
the source semantics required to reconstruct or faithfully expose the data. In
particular, an adapter must not silently discard or reinterpret:

- numeric width, complex values, timestamps, categorical values, or extension
  types;
- the distinction between null, unavailable, and absent;
- index and coordinate identity, order, dimensions, shapes, or variable roles;
- units and other scientific field metadata;
- column identity when a library requires names to be rewritten.

Column names in a native object remain the default durable IDs. A sparse
`fields={source_name: AnalysisField(...)}` publication mapping may rename them
once at the boundary and assign role, unit, and label together. The durable
schema records both source names and stable IDs rather than letting every
downstream adapter infer them differently. `AnalysisField.unit` is the durable
target unit, matching its meaning for typed table rows. A source field with a
known compatible unit is numerically converted; a field without unit metadata
treats it as the author's explicit declaration. Incompatible units and units on
non-numeric fields are rejected rather than relabeling values silently.

There are three intentional outcomes:

1. lossless normalization into a first-party dataset;
2. an explicit projection chosen by the user, such as selecting scalar columns
   for a table view; or
3. exact preservation as an artifact when no lossless first-party mapping
   exists yet.

An unsupported native shape must not be flattened implicitly merely because a
dataframe conversion is available. Adding a first-party mapping requires a
round-trip contract and tests against the native library.

### Native dataset contract

The first-party adapter intentionally supports a small, explicit matrix:

| Source | Accepted boundary | Durable guarantees | Explicit limit |
| --- | --- | --- | --- |
| PyArrow | A `Table` with unique, non-empty field names | Arrow types, nulls, nested column values, schema metadata, and recognized role/unit/label metadata | A table view must deliberately select scalar columns; nested values are not stringified |
| pandas | A two-dimensional `DataFrame` with string column names | Values enter the same Arrow schema; categorical, timezone, and nullable numeric identities remain durable there; meaningful indexes become coordinate columns | The default `RangeIndex` is dropped; index/column collisions and non-string columns are rejected |
| Polars | A `DataFrame` through its Arrow representation | Column order, Arrow-representable physical types, nulls, and explicit `AnalysisField` semantics | Polars-only metadata with no Arrow representation is not promised |
| Xarray | Exactly one named dimension, with every coordinate and data variable using that dimension | Coordinate roles, physical dtypes, dimension identity, and finite JSON dataset/variable attributes round-trip | Multi-dimensional, scalar-mixed, or multi-index layouts must be projected deliberately or stored as artifacts |
| Annotated rows | A non-empty homogeneous sequence of dataclass rows with `Annotated[..., AnalysisField(...)]` fields | The annotation supplies stable field ID, role, label, and target unit; `Quantity` values are converted once and the selected values enter Arrow without a dataframe adapter | Unannotated fields are private implementation details and are omitted; empty or mixed row types have no inferable durable schema |
| NumPy | Arrays inside an explicitly named dataframe/Xarray field | The owning container supplies field identity and topology | A bare ndarray is not a dataset because it has no durable field names or coordinate meaning |

Annotated rows use the same projector as `AnalysisTable.from_objects(...)`, but
dataset publication is not constrained by the bounded table-preview row limit.
Because the dataclass already owns its field semantics, a second `fields=`
mapping is rejected. Authors can publish the rows directly and let a table or
figure refer to that durable dataset by output ID.

`DerivedDataset.to_pandas()` defaults to familiar pandas/NumPy dtypes. Use
`dtype_backend="pyarrow"` when nullable integer and other exact Arrow dtype
identity matters more than NumPy-native behavior. This choice affects only the
in-memory pandas view; the durable dataset always retains its Arrow schema.

## Provenance and scope

The record identifies exact input snapshots and every published output. A
traced analysis execution may additionally retain implementation, named input
bindings, codecs, access mode, and the content identities of its named results.
Use `context.trace(...)` only when that execution evidence or bounded batch
access is valuable; ordinary library code does not need a wrapper in order to
publish results.

Executions and outputs are intentionally separate. Calling `trace(...)` returns
the native Python value and appends execution evidence to the analysis record;
it does not decide that the value is a durable user-facing output. Facts,
datasets, tables, figures, artifacts, and proposals remain explicit publication
choices. When an explicitly published fact, dataset, or artifact has exactly
the traced result's content and codec identity, it records `produced_by`
automatically. Applying the first-party dataset adapter with field mappings or
a different pandas index policy instead records `derived_from`, including the
source execution output and adapter arguments. Authors therefore do not pass
provenance handles through their numerical code, while the record still
distinguishes exact production from normalization. Views identify their
published source dataset; their projection is analysis authoring, not the
traced numerical result itself.

A parameter proposal may add `evidence=("selected-fit", "fit-quality")` to cite
authoritative outputs already published by the same analysis builder. The
proposal stores those analysis-local output IDs, so review can navigate to the
exact durable facts, datasets, or artifacts behind the change. Table and figure
views are deliberately not evidence targets because their previews are bounded
presentation caches; cite their source dataset instead. This is a shallow
publication relation, not a general-purpose analysis DAG.

An `AnalysisExecutionOutput` retains a named codec and content hash, not the
intermediate value itself. It is audit evidence and a provenance target, not a
cache, checkpoint, or replay promise. Only explicitly published facts, datasets,
and artifacts are durable content. Reusable intermediate caching would also
need code and environment identity and therefore belongs to a later execution
design rather than being implied by `trace(...)` today.

A registered implementation may expose several meaningful leaves from one
native result instead of forcing the result into one JSON blob. The function
still returns its ordinary dataclass, mapping, or sequence. `outputs` assigns a
stable result name to an attribute/key path; each selected leaf gets its own
kind, codec, content hash, and provenance identity:

```python
@dataclass(frozen=True)
class FitResult:
    resonance: float
    quality: float
    residuals: pd.DataFrame


@computes.implementation(
    "resonator.fit",
    "1",
    outputs={
        "resonance": "resonance",
        "quality": "quality",
        "residuals": "residuals",
    },
)
def fit(*, dataset: Dataset) -> FitResult: ...


fit_result = context.trace(id="fit", fn=fit, dataset=measurements)
analysis = (
    context.result("Fit review")
    .fact("resonance", fit_result.resonance)
    .fact("quality", fit_result.quality)
    .dataset("residuals", fit_result.residuals)
)
```

A string path selects one mapping key or attribute. A tuple such as
`("residuals", 0)` traverses nested keys/attributes and sequence positions.
Output names are durable provenance names, while result paths are only the
adapter from the function's native return type. Root output encoders and named
leaf outputs are mutually exclusive because one root codec cannot describe the
independent identities of several leaves.

The result-path declaration intentionally does not prescribe publication kind
or bulk-publish every leaf. First-party scalar and structured JSON values,
native datasets, and bytes or file paths determine execution-result identity;
the later `fact(...)`, `dataset(...)`, or `artifact(...)` call remains the
explicit durable interface. A richer result-spec abstraction should be added
only when a real non-inferable durable type needs it, rather than duplicating
publication metadata in the compute registry now.

Facts, datasets, and artifacts link to the one matching named result
automatically. If two named results intentionally have identical content,
content identity alone cannot choose one; pass `source=("fit", "quality")` at
the publication boundary to disambiguate. For a dataset, the same source
override works whether the final relation is exact `produced_by` or adapter-
backed `derived_from`; Scopecat determines that from the identities instead of
asking the user to choose a provenance relation.

Returning `bytes` or a file `Path` from `trace(...)` records an artifact result
by the exact byte identity. Publishing those bytes with `artifact(...)` links
the durable run artifact to that execution while filename and media type remain
publication metadata. Returning text remains a normal value; encoding text to
file bytes is a conversion rather than an exact artifact result.

Experiment `compute(...)` is a different lifecycle: it is a node in the formal
experiment program and may run before or during acquisition. Analysis
`trace(...)` is an optional record of ordinary eager code over a run snapshot.
They may share implementation descriptors, codec contracts, and provenance
machinery without sharing one authoring concept or placement model.

Views refer to datasets, and proposals may refer to authoritative outputs inside
their producing analysis. Future relations should likewise use stable output IDs
rather than display titles or tuple positions. Titles and labels remain
presentation metadata.

## Structured fact contract

A structured fact has a versioned domain `schema_id`, an explicit Scopecat
`schema_codec`, a fingerprint of that codec's structural schema, and canonical
JSON content. The schema ID says what the conclusion means; the codec defines
how its shape is described; the fingerprint detects accidental reuse of that ID
for a different shape. The durable record deliberately does not contain a
Python module or import path.

The first structural codec owns a deliberately small JSON type system: null,
boolean, integer, float, string, literal, union, array, tuple, string-keyed
mapping, object, and quantity. Dataclass and Pydantic types are local validation
and reconstruction adapters for that type system. Python class names,
docstrings, default values, Pydantic's generated JSON Schema, and
`AnalysisField` projection metadata do not affect the fingerprint. This keeps a
refactor or dependency upgrade from creating a false schema change while still
making a real field or type change visible.

Define the local type and its schema descriptor together, then reuse the
descriptor for publication and typed reading:

```python
@dataclass(frozen=True, slots=True)
class ResonatorFit:
    resonance: sc.Quantity
    quality: float


RESONATOR_FIT_SCHEMA = sc.AnalysisFactSchema(
    "lab.resonator-fit.v1",
    ResonatorFit,
)

analysis = context.result("Fit review").fact(
    "selected-fit",
    fit,
    schema=RESONATOR_FIT_SCHEMA,
)

published = run.published_analysis("fit-review")
fit = published.fact_as("selected-fit", RESONATOR_FIT_SCHEMA)
```

`fact_as(...)` checks the schema ID, structural codec, and fingerprint before
reconstructing the caller's dataclass or Pydantic model. Changing the durable
shape requires a new versioned schema ID. Scopecat does not maintain a global
Python type registry or import application types while reopening a run; code
that only needs generic inspection can continue to use `fact(...)` and read its
JSON value directly.

Analysis currently belongs to one completed run. Live checkpoints, retries,
cross-run state, schedules, and recurring calibration belong to a future
workflow model. They should not be encoded as hidden state in an analysis or as
special run-sequence behavior before that workflow owner exists. Future
streaming analysis may reuse the same execution and publication primitives, but
its cursors, windows, checkpoint state, and finalization policy belong to that
workflow rather than to the analysis record.
