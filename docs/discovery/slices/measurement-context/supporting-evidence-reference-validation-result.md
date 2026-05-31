# Supporting Evidence Reference Validation Result

## Status

Implementation candidate validated.

This result validates a narrow Measurement Context support slice:
**Supporting Evidence Reference**.

It does not accept a general attachment subsystem, payload importer, file
observer, evidence parser, checksum contract, storage writer, preview
generator, external file authority, artifact-provenance validator, recursive
relation traversal, measurement validity decision, implicit run-start context,
GUI workflow, or shared attachment schema.

## Fixture

Fixture:
[`../../tests/fixtures/supporting_evidence_reference/basic_supporting_evidence_reference/`](../../../../tests/fixtures/supporting_evidence_reference/basic_supporting_evidence_reference)

Implementation candidate:
[`../../implementation_candidates/supporting_evidence_reference/`](../../../../implementation_candidates/supporting_evidence_reference)

The fixture records one user-supplied during-run debug evidence reference:

- the evidence is labeled as an `attachment`;
- one resolved running measurement;
- one resolved prepared run;
- one unavailable follow-up calibration step.

The builder treats the evidence path, evidence kind, lifecycle stage, and
target links as declared references. It does not read files, import payloads,
copy files, write storage, calculate checksums, observe file state, validate
artifact provenance, generate previews, traverse relations, or decide whether
the linked measurement or context is valid.

## What This Earned

The implementation candidate shows that Scopecat can preserve optional
supporting evidence without making it primary context:

- preserve evidence identity, evidence kind, content kind, purpose, lifecycle,
  declared reference, and supplied authority;
- keep `attachment`, `artifact`, and `unspecified` as label-only evidence
  kinds in the base slice;
- avoid requiring artifact provenance unless a separate provenance/source-link
  slice earns it;
- relate evidence to measurement, prepared-run, operator-approval,
  parameter-state, running-measurement, or calibration-step targets;
- count target types and target states for review;
- classify the evidence reference as ready for review or needing evidence or
  target review;
- report unavailable related targets as review findings;
- reject fixture claims that cross into evidence observation, payload import,
  unsupported relation semantics, absolute paths, duplicate links, provenance
  passthrough, or shared attachment schema.

## Boundary

This slice validates explicit supporting evidence references only.

It does not:

- accept, copy, move, archive, checksum, observe, parse, or write referenced
  evidence;
- infer attachments from folders, generated compatibility files, stdout,
  notebooks, reports, or adapter outputs;
- infer that supporting evidence is produced before run start or required by
  run-start context review;
- make supporting evidence canonical measurement context, parameter context,
  primary data, or a second authority for parameter values;
- require supporting evidence for measurement-record validity;
- validate artifact provenance, source links, producing tools, analysis DAGs,
  or source-measurement completeness;
- define a final attachment model, package schema, relation graph, or GUI.

## Result

Supporting evidence references are useful as a generic route for debug, audit,
handoff, or review evidence that a user explicitly supplies.

The attachment/artifact distinction is useful, but it should stay label-only in
this base slice. Attachments are usually opaque user/lab supplied evidence;
artifacts may later need producer/source/provenance modeling, but that pressure
belongs in a separate artifact provenance or source-link slice. The stable
context remains the selected managed context record, such as a parameter-state
snapshot; the evidence reference explains supporting material without absorbing
payloads or expanding Scopecat's responsibility.

## Follow-Up

Stop this slice at explicit supporting evidence references unless a workflow
needs stronger behavior.

Likely follow-up slices should stay separate:

- artifact provenance/source-link validation for generated artifacts, without
  making it required for attachments;
- package inclusion of selected supporting evidence references, without
  accepting a final package schema;
- running-record update or post-run review composition for during-run
  diagnostic evidence, without making it a run-start input;
- file observation or checksum validation, without accepting payload import or
  external-file authority;
- artifact preview for a specific supported artifact kind, without arbitrary
  visualization;
- route-local GUI state that displays supporting evidence references, without
  creating a general attachment subsystem.
