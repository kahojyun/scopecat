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
  metric, classification, or structured fit summary. A fact retains an explicit
  schema or first-party scalar meaning; it is not an unlabelled JSON dump.
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
  its existing validation and acceptance lineage.

The analysis record is the manifest for this publication. Large datasets and
artifacts live as separate run content entries; the record stores typed
references. This keeps one atomic publication without embedding every payload
in one JSON record.

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

Column names in a native object remain the default durable IDs. Explicit
publication mappings may rename them once at the boundary and are recorded as
schema, rather than inferred differently by every downstream adapter.

There are three intentional outcomes:

1. lossless normalization into a first-party dataset;
2. an explicit projection chosen by the user, such as selecting scalar columns
   for a table view; or
3. exact preservation as an artifact when no lossless first-party mapping
   exists yet.

An unsupported native shape must not be flattened implicitly merely because a
dataframe conversion is available. Adding a first-party mapping requires a
round-trip contract and tests against the native library.

## Provenance and scope

The record identifies exact input snapshots and every published output. A
managed compute may add implementation, binding, codec, access, and content-hash
provenance, but ordinary library code does not need to become a managed compute
in order to publish results.

Views refer to outputs, proposals refer to their producing analysis, and future
relations should use stable output IDs rather than display titles or tuple
positions. Titles and labels remain presentation metadata.

Analysis currently belongs to one completed run. Live checkpoints, retries,
cross-run state, schedules, and recurring calibration belong to a future
workflow model. They should not be encoded as hidden state in an analysis or as
special run-sequence behavior before that workflow owner exists.
