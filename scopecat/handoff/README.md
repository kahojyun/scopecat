# Handoff Prototype Module

Engineering prototype module for read-only Scopecat-authored handoff package
use.

This module is route-local prototype code. It tests a production-shaped Python
entrypoint over validated handoff discovery candidates without accepting final
public SDK names, package format, storage import behavior, GUI architecture,
plotting stack, or shared measurement-record domain model.

The runtime API exposes route-local objects rather than discovery candidate
summary dictionaries. `as_open_summary()` exists as a copy-safe prototype
snapshot, not as a public contract.

The prototype owns its handoff-specific manifest preview and contract helpers
inside this module. Discovery implementation candidates remain historical
validation inputs, not runtime dependencies for this route.

Raw manifest dictionaries are validated at the package boundary. After that,
manifest preview classification, review findings, opener internals, and
package projections consume typed route-local manifest fragments.
`observe_package_integrity(...)` is a read-only receiving/import prerequisite:
it compares package-local regular files with paired manifest-declared
digest/size facts where available. It does not verify signatures,
authenticity, trust, archive contents, import acceptance, or storage mutation.

The route-local writer uses a caller-provided `source_root` plus declared
relative source paths for already-normalized primary data. That source-root
boundary deliberately avoids accepting final Scopecat storage architecture.
The writer materializes the current directory-shaped package subset, preflights
declared sha256/size facts, writes with no-overwrite behavior, and returns a
local review receipt. It does not create archives, import packages, mutate the
source root, or decide package acceptance.
Raw write-request dictionaries are accepted only at `write_package(...)`; the
writer validates and parses them into route-local write-source objects before
filesystem preflight, manifest generation, package writes, or receipt
serialization.
`run_package_workflow(...)` composes the promoted writer, reader, and optional
local inspection artifact into one route-local review workflow. It does not
create archives, import or accept packages, verify package integrity, or decide
final storage layout.

## API Surface

Current user-facing prototype surface:

- `open_package(package_dir)`;
- `observe_package_integrity(package_dir)`;
- `write_package(source, source_root=..., package_root=...)`;
- `run_package_workflow(source, source_root=..., package_root=...)`;
- `python -m scopecat.handoff <package-dir>`;
- `write_inspection_artifact(...)` and `build_inspection_html(...)`;
- route projection objects exported from `scopecat.handoff`.

Modules with leading underscores are route-private implementation modules.
They may be tested directly while the prototype hardens, but they are not
public SDK or cross-route domain APIs.
