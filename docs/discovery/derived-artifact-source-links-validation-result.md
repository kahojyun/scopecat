# Derived Artifact Source Links Validation Result

## Status

Implementation candidate validated.

This result validates a narrow Measurement Records slice: **Derived Artifact
Source Links**.

It does not accept an artifact parser, source observer, checksum contract,
storage writer, schema inference engine, recursive relation traversal,
analysis-DAG inference, scientific validity review, artifact GUI, or shared
measurement-record schema.

## Fixture

Fixture:
[`../../tests/fixtures/derived_artifact_source_links/basic_artifact_links/`](../../tests/fixtures/derived_artifact_source_links/basic_artifact_links/)

Implementation candidate:
[`../../implementation_candidates/derived_artifact_source_links/`](../../implementation_candidates/derived_artifact_source_links/)

The fixture records one derived artifact from an explicit artifact-link
manifest:

- one declared-available Rabi fit summary artifact;
- one declared-available primary input measurement;
- one unavailable comparison-reference measurement;
- direct source roles and relations only.

The builder treats the artifact and source measurement paths as declared
references. It does not read artifact files, open source data, parse CSV
headers, copy files, write storage, calculate checksums, infer schemas,
traverse relations, infer analysis DAGs, or judge scientific correctness.

## What This Earned

The implementation candidate shows that a side-effect-free summary can attach
reviewable source links to a derived artifact:

- preserve artifact identity, kind, path, authority, and reference state;
- summarize explicit source measurement IDs, labels, roles, relations,
  primary-data references, and record states;
- count source states and source roles for review;
- classify the artifact as ready for review or needing source/link review;
- report unavailable source measurements as review findings;
- keep source-link findings separate from analysis-lineage completeness,
  source integrity, artifact correctness, storage mutation, checksum,
  schema-inference, relation-graph, or GUI claims;
- reject fixture claims that cross into artifact observation, source
  observation, storage mutation, checksum validation, schema inference,
  recursive traversal, analysis-DAG inference, scientific validity, GUI
  workflow, or shared schema.

## Boundary

This slice validates direct artifact-to-measurement source links only.

It does not:

- accept, copy, move, archive, checksum, or write artifacts or measurements;
- read artifacts, source data, notebooks, reports, or generated files;
- infer artifact sources from notebooks, scripts, filenames, folders, or
  metadata;
- define a final artifact, measurement relation, package, or handoff schema;
- traverse relation graphs or infer analysis DAGs;
- decide source permanence, artifact correctness, fit quality, scientific
  validity, reproducibility, or publication readiness;
- define GUI behavior.

## Result

Derived artifact source links are a useful Measurement Records boundary because
handoff and traceability often need artifact context before Scopecat has any
analysis-DAG or report-generation authority.

The fixture keeps the relationship explicit: the manifest names the artifact
and direct source measurements. An unavailable comparison source is surfaced as
a review finding, not as proof that the artifact is invalid or that the
analysis lineage is complete.

## Follow-Up

Stop this slice at explicit source-link validation unless the next workflow
needs stronger artifact review behavior.

Likely follow-up slices should stay separate:

- selected-measurement export or handoff package inclusion of derived artifact
  links, without accepting a final package schema;
- artifact observation or checksum validation for artifact-file references, without
  accepting recursive analysis provenance;
- analysis-choice recording for user-declared fit settings or review notes,
  without claiming scientific validity;
- additional artifact kinds, such as figures or reports, one authority case at
  a time.
