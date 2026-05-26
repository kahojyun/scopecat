# Filesystem Mutation Helpers

This support candidate contains narrow filesystem primitives for implementation
candidates that write new files under caller-provided roots.

It owns only repeated low-level behavior:

- require an existing non-symlink directory root;
- resolve relative paths under that root;
- detect existing paths including symlinks;
- reject symlink parents;
- write new files with no-overwrite behavior;
- remove partial files and created directories on ordinary write failures;
- roll back a sequence of files written by a candidate transaction.

It does not define Scopecat storage architecture, package format, import
semantics, record manifests, locking, concurrency, redaction, schema inference,
or a stable public API.
