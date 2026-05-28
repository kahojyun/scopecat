"""Local static inspection artifact for handoff packages."""

from __future__ import annotations

import html
import math
import os
from pathlib import Path
from typing import Any

from scopecat.handoff.package import (
    HandoffFinding,
    HandoffLinkedContext,
    HandoffMeasurement,
    HandoffPackage,
)
from scopecat.handoff.read_only import open_package
from scopecat.handoff.tables import HandoffPlotSeries, HandoffTable

HANDOFF_INSPECTION_ARTIFACT_NAME = "handoff-package-inspection.html"


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _axis_label(columns: tuple[dict[str, str], ...], name: str) -> str:
    for column in columns:
        if column["name"] == name:
            unit = column.get("unit")
            if unit:
                return f"{column['label']} ({unit})"
            return column["label"]
    return name


def _float_points(series: HandoffPlotSeries) -> list[tuple[float, float]] | None:
    parsed = []
    for point in series.points:
        try:
            x = float(point["x"])
            y = float(point["y"])
        except (TypeError, ValueError):
            return None
        if not math.isfinite(x) or not math.isfinite(y):
            return None
        parsed.append((x, y))
    return parsed


def _scale(
    value: float,
    *,
    source_min: float,
    source_max: float,
    target_min: float,
    target_max: float,
) -> float:
    if source_min == source_max:
        return (target_min + target_max) / 2
    return target_min + (value - source_min) * (target_max - target_min) / (source_max - source_min)


def _svg_plot(series: HandoffPlotSeries, measurement: HandoffMeasurement) -> tuple[str, str]:
    points = _float_points(series)
    if points is None:
        return (
            '<div class="plot-empty">Plot points are not numeric-looking strings.</div>',
            "not_rendered_non_numeric_points",
        )
    if not points:
        return ('<div class="plot-empty">No points declared.</div>', "not_rendered_empty")

    width = 520
    height = 260
    pad_left = 54
    pad_right = 18
    pad_top = 18
    pad_bottom = 46
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x_min = min(xs)
    x_max = max(xs)
    y_min = min(ys)
    y_max = max(ys)
    screen_points = []
    for x, y in points:
        screen_x = _scale(
            x,
            source_min=x_min,
            source_max=x_max,
            target_min=pad_left,
            target_max=width - pad_right,
        )
        screen_y = _scale(
            y,
            source_min=y_min,
            source_max=y_max,
            target_min=height - pad_bottom,
            target_max=pad_top,
        )
        if not math.isfinite(screen_x) or not math.isfinite(screen_y):
            return (
                '<div class="plot-empty">Plot points exceed the static renderer numeric range.</div>',
                "not_rendered_numeric_range",
            )
        screen_points.append((screen_x, screen_y))

    polyline = " ".join(f"{x:.2f},{y:.2f}" for x, y in screen_points)
    circles = "\n".join(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.5" />' for x, y in screen_points)
    columns = measurement.declared_preview_columns
    x_axis = _axis_label(columns, series.x_name)
    y_axis = _axis_label(columns, series.y_name)
    svg = f"""
      <svg class="plot" viewBox="0 0 {width} {height}" role="img" aria-label="{_esc(y_axis)} vs {_esc(x_axis)}">
        <line class="axis" x1="{pad_left}" y1="{height - pad_bottom}" x2="{width - pad_right}" y2="{height - pad_bottom}" />
        <line class="axis" x1="{pad_left}" y1="{pad_top}" x2="{pad_left}" y2="{height - pad_bottom}" />
        <polyline class="series-line" points="{polyline}" />
        <g class="series-points">
          {circles}
        </g>
        <text class="tick-label" x="{pad_left}" y="{height - 18}">{_esc(f"{x_min:g}")}</text>
        <text class="tick-label tick-label-end" x="{width - pad_right}" y="{height - 18}">{_esc(f"{x_max:g}")}</text>
        <text class="tick-label" x="8" y="{height - pad_bottom}">{_esc(f"{y_min:g}")}</text>
        <text class="tick-label" x="8" y="{pad_top + 4}">{_esc(f"{y_max:g}")}</text>
        <text class="axis-label x-label" x="{(pad_left + width - pad_right) / 2:.2f}" y="{height - 4}">{_esc(x_axis)}</text>
        <text class="axis-label y-label" x="14" y="{height / 2:.2f}" transform="rotate(-90 14 {height / 2:.2f})">{_esc(y_axis)}</text>
      </svg>
    """
    return svg, "rendered_fixture_svg"


def _badges(items: tuple[HandoffFinding, ...]) -> str:
    if not items:
        return '<span class="badge quiet">no review findings</span>'
    return "\n".join(f'<span class="badge review">{_esc(item.code)}</span>' for item in items)


def _linked_context(items: tuple[HandoffLinkedContext, ...]) -> str:
    if not items:
        return '<p class="empty">No linked context declared.</p>'
    rows = []
    for item in items:
        rows.append(
            "<li>"
            f"<b>{_esc(item.label)}</b>"
            f"<span>{_esc(item.kind)}</span>"
            f"<span>{_esc(item.materialization)}</span>"
            f"<code>{_esc(item.link_id)}</code>"
            "</li>"
        )
    return f'<ul class="linked-context">{"".join(rows)}</ul>'


def _preview_rows(table: HandoffTable) -> str:
    rows = []
    for row in table.to_records()[:5]:
        rows.append(
            "<tr>" + "".join(f"<td>{_esc(row[column])}</td>" for column in table.columns) + "</tr>"
        )
    headers = "".join(f"<th>{_esc(column)}</th>" for column in table.columns)
    return f"""
      <table class="preview-table">
        <thead><tr>{headers}</tr></thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    """


def _plot_cards(measurement: HandoffMeasurement) -> str:
    cards = []
    for index, series in enumerate(measurement.plot_series, start=1):
        svg, render_state = _svg_plot(series, measurement)
        cards.append(
            f"""
              <section class="plot-card">
                <p class="eyebrow">plot {index} · {_esc(series.y_name)} vs {_esc(series.x_name)}</p>
                {svg}
                <div class="plot-meta">
                  <span>render: {_esc(render_state)}</span>
                  <span>points: {_esc(len(series.points))}</span>
                  <span>source: <code>{_esc(series.source)}</code></span>
                </div>
              </section>
            """
        )
    if cards:
        return "\n".join(cards)
    return (
        '<div class="plot-empty">No declared plot candidates. Table preview is shown instead.</div>'
    )


def _measurement_card(measurement: HandoffMeasurement) -> str:
    return f"""
      <section class="measurement-card" id="{_esc(measurement.measurement_record_id)}">
        <div class="measurement-header">
          <div>
            <p class="eyebrow"><code>{_esc(measurement.measurement_record_id)}</code></p>
            <h2>{_esc(measurement.label)}</h2>
          </div>
          <div class="attention">{_badges(measurement.findings)}</div>
        </div>
        <div class="facts">
          <span><b>experiment</b>{_esc(measurement.experiment_type)}</span>
          <span><b>target</b>{_esc(measurement.target)}</span>
          <span><b>primary rows</b>{_esc(measurement.primary_table.row_count)}</span>
          <span><b>preview rows</b>{_esc(measurement.preview_table.row_count)}</span>
          <span><b>integrity</b>{_esc(measurement.integrity_check)}</span>
        </div>
        <div class="measurement-grid">
          <div>
            <h3>Declared Preview</h3>
            {_plot_cards(measurement)}
          </div>
          <aside>
            <h3>Table Preview</h3>
            {_preview_rows(measurement.preview_table)}
            <h3>Linked Context</h3>
            {_linked_context(measurement.linked_context)}
          </aside>
        </div>
      </section>
    """


def _measurement_index(package: HandoffPackage) -> str:
    rows = []
    for measurement in package.measurements:
        plot_count = len(measurement.plot_series)
        rows.append(
            "<tr>"
            f'<td><a href="#{_esc(measurement.measurement_record_id)}"><code>{_esc(measurement.measurement_record_id)}</code></a></td>'
            f"<td>{_esc(measurement.label)}</td>"
            f"<td>{_esc(measurement.experiment_type)}</td>"
            f"<td>{_esc(measurement.target)}</td>"
            f"<td>{_esc(plot_count)}</td>"
            f"<td>{_esc(measurement.preview_table.row_count)}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _style() -> str:
    return """
      :root {
        color-scheme: light;
        --ink: #1e293b;
        --muted: #64748b;
        --line: #cbd5e1;
        --panel: #ffffff;
        --wash: #f8fafc;
        --accent: #0f766e;
        --accent-weak: #ccfbf1;
        --review: #b45309;
        --review-weak: #ffedd5;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        color: var(--ink);
        background: var(--wash);
        font: 14px/1.45 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      main { max-width: 1180px; margin: 0 auto; padding: 28px; }
      header {
        border-bottom: 1px solid var(--line);
        padding-bottom: 18px;
        margin-bottom: 18px;
      }
      h1, h2, h3, p { margin-top: 0; }
      h1 { font-size: 28px; margin-bottom: 8px; }
      h2 { font-size: 20px; margin-bottom: 0; }
      h3 { font-size: 13px; text-transform: uppercase; color: var(--muted); margin: 16px 0 8px; }
      code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
      table { width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--line); }
      th, td { padding: 8px 10px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
      th { color: var(--muted); font-size: 12px; text-transform: uppercase; background: #f1f5f9; }
      .eyebrow, .empty, .plot-meta { color: var(--muted); font-size: 12px; }
      .facts, .plot-meta, .attention { display: flex; flex-wrap: wrap; gap: 8px; }
      .facts span, .badge {
        display: inline-flex;
        gap: 6px;
        align-items: center;
        border: 1px solid var(--line);
        border-radius: 999px;
        padding: 4px 8px;
        background: var(--panel);
      }
      .badge.review { color: var(--review); background: var(--review-weak); border-color: #fdba74; }
      .badge.quiet { color: var(--muted); }
      .measurement-card {
        background: var(--panel);
        border: 1px solid var(--line);
        margin-top: 18px;
        padding: 18px;
      }
      .measurement-header {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 16px;
        align-items: start;
        margin-bottom: 14px;
      }
      .measurement-grid {
        display: grid;
        grid-template-columns: minmax(0, 2fr) minmax(300px, 1fr);
        gap: 18px;
      }
      .plot-card { margin-bottom: 14px; }
      .plot {
        display: block;
        width: 100%;
        min-height: 250px;
        border: 1px solid var(--line);
        background: #f8fafc;
      }
      .axis { stroke: #94a3b8; stroke-width: 1; }
      .series-line { fill: none; stroke: var(--accent); stroke-width: 3; stroke-linejoin: round; stroke-linecap: round; }
      .series-points circle { fill: var(--accent); stroke: #ffffff; stroke-width: 1.5; }
      .tick-label, .axis-label { fill: var(--muted); font-size: 11px; }
      .tick-label-end { text-anchor: end; }
      .x-label, .y-label { text-anchor: middle; }
      .plot-empty {
        min-height: 250px;
        border: 1px dashed var(--line);
        display: grid;
        place-items: center;
        color: var(--muted);
        background: #f8fafc;
      }
      .linked-context {
        list-style: none;
        padding: 0;
        margin: 0;
        display: grid;
        gap: 8px;
      }
      .linked-context li {
        border: 1px solid var(--line);
        padding: 10px;
        display: grid;
        gap: 4px;
      }
      footer {
        border-top: 1px solid var(--line);
        color: var(--muted);
        margin-top: 28px;
        padding-top: 14px;
      }
      @media (max-width: 820px) {
        main { padding: 18px; }
        .measurement-header, .measurement-grid { grid-template-columns: 1fr; }
      }
    """


def build_inspection_html(package: HandoffPackage) -> str:
    """Render a read-only handoff package projection into local static HTML."""

    measurement_cards = "\n".join(
        _measurement_card(measurement) for measurement in package.measurements
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_esc(package.display_name)}</title>
  <style>{_style()}</style>
</head>
<body>
  <main>
    <header>
      <p class="eyebrow">local handoff package inspection artifact</p>
      <h1>{_esc(package.display_name)}</h1>
      <div class="facts">
        <span><b>package</b><code>{_esc(package.package_id)}</code></span>
        <span><b>preview</b>{_esc(package.preview_classification)}</span>
        <span><b>measurements</b>{_esc(len(package.measurements))}</span>
        <span><b>findings</b>{_esc(len(package.findings))}</span>
      </div>
    </header>

    <section>
      <h2>Measurement Index</h2>
      <table>
        <thead>
          <tr>
            <th>Record</th>
            <th>Label</th>
            <th>Experiment</th>
            <th>Target</th>
            <th>Plots</th>
            <th>Preview Rows</th>
          </tr>
        </thead>
        <tbody>
          {_measurement_index(package)}
        </tbody>
      </table>
    </section>

    <section>
      <h2>Read-Only Review</h2>
      {measurement_cards}
    </section>

    <footer>
      Static local inspection artifact. Not a portable package member, public
      report, final GUI component model, dataframe adapter, package import
      record, or package-integrity verification.
    </footer>
  </main>
</body>
</html>
"""


def _is_in_package_tree(path: Path) -> bool:
    resolved = path.resolve()
    return any(
        (candidate / "package-manifest.json").exists()
        for candidate in (resolved, *resolved.parents)
    )


def write_inspection_artifact(
    package_or_dir: HandoffPackage | str | Path,
    *,
    output_dir: Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Write a local static handoff inspection artifact and return a receipt."""

    if _is_in_package_tree(output_dir):
        raise ValueError("handoff inspection artifact output_dir must not be in a package tree")
    package = (
        package_or_dir
        if isinstance(package_or_dir, HandoffPackage)
        else open_package(Path(package_or_dir))
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / HANDOFF_INSPECTION_ARTIFACT_NAME
    if html_path.is_symlink():
        raise ValueError("handoff inspection artifact target must not be a symlink")
    existed = os.path.lexists(html_path)
    if existed and not overwrite:
        raise ValueError("handoff inspection artifact already exists")
    html_path.write_text(build_inspection_html(package), encoding="utf-8")
    return {
        "artifact_posture": "review_summary",
        "html_artifact": {
            "filename": HANDOFF_INSPECTION_ARTIFACT_NAME,
            "local_path": str(html_path),
            "created": html_path.is_file(),
            "overwritten": existed,
            "portable_package_member": False,
        },
        "package_id": package.package_id,
        "measurement_count": len(package.measurements),
    }
