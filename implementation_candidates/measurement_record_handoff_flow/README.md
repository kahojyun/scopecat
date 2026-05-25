# Measurement Record Handoff Flow Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It composes existing measurement-record candidates into one provisional
vertical workflow:

- consume explicit accepted-record facts from one reviewed adapter-authored
  legacy import;
- build a source-observation request for the accepted primary-data path and
  carry its observation findings;
- summarize that record as an explicit selected measurement export;
- preview an explicit Scopecat-authored handoff package-preview manifest.

The package exists to test whether the current slice-local candidates can
preserve identity, source references, preview metadata, linked context, and
review findings across an eventual handoff route.

Summary posture: `review_summary`. The candidate output is a deliberate
projection of the selected handoff facts, not a raw dump of the input or a
portable/export package artifact.

Raw JSON fixture input is not treated as a full schema contract after parsing.
The candidate-local `contracts.py` module validates the selected handoff facts
before the summary builder adapts them into other slice-local inputs. This is
not a shared measurement model.

Repeated low-level value-shape checks are delegated to the contract-primitives
candidate where the semantics are identical, such as managed identifiers,
syntax-only relative path checks, exact package primary-data paths, strict child
paths, positive integers, text values, and sha256 digest strings. Stable
handoff package route checks, such as package identity and preview column shape,
are delegated to `../handoff_package_contracts/` where they are already shared
with writer or preview candidates.
Composition-specific wrappers remain local when they carry route semantics, such
as accepted-record continuity, package preview alignment, path-derived storage
display refs, and handoff alignment across accepted-record and package-preview
facts.

The composed boundary validates that accepted-record storage paths stay
relative and inside the accepted record directory, that accepted materialization
matches the reference-only linked-context handoff boundary, that Scopecat-managed
display references stay public-safe and redacted, that no-overwrite acceptance,
accepted write-result kind/result/path/digest/size alignment, preview
authority, accepted preview plot-source continuity, candidate-local storage
display derivation, package-declared export summary identifier syntax, and
candidate-local manifest/primary-data package path topology match the accepted record, and that
linked-context package-preview refs and derived package-preview entries match
the accepted reference-only context, including the expected package link-id
mapping.

The package manifest's `source_export_summary_id` is package-declared metadata
validated as a public identifier. This composition does not derive or resolve a
stable selected-export summary identity.

Accepted linked-context `reference` values are adapter-declared scalar text
preserved for local review. They are not interpreted as Scopecat-managed paths
or package topology. Managed topology validation applies to fields this
composition owns or transforms, such as `linked_context_export_refs[].path` and
package `package_path` values.

It deliberately does not perform import acceptance, mutate storage, define a
shared measurement schema, final storage model, package writer, package
format, import acceptance for packages, recursive relation graph, GUI
behavior, schema inference, plotting, live service, hardware control, or
scientific validation.
