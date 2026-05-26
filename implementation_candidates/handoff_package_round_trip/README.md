# Handoff Package Round Trip Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It tests producer-to-reader compatibility for the current directory-shaped
handoff package route:

- write a handoff package through the validated writer;
- preview the generated `package-manifest.json`;
- open the generated package through the read-only reader view;
- summarize whether package identity, selected measurements, table access,
  declared preview plots, linked context, and review findings survive the
  writer-to-reader path.

The summary is a local review surface. It is not a portable/export artifact,
package import record, archive, final SDK contract, dataframe adapter, GUI
contract, or shared measurement model. It may report writer receipt posture as
local-only review data; that posture is not a package or reader capability.
