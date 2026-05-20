# Selected Run Handoff Spike

## Status

Validation spike only. This is not product code, not a manifest schema, not a
package/export format, not a reader API, and not an ADR.

The spike tests whether a small public-safe selected-run export input can
produce a handoff summary with:

- selected source identity and export provenance;
- present and missing file checks;
- source data, copied context, companion artifacts, and derived artifacts kept
  distinct;
- no-silent-transform expectations;
- enough figure-readiness context for a collaborator to identify candidate plot
  axes without treating the output as a report.

## Boundary

This spike intentionally uses only the Python standard library. It does not
read real lab data, parse notebooks, infer schemas from arbitrary files, or
generate plots.

Preview, slicing, dataframe-friendly export, and plotting behavior are separate
future validation questions.

Related-but-not-exported runs are also outside this minimal spike. They may be
validated later if grouping, tags, or user notes make that context valuable.

The companion preview spike starts from declared column names and roles rather
than schema inference. That keeps selected-run export focused on carrying
context and lets scan declaration evolve through separate fixtures.
