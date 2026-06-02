# Measurement Data Reference Boundary

## Status

Discovery boundary note.

This note clarifies the current Measurement Records distinction between data
Scopecat can preview and files Scopecat can only reference or observe. It does
not accept a final storage schema, importer API, adapter API, GUI contract,
legacy reader, artifact schema, or shared measurement-record domain model.

For the current route decisions and next-work guidance after the import/source
observation pass, read
[`routes/measurement-records/import-source-decision.md`](../routes/measurement-records/import-source-decision.md).

## Rule

Scopecat can record references to arbitrary legacy files, attachments, and
artifacts. Scopecat should only plot, preview, or expose dataframe-like primary
data when the referenced content has been converted into a Scopecat-understood
data format or explicitly declares a supported previewable data model.

This keeps legacy compatibility useful without making Scopecat a parser for
every historical storage system.

## Reference Classes

| Class | Meaning | Scopecat can do now | Scopecat must not claim |
| --- | --- | --- | --- |
| Normalized primary data | Data converted or authored into a Scopecat-understood measurement data shape, such as the current small CSV/table fixtures plus declared preview metadata. | Be copied, packaged, opened, observed, exposed as table-like rows, or plotted only through the specific routes that validate those actions. | Legacy source parsing, inferred schema, final storage architecture, or automatic preview merely because a path exists. |
| External source reference | A pointer to original or lab-managed external data, such as a Data Vault, LabRAD, Labber, shared-drive, or old-system file location. | Preserve source identity, label, relation, reference state, redacted display facts, and optional file-level observations such as exists, size, sha256, or mtime when a slice validates them. | That Scopecat can parse, preview, plot, or verify scientific data semantics from the referenced file. |
| Attachment or artifact | An arbitrary linked file or result associated with a measurement, run, step, or analysis. | List it, relate it to source measurements, report availability or source-link findings, and hand it to an external tool or later validated consumer. | Default visualization or conversion into measurement primary data. |
| Previewable data item | A narrower data item that declares roles, axes, units, components, shape, and plot candidates in a supported preview model. | Drive conservative local preview, GUI, SDK, and handoff projections. | Generic ndarray, HDF5, notebook, image, report, or matrix visualization without a validated preview model. |

## Adapter Boundary

Legacy-specific knowledge belongs in user-owned or lab-owned adapters unless a
future slice explicitly accepts a core reader.

An adapter-authored manifest may include both:

- an **external source reference** to the original legacy data for provenance;
- **normalized primary data** produced by the adapter for Scopecat preview,
  packaging, and later analysis.

If a manifest field named `primary_data` points to a Scopecat-readable
normalized file, a slice may treat it as primary measurement data only for the
actions that slice validates. If it points directly to an original legacy file,
it should be modeled as an external source reference or artifact-like
attachment instead. Adapter-declared preview metadata may be shown as an
adapter assertion, but it is not Scopecat-observed previewability unless a
later data-level open/read/observation slice validates access to normalized
data.

## Observation Levels

Keep observation claims explicit:

- **Reference-level observation**: the reference is present in a manifest or
  record. No file access is claimed.
- **File-level observation**: a concrete referenced file was checked for
  existence, size, sha256, mtime, or similar file facts. This does not imply
  data parsing.
- **Data-level observation**: Scopecat or an adapter read the data with a
  declared format/model and checked rows, schema, preview metadata, or plot
  bindings. This requires normalized data or an explicitly validated adapter
  authority.

Do not use file-level observation as evidence that Scopecat can show a plot.

## Import Implications

Current import-like slices should be read this way:

- Incoming record import preview consumes declared external manifests and does
  not read files.
- Adapter-authored legacy import consumes normalized adapter output, not
  legacy input.
- Legacy import acceptance by copy is only Scopecat-readable primary data when
  the copied file is normalized adapter output.
- Reference-only legacy import preserves an unobserved external source
  reference. It never enables Scopecat plots or dataframe-like access by
  itself.
- The handoff package route is different because the package writer owns the
  package-local normalized primary data projection, and separate open/read
  slices validate table and plot access. Handoff package acceptance remains a
  later copy-into-storage mutation step.

## Follow-Up Guidance

Before implementing more reference-only import observation, name the level:

- the first file-level observation slice validates that an external source
  reference still resolves and matches declared file facts;
- a data-level observation or preview slice must require normalized primary
  data or explicit adapter authority;
- repair, moved-reference discovery, recursive artifact traversal, and legacy
  parser integration remain separate decisions.
