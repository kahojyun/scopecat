# Handoff Package Opener Implementation Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests the read-only package-use step in the open-before-import handoff
flow:

- read a directory-shaped Scopecat handoff package from a caller-provided
  package directory;
- validate and summarize its `package-manifest.json` through the handoff
  package contents preview contract;
- reject empty selected-measurement packages through that manifest contract;
- open package-local primary CSV files declared by selected measurements,
  while rejecting symlink package roots, primary files, and primary parent
  directories;
- expose declared preview rows and plot-ready point series from declared
  columns when the manifest metadata is `preview_ready`;
- preserve manifest-declared `data_shape` as local opened summary metadata
  without inferring shape from CSV contents;
- carry manifest-preview findings without treating them as opener-local file
  open failures;
- keep linked context reference-only.

The candidate is read-only. It does not mutate storage, accept or import the
package, extract archives, validate package integrity or signatures, infer
schemas, recursively traverse relations, define a GUI, or define a stable SDK
object model.
