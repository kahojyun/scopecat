# Supporting Artifact Provenance Validation Result

## Status

Implementation candidate validated.

This result validates a narrow Measurement Context support slice:
**Supporting Artifact Provenance**.

It does not accept artifact generation, artifact payload import, artifact file
observation, source payload observation, checksum validation, storage mutation,
recursive relation traversal, analysis-DAG inference, fit validation,
measurement-validity decisions, portable/public export, GUI workflow, or a
shared artifact schema.

## Fixture

Fixture:
[`../../tests/fixtures/supporting_artifact_provenance/basic_provenance/`](../../../../tests/fixtures/supporting_artifact_provenance/basic_provenance)

Implementation candidate:
[`../../implementation_candidates/supporting_artifact_provenance/`](../../../../implementation_candidates/supporting_artifact_provenance)

The fixture records one artifact-labeled supporting evidence summary and one
explicit provenance manifest:

- one declared-available post-run review artifact reference;
- one declared-completed producer;
- one declared-available source measurement record;
- one declared-available parameter-state source context;
- one unavailable calibration-step source context.

The builder validates identity continuity between the supporting-evidence
artifact and the provenance manifest, then summarizes direct source links. It
does not open the artifact, read source records, import payloads, calculate
checksums, generate artifacts, infer recursive lineage, perform fit review, or
decide measurement validity.

## What This Earned

The implementation candidate shows that Scopecat can strengthen an
artifact-labeled supporting evidence reference with declared provenance without
turning all attachments into artifacts:

- require a prior supporting-evidence summary whose evidence kind is
  `artifact`;
- keep the base supporting-evidence slice label-only and non-observing;
- validate artifact identity, label, and declared reference continuity;
- preserve declared producer identity and execution state;
- summarize direct source identities, source roles, relations, and states;
- classify the provenance summary as ready, needing producer review, needing
  source review, needing link review, or needing artifact-reference review;
- report unavailable source links as review findings;
- reject claims that cross into payload import, file observation, checksum
  validation, storage mutation, artifact generation, recursive traversal,
  analysis-DAG inference, fit validation, measurement validity, or shared
  artifact schema.

## Boundary

This slice validates declared provenance/source links for supporting artifacts
only.

It does not:

- require provenance for ordinary attachments or debug logs;
- discover, create, copy, move, archive, checksum, parse, or observe artifacts;
- read source measurement data, context payloads, notebooks, reports, scripts,
  or generated files;
- infer provenance from filenames, folders, notebooks, code, logs, or metadata;
- prove complete analysis lineage or recursive analysis DAG structure;
- decide fit quality, scientific correctness, reproducibility, or measurement
  validity;
- add selected artifact references to durable records or export packages;
- define GUI behavior or a final artifact schema.

## Result

Supporting artifact provenance is a useful follow-up to the base supporting
evidence reference slice.

The base slice remains the right route for debug logs and opaque attachments.
This slice adds stronger semantics only when the evidence is explicitly an
artifact and the user supplies a provenance manifest. Missing source links are
review findings, not proof that the artifact is invalid or that provenance is
complete.

## Follow-Up

Stop this slice at declared direct provenance unless a concrete workflow needs
stronger behavior.

Likely follow-up slices should stay separate:

- artifact file observation or checksum validation, without accepting payload
  import or storage mutation;
- selected-measurement export inclusion of supporting artifacts and their
  provenance links, without accepting a final package schema;
- fit-result or analysis-quality review, without turning provenance into a
  scientific-validity decision;
- durable record append of reviewed artifact evidence, without broadening this
  slice into storage ownership;
- route-local GUI state for displaying provenance links, without creating a
  general artifact manager.
