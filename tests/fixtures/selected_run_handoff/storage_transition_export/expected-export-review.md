# Expected Storage-Transition Export Review

## Fixture Wrapper

- expected output id: `storage-transition-measurement-export.expected`
- status: `expected_validation_output`
- source fixture: `export-input.json`
- reference semantics: `storage_transition_fixture`
- guard: This expected output is not a final storage architecture, package
  format, schema contract, or path-addressed identity model.

`export-input.json` models pre-export record/reference state. Package
materialization paths are expected export output, not known source input.
`path` and `package_materialized_path` values in the expected summary are
package-relative fixture files used for export/openability checks. They are not
durable record identity.

## Candidate Summary Review

### Selected Export Set

- selection mode: `multi_measurement`
- selected measurements: `measurement-02001`, `measurement-02002`
- traversal policy: `non_recursive`

Selecting these measurements exports their declared default bundles. Linked
files are reported with declared inclusion status and are not recursively
traversed.

### Storage And Source Identity

| Measurement | Source identity | Current reference | Package materialization | Availability |
| --- | --- | --- | --- | --- |
| `measurement-02001` | Scopecat-managed record | `scopecat://measurements/measurement-02001/primary-data` | `source/managed/managed-rabi-source.csv` | `available` |
| `measurement-02002` | lab-managed network reference | `LAB_SHARE:/redacted/datavault/network-storage-demo/external-ramsey-source.csv` | `source/external_materialized/external-ramsey-source.csv` | `available_for_export` |

Managed storage, lab-managed network source identity, and package
materialization are separate concepts. A managed record does not need to expose
an internal filesystem path. A network reference can still be materialized into
an export package when available.

### Included By Default

| Measurement | Experiment | Included items |
| --- | --- | --- |
| `measurement-02001` | qB Rabi amplitude sweep | qB Rabi source data (`source/managed/managed-rabi-source.csv`); qB Rabi parameter snapshot (`snapshots/managed-rabi-parameter-snapshot.json`) |
| `measurement-02002` | qB Ramsey detuning scan | qB Ramsey source data (`source/external_materialized/external-ramsey-source.csv`); qB Ramsey parameter snapshot (`snapshots/external-ramsey-parameter-snapshot.json`) |

### Linked Context

- Session beta cooldown note (`attachments/network-session-cooldown-note.md`):
  managed attachment, included by user, linked to both selected measurements.
- Local fit scratchpad: user-declared network artifact linked to
  `measurement-02002`, but missing or moved.

### Warnings

- `missing_external_reference`: a user-declared external artifact for
  `measurement-02002` cannot be materialized into the export package.

## Boundary Notes

- lab-managed network referenced but available selected source data is normal
  state, not a warning.
- missing or moved external linked context is warning-worthy.
- package-relative materialized paths are openability/export paths, not the
  final storage identity model.
- this fixture does not decide whether network-reference mode is temporary
  adoption support, lab policy support, or a normal long-term workflow.
- this fixture does not encourage recording arbitrary mutable local files as a
  substitute for managed data.
- this fixture does not add an importer, package writer, checksum contract,
  GUI workflow, moved-path repair behavior, or recursive relation traversal.

## Reviewer Questions

A reviewer should be able to answer:

- which selected measurements are managed by Scopecat versus externally
  referenced;
- which source identity is recoverable after export;
- which files are materialized into package-relative paths;
- which linked context is user-included;
- which external reference is missing or moved;
- that package paths are not durable identity;
- that final storage architecture and external-reference policy remain
  undecided.
