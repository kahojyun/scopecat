"""Static HTML artifact for local handoff package visual review.

This candidate consumes the plot-first visual-review model and projects it into
one deterministic local HTML file. The artifact is meant for local review and
prototype UX validation; it is not a portable package member, public report,
final GUI component, or scientific plotting contract.
"""

from __future__ import annotations

import html
import math
from pathlib import Path
from typing import Any

_ARTIFACT_NAME = "handoff-package-visual-review.html"
_EXPECTED_POLICY = {
    "artifact_authority": "handoff_package_visual_review_model",
    "artifact_class": "local_review_surface",
    "html_output": "static_single_file",
    "plot_rendering": "simple_fixture_svg_for_numeric_points",
    "caption_text_generation": "not_performed",
    "interactive_gui": "not_defined",
    "plotting_library": "not_selected",
    "dataframe_adapter": "not_defined",
    "package_acceptance": "not_performed",
    "storage_import": "not_performed",
    "archive_handling": "not_performed",
    "package_integrity": "not_claimed",
    "schema_inference": "not_performed",
}


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _severity_class(severity: Any) -> str:
    if severity in {"info", "review"}:
        return str(severity)
    return "quiet"


def _axis_label(axis: dict[str, Any]) -> str:
    label = axis["label"]
    unit = axis.get("unit")
    if unit:
        return f"{label} ({unit})"
    return str(label)


def _float_points(points: list[dict[str, str]]) -> list[tuple[float, float]] | None:
    parsed = []
    for point in points:
        try:
            x = float(point["x"])
            y = float(point["y"])
        except (KeyError, TypeError, ValueError):
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


def _screen_points(
    points: list[tuple[float, float]],
    *,
    width: int,
    height: int,
    pad_left: int,
    pad_right: int,
    pad_top: int,
    pad_bottom: int,
) -> list[tuple[float, float]] | None:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x_min = min(xs)
    x_max = max(xs)
    y_min = min(ys)
    y_max = max(ys)
    scaled = []
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
            return None
        scaled.append((screen_x, screen_y))
    return scaled


def _svg_plot(plot: dict[str, Any]) -> tuple[str, str]:
    points = _float_points(plot["series"]["points"])
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
    screen_points = _screen_points(
        points,
        width=width,
        height=height,
        pad_left=pad_left,
        pad_right=pad_right,
        pad_top=pad_top,
        pad_bottom=pad_bottom,
    )
    if screen_points is None:
        return (
            '<div class="plot-empty">Plot points exceed the static renderer numeric range.</div>',
            "not_rendered_numeric_range",
        )
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x_min = min(xs)
    x_max = max(xs)
    y_min = min(ys)
    y_max = max(ys)
    polyline = " ".join(f"{x:.2f},{y:.2f}" for x, y in screen_points)
    circles = "\n".join((f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.5" />') for x, y in screen_points)
    x_axis = _axis_label(plot["x_axis"])
    y_axis = _axis_label(plot["y_axis"])
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


def _attention_badges(items: list[dict[str, Any]]) -> str:
    if not items:
        return '<span class="badge quiet">no review findings</span>'
    return "\n".join(
        f'<span class="badge {_severity_class(item.get("severity"))}">{_esc(item["code"])}</span>'
        for item in items
    )


def _context_badges(context: dict[str, Any]) -> str:
    badges = [
        ("experiment", context["experiment_type"]),
        ("target", context["target"]),
        ("primary rows", context["primary_table"]["row_count"]),
        ("preview rows", context["preview_table"]["row_count"]),
    ]
    return "\n".join(
        f'<span class="context-badge"><b>{_esc(label)}</b>{_esc(value)}</span>'
        for label, value in badges
    )


def _linked_context(items: list[dict[str, Any]]) -> str:
    if not items:
        return '<p class="empty">No linked context declared for this visual.</p>'
    rows = []
    for item in items:
        rows.append(
            "<li>"
            f"<b>{_esc(item['label'])}</b>"
            f"<span>{_esc(item['kind'])}</span>"
            f"<span>{_esc(item['materialization'])}</span>"
            f"<code>{_esc(item['link_id'])}</code>"
            "</li>"
        )
    return f'<ul class="linked-context">{"".join(rows)}</ul>'


def _visual_card(visual: dict[str, Any]) -> str:
    plot = visual["plot"]
    svg, render_state = _svg_plot(plot)
    duplicate = " duplicate" if plot["duplicate_candidate"] else ""
    return f"""
      <section class="visual-card{duplicate}" id="{_esc(visual["visual_summary_id"])}">
        <div class="visual-header">
          <div>
            <p class="eyebrow">visual {_esc(plot["candidate_position"])} · {_esc(plot["kind"])}</p>
            <h2>{_esc(visual["measurement_label"])}</h2>
          </div>
          <div class="attention">{_attention_badges(visual["attention_items"])}</div>
        </div>
        <div class="visual-grid">
          <div class="plot-panel">
            {svg}
            <div class="plot-meta">
              <span>render: {_esc(render_state)}</span>
              <span>points: {_esc(plot["series"]["point_count"])}</span>
              <span>source: <code>{_esc(plot["source"])}</code></span>
            </div>
          </div>
          <aside class="context-panel">
            <h3>Structured Context</h3>
            <div class="context-badges">{_context_badges(visual["structured_context"])}</div>
            <h3>Linked Context</h3>
            {_linked_context(visual["structured_context"]["linked_context_refs"])}
          </aside>
        </div>
      </section>
    """


def _measurement_index(items: list[dict[str, Any]]) -> str:
    rows = []
    for item in items:
        visual_links = " ".join(
            f'<a href="#{_esc(visual_id)}">{_esc(visual_id)}</a>'
            for visual_id in item["visual_summary_ids"]
        )
        if not visual_links:
            visual_links = '<span class="empty">no declared plots</span>'
        rows.append(
            "<tr>"
            f"<td><code>{_esc(item['measurement_record_id'])}</code></td>"
            f"<td>{_esc(item['label'])}</td>"
            f"<td>{_esc(item['experiment_type'])}</td>"
            f"<td>{_esc(item['target'])}</td>"
            f"<td>{visual_links}</td>"
            f"<td>{_attention_badges(item['attention_items'])}</td>"
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
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 24px;
        align-items: end;
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
      th, td { padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
      th { color: var(--muted); font-size: 12px; text-transform: uppercase; background: #f1f5f9; }
      .eyebrow, .empty, .plot-meta { color: var(--muted); font-size: 12px; }
      .package-facts, .context-badges, .plot-meta, .attention { display: flex; flex-wrap: wrap; gap: 8px; }
      .context-badge, .badge {
        display: inline-flex;
        gap: 6px;
        align-items: center;
        border: 1px solid var(--line);
        border-radius: 999px;
        padding: 4px 8px;
        background: var(--panel);
        white-space: nowrap;
      }
      .badge.info { color: var(--accent); background: var(--accent-weak); border-color: #5eead4; }
      .badge.review { color: var(--review); background: var(--review-weak); border-color: #fdba74; }
      .badge.quiet { color: var(--muted); }
      .visual-card {
        background: var(--panel);
        border: 1px solid var(--line);
        margin-top: 18px;
        padding: 18px;
      }
      .visual-card.duplicate { border-color: #fdba74; }
      .visual-header {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 16px;
        align-items: start;
        margin-bottom: 14px;
      }
      .visual-grid {
        display: grid;
        grid-template-columns: minmax(0, 2fr) minmax(260px, 1fr);
        gap: 18px;
      }
      .plot-panel, .context-panel { min-width: 0; }
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
      .x-label { text-anchor: middle; }
      .y-label { text-anchor: middle; }
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
        header, .visual-header, .visual-grid { grid-template-columns: 1fr; }
      }
    """


def build_handoff_package_visual_review_html(model: dict[str, Any]) -> str:
    """Render a visual-review model to one local static HTML document."""

    package = model["package"]
    visuals = model["visual_summaries"]
    visual_cards = "\n".join(_visual_card(visual) for visual in visuals)
    if not visual_cards:
        visual_cards = (
            '<section class="visual-card"><div class="plot-empty">'
            "No declared plot candidates are available in this package."
            "</div></section>"
        )
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_esc(package["display_name"])}</title>
  <style>{_style()}</style>
</head>
<body>
  <main>
    <header>
      <div>
        <p class="eyebrow">local handoff package review artifact</p>
        <h1>{_esc(package["display_name"])}</h1>
        <div class="package-facts">
          <span class="context-badge"><b>package</b><code>{_esc(package["package_id"])}</code></span>
          <span class="context-badge"><b>preview</b>{_esc(package["preview_classification"])}</span>
          <span class="context-badge"><b>measurements</b>{_esc(package["measurement_count"])}</span>
          <span class="context-badge"><b>visuals</b>{_esc(package["visual_summary_count"])}</span>
        </div>
      </div>
      <div class="attention">{_attention_badges(model["attention"])}</div>
    </header>

    <section>
      <h2>Visual Review</h2>
      {visual_cards}
    </section>

    <section>
      <h2>Measurement Index</h2>
      <table>
        <thead>
          <tr>
            <th>Record</th>
            <th>Label</th>
            <th>Experiment</th>
            <th>Target</th>
            <th>Visuals</th>
            <th>Attention</th>
          </tr>
        </thead>
        <tbody>
          {_measurement_index(model["measurement_index"])}
        </tbody>
      </table>
    </section>

    <footer>
      Static local review artifact. Not a portable package member, public report,
      final GUI component model, dataframe adapter, package import record, or
      package-integrity verification.
    </footer>
  </main>
</body>
</html>
"""
    return html_doc


def _is_in_package_tree(path: Path) -> bool:
    resolved = path.resolve()
    return any(
        (candidate / "package-manifest.json").exists()
        for candidate in (resolved, *resolved.parents)
    )


def write_handoff_package_visual_review_artifact(
    model: dict[str, Any],
    *,
    output_dir: Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Write the static visual-review HTML artifact and return a local receipt."""

    if _is_in_package_tree(output_dir):
        raise ValueError("visual review artifact output_dir must not be in a package tree")
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / _ARTIFACT_NAME
    existed = html_path.exists()
    if existed and not overwrite:
        raise ValueError("visual review artifact already exists")
    html_path.write_text(
        build_handoff_package_visual_review_html(model),
        encoding="utf-8",
    )
    return {
        "artifact_posture": "review_summary",
        "artifact_policy": dict(_EXPECTED_POLICY),
        "html_artifact": {
            "filename": _ARTIFACT_NAME,
            "local_path": str(html_path),
            "created": html_path.is_file(),
            "overwritten": existed,
            "portable_package_member": False,
        },
        "package_id": model["package"]["package_id"],
        "visual_summary_count": model["package"]["visual_summary_count"],
        "measurement_count": model["package"]["measurement_count"],
    }
