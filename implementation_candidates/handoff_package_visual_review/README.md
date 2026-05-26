# Handoff Package Visual Review Candidate

This package is an implementation candidate, not accepted Scopecat
architecture, a GUI contract, or a stable SDK.

It tests a plot-first local review projection over the read-only handoff
package read view:

- open a directory-shaped handoff package through the validated read view;
- put declared plot candidates before table drilldown facts;
- expose axis labels, units, roles, and point counts as structured facts;
- expose plot points as a local plot-data projection without choosing a
  plotting library;
- keep linked context and review findings visible beside the visual summary.

The candidate deliberately does not generate caption prose. It provides
caption-like structured facts so a future GUI, notebook helper, or SDK wrapper
can render titles, badges, side panels, or tooltips without treating natural
language text as the contract.

The summary is a local `review_summary`. It is not a portable/export artifact,
package import record, archive, dataframe adapter, final GUI component model,
package-integrity check, or shared measurement model.
