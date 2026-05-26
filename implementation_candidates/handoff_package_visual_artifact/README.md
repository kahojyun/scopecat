# Handoff Package Visual Artifact Candidate

This candidate is not accepted Scopecat
architecture, a GUI framework, a plotting library decision, or a stable SDK.

It tests whether the plot-first handoff package visual-review model can be
rendered into one local static HTML review artifact:

- consume the validated visual-review model projection;
- render package and measurement overview facts;
- render declared visual summaries before table drilldown facts;
- draw simple inline SVG plots for numeric-looking local fixture points;
- keep linked-context references and review findings visible beside visuals;
- write a deterministic local HTML file when asked;
- reject package-tree output directories and require explicit overwrite.

The HTML artifact is a local/review surface. It is not a portable handoff
package member, public report, package import record, archive, final GUI
component model, dataframe adapter, scientific plotting contract, package
integrity check, or shared measurement model.

Current rendering assumption: this candidate may use narrow stdlib string
rendering while it remains a single-file, non-interactive local review artifact
covered by escaping and structure-position tests. If this route grows into a
maintained GUI/report surface, it should move to an escaping-by-default
rendering layer instead of expanding ad hoc HTML strings.
