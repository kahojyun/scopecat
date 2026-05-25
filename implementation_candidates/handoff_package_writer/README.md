# Handoff Package Writer Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It materializes a minimal directory-shaped handoff package from explicit
package-writer input:

- copy selected primary measurement data from a caller-provided storage root
  into the package-relative
  `measurements/{measurement_record_id}/primary.csv` path;
- write a deterministic package manifest at
  `{package_id}/package-manifest.json`;
- preserve linked context as visible reference-only manifest entries.

This is the first portable/package boundary in the measurement handoff route.
The generated package directory is the portable artifact. Its
`package-manifest.json` is the portable contract/index inside that directory,
and copied primary data are package members. The manifest deliberately projects
an allowlisted set of package facts in the same shape accepted by the handoff
package contents preview candidate, and does not include the source storage
paths used to copy primary data. The function return value is a local write
receipt for engineering review, not the portable package artifact. The
portable manifest omits local display paths; the local write receipt may keep a
redacted local display identity for review. It validates managed package paths,
generated package directory/manifest topology, rejection of package roots equal
to or inside measurement storage, at least one selected measurement, managed
identifiers and schema-binding column names, no-overwrite destinations, source
sha256/size preflight, best-effort rollback for ordinary write failures, and
reference-only linked-context alignment. Human labels and reasons remain
reviewed free text rather than runtime-redacted fields.

Repeated low-level checks are delegated to the contract-primitives
implementation candidate. Shared handoff-route semantics such as package
identity and preview-ready metadata shape are delegated to
`../handoff_package_contracts/`. The writer still owns package-writing
behavior, manifest projection, file preflight, no-overwrite checks, and
rollback behavior; using those helpers does not accept a shared measurement
schema or final package format.

This slice does not accept arbitrary nested package member paths. Additional
package members or package layout categories should be introduced as explicit
future contracts rather than inferred from fixture-provided paths.

This prototype assumes caller-provided storage and package roots are not
concurrently mutated during the write call. Adversarial filesystem races and
atomic publish semantics are production-hardening work, not accepted by this
slice.

It deliberately does not create an archive, accept or import packages, allow
package roots equal to or inside measurement storage, mutate the
caller-provided measurement storage root, infer schemas, traverse relation
graphs, define a shared measurement schema, provide a GUI workflow, or package
linked-context payloads.
