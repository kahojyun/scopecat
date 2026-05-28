# Adapter Output Boundary Validation Result

## Status

Implementation candidate validated.

Artifact posture: `internal_validation_summary`. This document and the
expected fixture are repository review artifacts. They are not portable,
public, export, or package output.

## Validation Question

Can Scopecat review a small adapter-produced input boundary without deciding
the final adapter transport API?

## Result

Yes, for the validated fixture.

The candidate validates a file-shaped adapter output bundle with:

- a boundary manifest using schema `scopecat.adapter_output_boundary.v0`;
- an adapter-authored legacy import manifest;
- one adapter-normalized primary CSV table;
- one or more linked-context reference files;
- declared sha256 and byte-size facts for those files;
- source identity and preview metadata delegated to the adapter-authored
  legacy import candidate.

The fixture uses files because that makes the boundary observable in tests.
The earned contract is the logical adapter output boundary: an adapter supplies
reviewed manifest facts plus declared output file facts. A later writer-like
adapter API could provide the same logical facts without preserving this
directory layout.

## Boundary

This slice is before import acceptance. It validates adapter output and reports
review findings, but it does not copy into Scopecat storage, mutate existing
records, accept an import, or make GUI decisions.

Scopecat core still does not parse arbitrary legacy systems. The adapter is
responsible for any LabRAD, DataVault, Labber, or lab-specific source parsing
and for producing normalized Scopecat-readable primary data when preview,
copy, SDK/table access, or plotting is desired.

Linked context is observed as a declared reference file. Its payload is not
imported, recursively traversed, repaired, or interpreted by this slice.

The file observation checks ordinary fixture files under a caller-provided
adapter output root. The prototype rejects symlink roots, symlink parents, and
symlink targets, but it does not claim adversarial concurrent-root mutation
support.

## Validated Behavior

- `validate_adapter_output_boundary()` returns
  `adapter_output_ready_for_review` for the repository fixture.
- Missing or digest/size-mismatched non-manifest files become review findings
  and block the boundary as `adapter_output_blocked_by_file_findings`.
- Missing or mismatched adapter manifest file facts block before manifest
  parsing as `adapter_output_blocked_by_manifest_file_findings`.
- The declared normalized primary-data file must match the adapter-authored
  manifest's `primary_data.path`.
- Every available adapter-manifest linked-context record must have a declared
  boundary file reference, and every declared boundary linked-context file must
  match an available adapter-manifest link.
- Unsupported policy or transport claims are rejected rather than silently
  becoming route decisions.
- Delegated adapter-manifest validation still owns adapter authority, source
  identity, primary-data reference, preview metadata, linked context, and
  adapter finding checks.

## Decisions Not Earned

- final drop-folder protocol, writer-like adapter API, or storage protocol;
- stable public adapter API;
- core legacy readers;
- storage mutation, import acceptance, or existing-record update;
- schema inference, scan-shape inference, or generic dataframe semantics;
- linked-context payload import or recursive traversal;
- reference repair or moved-reference discovery;
- GUI import/review workflow.

## Follow-Up

Use this boundary as the current stop point for adapter-produced input unless a
real product workflow needs more pressure.

Reopen with a separate slice if users need a durable drop-folder discovery
protocol, a concrete writer-like adapter API, import acceptance from this
boundary into storage, data-level reads of normalized adapter output, or GUI
workflow state.
