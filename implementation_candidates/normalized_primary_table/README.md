# Normalized Primary Table Candidate

This package is an implementation candidate, not accepted Scopecat
architecture, a final table storage format, or a stable SDK/dataframe API.

The candidate validates the smallest table read contract for Scopecat-readable
normalized primary CSV data. It starts from already-provided bytes, so it does
not own adapter output, storage paths, package layout, file observation,
integrity checks, or legacy source parsing.

The candidate:

- decodes UTF-8 CSV bytes;
- requires one non-empty header row with unique, non-blank column names;
- rejects ragged rows before emitting table facts;
- validates declared preview-column bindings against observed table columns;
- returns string-valued rows and declared-column preview rows;
- reports declared row-count mismatches as review findings.

It deliberately does not infer schemas, scalar types, dataframe dtypes, scan
shape, units, plot series, file integrity, storage acceptance, adapter
transport, GUI behavior, or final SDK names.
