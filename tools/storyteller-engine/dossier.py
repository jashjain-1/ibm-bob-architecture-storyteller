"""
dossier.py
~~~~~~~~~~
Publication dossier builder.

One HTML document is the single design source; `scripts/render_pdf.mjs` prints it
to PDF with the installed Chromium (Edge/Chrome). There is no second renderer,
so the PDF and the on-screen preview can never diverge.

Levels
------
L1  Executive   - cover, KPIs, executive summary, context diagram, story, top risks
L2  Engineering - + module graph, flows, routes, models, ranked key functions, clusters
L3  Forensic    - + per-symbol pages (call sites, rationale, git backstory, code),
                  dynamic-risk registry, cycles, churn since last index, appendix

Design rules
------------
- No emoji. No marketing adjectives. Every number is traceable to the model.
- AI prose is labelled with its source (`bob`, `llm`, `derived`) and timestamp.
- Print-first light theme; page breaks are explicit; tables repeat their header.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Iterable, Optional

from model_builder import read_symbol_source

LEVELS = {1: "Executive", 2: "Engineering", 3: "Forensic"}

# Display caps per level: the document grows because the repository has more to
# say, never because a fixed page count is padded.
CAPS = {
    1: {"risks": 8, "flows": 0, "modules": 4, "module_routines": 0, "edges": 0,
        "symbol_rows": 10, "entry_points": 8, "services": 0, "roadmap": 5},
    2: {"risks": 20, "flows": 12, "modules": 16, "module_routines": 8, "symbol_rows": 80,
        "routes": 60, "models": 40, "services": 40, "entry_points": 100, "files": 60,
        "edges": 60, "roadmap": 8},
    3: {"risks": 60, "flows": 12, "modules": 30, "module_routines": 8, "symbol_rows": 400,
        "routes": 200, "models": 200, "services": 200, "entry_points": 500, "files": 0,
        "edges": 200, "deep_symbols": 25, "cycle_groups": 15, "appendix": 600, "roadmap": 12},
}


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def pct(part: int, whole: int) -> str:
    return f"{(100.0 * part / whole):.0f}%" if whole else "0%"


def _fmt_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return esc(value)


# ---------------------------------------------------------------------------
# CSS (plain string: braces stay literal)
# ---------------------------------------------------------------------------

CSS = """
:root {
  --ink: #10151c;
  --muted: #5b6673;
  --line: #dfe4ea;
  --paper: #ffffff;
  --panel: #f6f8fa;
  --accent: #12467b;
  --accent-soft: #e8f0f9;
  --warn: #8a3b12;
  --warn-soft: #fdf1e7;
  --danger: #8f1d1d;
  --danger-soft: #fbecec;
  --ok: #1c5c34;
  --mono: "Cascadia Mono", "Consolas", "SFMono-Regular", "Menlo", monospace;
}
@media screen {
  body.vscode-dark,
  body.vscode-high-contrast,
  body[data-vscode-theme-kind*="dark"] {
    --ink: #e6edf3;
    --muted: #8b949e;
    --line: #30363d;
    --paper: #0d1117;
    --panel: #161b22;
    --accent: #58a6ff;
    --accent-soft: rgba(56, 139, 253, 0.15);
    --warn: #d29922;
    --warn-soft: rgba(210, 153, 34, 0.15);
    --danger: #f85149;
    --danger-soft: rgba(248, 81, 73, 0.15);
    --ok: #3fb950;
  }
}
@media print {
  :root {
    --ink: #10151c !important;
    --muted: #5b6673 !important;
    --line: #dfe4ea !important;
    --paper: #ffffff !important;
    --panel: #f6f8fa !important;
    --accent: #12467b !important;
    --accent-soft: #e8f0f9 !important;
    --warn: #8a3b12 !important;
    --warn-soft: #fdf1e7 !important;
    --danger: #8f1d1d !important;
    --danger-soft: #fbecec !important;
    --ok: #1c5c34 !important;
  }
  html, body {
    background: #ffffff !important;
    color: #10151c !important;
  }
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--paper); color: var(--ink); }
body { font: 10.5pt/1.5 "Segoe UI", "Helvetica Neue", Arial, sans-serif; }
.page { padding: 0 2mm; }
h1, h2, h3, h4 { margin: 0 0 6px 0; line-height: 1.25; font-weight: 650; }
h1 { font-size: 24pt; }
h2 { font-size: 14pt; color: var(--accent); border-bottom: 1.4pt solid var(--accent);
     padding-bottom: 3px; margin-top: 16px; }
h3 { font-size: 11.5pt; margin-top: 12px; }
h4 { font-size: 10pt; margin-top: 10px; color: var(--muted); text-transform: uppercase;
     letter-spacing: .4px; }
p { margin: 0 0 8px 0; }
ul, ol { margin: 0 0 8px 18px; padding: 0; }
li { margin: 0 0 3px 0; }
code, .mono { font-family: var(--mono); font-size: 9pt; }
a { color: var(--accent); text-decoration: none; }
.small { font-size: 9pt; color: var(--muted); }
.section { break-inside: auto; }
.avoid-break { break-inside: avoid; }
.page-break { break-after: page; }
.cover { padding-top: 26mm; }
.cover .kicker { font-size: 9pt; letter-spacing: 2px; text-transform: uppercase; color: var(--muted); }
.cover .rule { height: 3pt; background: var(--accent); width: 42mm; margin: 10px 0 18px 0; }
.cover h1 { font-size: 30pt; letter-spacing: -.5px; }
.cover .subtitle { font-size: 13pt; color: var(--muted); margin-bottom: 22px; }
.meta-grid { display: grid; grid-template-columns: 34mm 1fr 34mm 1fr; gap: 4px 10px;
             font-size: 9pt; border-top: 1px solid var(--line); padding-top: 10px; }
.meta-grid dt { color: var(--muted); }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 14px 0 6px 0; }
.kpi { border: 1px solid var(--line); border-top: 2.5pt solid var(--accent); padding: 8px 10px; }
.kpi .n { font-size: 17pt; font-weight: 700; }
.kpi .l { font-size: 8.5pt; color: var(--muted); text-transform: uppercase; letter-spacing: .3px; }
table { width: 100%; border-collapse: collapse; margin: 6px 0 12px 0; font-size: 9pt; }
thead { display: table-header-group; }
th { background: var(--panel); text-align: left; font-weight: 650; color: var(--ink);
     border-bottom: 1px solid var(--line); padding: 5px 6px; }
td { border-bottom: 1px solid var(--line); padding: 4px 6px; vertical-align: top; }
tr { break-inside: avoid; }
.tag { display: inline-block; padding: 1px 6px; border-radius: 9px; font-size: 8pt;
       border: 1px solid var(--line); background: var(--panel); margin-right: 4px; }
.tag.warn { color: var(--warn); background: var(--warn-soft); border-color: #f0d6c4; }
.tag.danger { color: var(--danger); background: var(--danger-soft); border-color: #f0cccc; }
.tag.ok { color: var(--ok); background: #eaf6ee; border-color: #cfe8d7; }
.callout { border-left: 3pt solid var(--accent); background: var(--accent-soft);
           padding: 9px 12px; margin: 8px 0 12px 0; }
.callout .src { display: block; margin-top: 5px; font-size: 8pt; color: var(--muted); }
.callout.risk { border-left-color: var(--danger); background: var(--danger-soft); }
.note { border: 1px solid var(--line); background: var(--panel); padding: 8px 10px;
        font-size: 9pt; margin: 8px 0 12px 0; }
pre { background: #0f172a; color: #e6edf5; padding: 8px 10px; border-radius: 3px;
      font-family: var(--mono); font-size: 8pt; line-height: 1.4; overflow: hidden;
      white-space: pre-wrap; margin: 6px 0 10px 0; }
.chain { font-family: var(--mono); font-size: 9pt; }
.chain .step { border: 1px solid var(--line); background: var(--panel); padding: 1px 6px;
               border-radius: 3px; margin-right: 3px; display: inline-block; margin-bottom: 3px; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.symbol-card { border: 1px solid var(--line); border-radius: 3px; padding: 10px 12px;
               margin: 0 0 12px 0; break-inside: avoid; }
.symbol-card .head { display: flex; justify-content: space-between; align-items: baseline; }
.symbol-card .name { font-family: var(--mono); font-size: 11pt; font-weight: 650; }
.symbol-card .where { font-size: 8.5pt; color: var(--muted); }
.footer-note { margin-top: 14px; border-top: 1px solid var(--line); padding-top: 6px;
               font-size: 8pt; color: var(--muted); }
@page { size: A4; margin: 17mm 15mm 15mm 15mm; }

/* --- cover ---------------------------------------------------------------- */
.cover { min-height: 250mm; display: flex; flex-direction: column; break-after: page; padding-top: 12mm; }
.cover .headline { font-size: 15pt; line-height: 1.35; font-weight: 600; max-width: 150mm;
                  margin: 0 0 9mm 0; }
.cover .facts { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px;
                margin: 0 0 9mm 0; }
.cover .fact { border-top: 2pt solid var(--accent); padding-top: 6px; }
.cover .fact .v { font-size: 14pt; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1.1; }
.cover .fact .k { font-size: 8.5pt; color: var(--muted); }
.cover .colophon { margin-top: auto; border-top: 1px solid var(--line); padding-top: 7px;
                   font-size: 8pt; color: var(--muted); }

/* --- contents ------------------------------------------------------------- */
.contents { break-after: page; }
.contents ol { list-style: none; margin: 4px 0 0 0; padding: 0; counter-reset: toc; }
.contents li { display: flex; align-items: baseline; gap: 9px; padding: 4px 0;
               border-bottom: .4pt dotted #ccd4dd; break-inside: avoid; }
.contents li::before { counter-increment: toc; content: counter(toc); width: 7mm;
                       color: var(--muted); font-variant-numeric: tabular-nums; font-size: 9pt; }
.contents .t { flex: 1; }
.contents .t a { color: var(--ink); }
.contents .tn { display: block; font-size: 8.2pt; color: var(--muted); margin-top: 1px; }

/* --- metrics -------------------------------------------------------------- */
.metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px 10px; margin: 10px 0 4px 0; }
.metric { border: 1px solid var(--line); border-left: 2.5pt solid var(--accent); padding: 7px 9px;
          break-inside: avoid; }
.metric .v { font-size: 15pt; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1.1; }
.metric .k { font-size: 8.5pt; text-transform: uppercase; letter-spacing: .3px; color: var(--muted); }
.metric .sub { font-size: 8pt; color: var(--muted); margin-top: 2px; }
.notes { margin: 6px 0 2px 0; font-size: 8.8pt; color: var(--muted); }
.notes span { margin-right: 12px; }

/* --- section leads and print discipline ----------------------------------- */
p.lead { font-size: 10pt; color: #39424d; margin: 2px 0 10px 0; max-width: 168mm; }
.figure-note { font-size: 8pt; color: var(--muted); margin: -4px 0 12px 0; }
h2 { break-after: avoid; }
h3, h4 { break-after: avoid; }
p, li { orphans: 3; widows: 3; }
table { break-inside: auto; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
.metric, .symbol-card, .callout, .note, pre, figure, svg { break-inside: avoid; }
svg { max-width: 100%; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
body { font-size: 10pt; line-height: 1.45; }
td, th { font-size: 8.6pt; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
"""


def _doc_shell(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        f"<title>{esc(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
        f"<div class=\"page\">\n{body}\n</div>\n</body>\n</html>\n"
    )


# ---------------------------------------------------------------------------
# SVG diagrams (deterministic layout, no external chart library)
# ---------------------------------------------------------------------------

def _svg_text(x: float, y: float, text: str, size: float = 9, anchor: str = "middle",
              weight: str = "400", fill: str = "#10151c") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" '
            f'font-weight="{weight}" fill="{fill}" font-family="Segoe UI, Arial, sans-serif">'
            f'{esc(text)}</text>')


def _svg_box(x: float, y: float, w: float, h: float, label: str, sub: str = "",
             stroke: str = "#c9d3dd", fill: str = "#f6f8fa", accent: str = "#12467b") -> str:
    parts = [
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="3" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="1"/>',
        _svg_text(x + w / 2, y + 13, label[:34], 9, "middle", "600", accent),
    ]
    if sub:
        parts.append(_svg_text(x + w / 2, y + 24, sub[:44], 7.5, "middle", "400", "#5b6673"))
    return "".join(parts)


def svg_context(model: dict[str, Any]) -> str:
    """Inputs -> modules -> state. One page-width diagram, no hairball."""
    entries = [e for e in (model.get("entry_points") or []) if e.get("name")][:6]
    modules = (model.get("module_graph") or {}).get("nodes", [])[:8]
    models_ = (model.get("layers") or {}).get("models", [])[:6]
    routes = (model.get("layers") or {}).get("routes", [])

    W, H = 760, 100 + 34 * max(len(entries), len(modules), len(models_), 3)
    box_w, box_h = 190, 30
    cols = {"in": 20, "core": 285, "data": 550}
    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" role="img">']
    out.append(_svg_text(cols["in"] + box_w / 2, 18, "ENTRY POINTS", 8.5, "middle", "700", "#5b6673"))
    out.append(_svg_text(cols["core"] + box_w / 2, 18, "MODULES", 8.5, "middle", "700", "#5b6673"))
    out.append(_svg_text(cols["data"] + box_w / 2, 18, "STATE & OUTPUTS", 8.5, "middle", "700", "#5b6673"))

    y = 30
    for entry in entries:
        label = f"{entry.get('name', '')}"
        sub = f"{entry.get('kind', '')} - {entry.get('file_path', '')}"
        out.append(_svg_box(cols["in"], y, box_w, box_h, label, sub))
        y += 40
    core_y = 30
    for node in modules:
        label = f"{node.get('label', node.get('id', ''))}"
        sub = f"{node.get('symbols', 0)} symbols - {node.get('files', 0)} files"
        stroke = "#8f1d1d" if node.get("has_cycle") else "#c9d3dd"
        out.append(_svg_box(cols["core"], core_y, box_w, box_h, label, sub, stroke=stroke))
        core_y += 40
    data_y = 30
    for dim in models_[:3]:
        out.append(_svg_box(cols["data"], data_y, box_w, box_h,
                            dim.get("name", "model"), f"table {dim.get('table_name', '')}",
                            fill="#eaf6ee", stroke="#cfe8d7"))
        data_y += 40
    if routes:
        out.append(_svg_box(cols["data"], data_y, box_w, box_h, f"{len(routes)} API routes",
                            "heuristic detection", fill="#e8f0f9", stroke="#cfe0f0"))
        data_y += 40
    if not models_:
        out.append(_svg_box(cols["data"], data_y, box_w, box_h, "No ORM models detected",
                            "state handled in code", fill="#ffffff"))
        data_y += 40

    mid_core = cols["core"] - 14
    mid_data = cols["data"] - 14
    max_y = min(H - 24, y + 6)
    for i in range(max(1, len(entries))):
        yy = 30 + 15 + 40 * i
        if yy < max_y:
            out.append(f'<path d="M{cols["in"] + box_w} {yy} H{mid_core}" stroke="#c9d3dd" '
                       f'fill="none" marker-end="url(#a)"/>')
    for i in range(max(1, len(modules))):
        yy = 30 + 15 + 40 * i
        if yy < max_y:
            out.append(f'<path d="M{cols["core"] + box_w} {yy} H{mid_data}" stroke="#c9d3dd" '
                       f'fill="none" marker-end="url(#a)"/>')
    out.insert(1, '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
                  'markerHeight="6" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#9fb0c0"/></marker></defs>')
    out.append("</svg>")
    return "".join(out)


def svg_module_graph(model: dict[str, Any]) -> str:
    """Module dependencies; red ring = module participates in a cycle."""
    nodes = (model.get("module_graph") or {}).get("nodes", [])[:24]
    edges = (model.get("module_graph") or {}).get("edges", [])
    if not nodes:
        return ""
    W, H = 760, 420
    cx, cy, radius = 380, 200, 140
    import math
    positions: dict[str, tuple[float, float]] = {}
    for i, node in enumerate(nodes):
        angle = 2 * math.pi * i / len(nodes) - math.pi / 2
        positions[node["id"]] = (cx + radius * math.cos(angle) * 1.25,
                                 cy + radius * math.sin(angle))
    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" role="img">']
    weight_by_key = {(e["from"], e["to"]): e.get("weight", 1) for e in edges}
    drawn = set()
    for edge in edges:
        src, tgt = edge["from"], edge["to"]
        if src not in positions or tgt not in positions or (src, tgt) in drawn:
            continue
        drawn.add((src, tgt))
        x1, y1 = positions[src]
        x2, y2 = positions[tgt]
        width = min(3.2, 0.7 + 0.25 * edge.get("weight", 1))
        out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                   f'stroke="#c2ccd8" stroke-width="{width:.1f}"/>')
    for node in nodes:
        x, y = positions[node["id"]]
        r = 10 + min(16, 1.6 * node.get("symbols", 1) ** 0.6)
        stroke = "#8f1d1d" if node.get("has_cycle") else "#12467b"
        fill = "#fbecec" if node.get("has_cycle") else "#e8f0f9"
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{fill}" '
                   f'stroke="{stroke}" stroke-width="1.4"/>')
        label = node.get("label", node["id"]).split("/")[-1][:18]
        out.append(_svg_text(x, y + r + 9, label, 7.5, "middle", "600"))
        out.append(_svg_text(x, y + r + 17, f"{node.get('symbols', 0)} sym", 6.5, "middle", "400", "#5b6673"))
    out.append(_svg_text(12, H - 8, "Red ring: module participates in a dependency cycle", 8, "start", "400", "#5b6673"))
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------

def _symbol_index(model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["id"]: s for s in model.get("symbols", [])}


def _display(sym: dict[str, Any]) -> str:
    return sym.get("qualified") or sym.get("name") or sym.get("id", "")


def _loc(sym: dict[str, Any]) -> str:
    return f"{sym.get('file_path', '')}:{sym.get('line_start', 0)}"


def _flag_tag(flag: str) -> str:
    cls = "danger" if flag.startswith("dynamic:") else ("ok" if flag in ("cache", "retry") else "warn")
    return f'<span class="tag {cls}">{esc(flag)}</span>'


def _source_label(entry: dict[str, Any]) -> str:
    source = str(entry.get("source") or "auto")
    model_name = str(entry.get("model") or "")
    generated = str(entry.get("generated_at") or "")
    label = {
        "bob": "IBM Bob", "llm": "local LLM", "auto": "deterministic fallback",
        "derived": "derived from model", "cached": "cached",
    }.get(source, source)
    if model_name and source in ("bob", "llm"):
        label += f" ({model_name})"
    if generated:
        label += f", {generated}"
    return label


def _insight_for(insights: Any, symbol_id: str) -> dict[str, Any]:
    if insights is None:
        return {}
    if isinstance(insights, dict):
        return insights.get(symbol_id) or {}
    getter = getattr(insights, "get", None)
    if callable(getter):
        try:
            return getter(symbol_id) or {}
        except Exception:
            return {}
    return {}


def _page_break() -> str:
    return '<div class="page-break"></div>'


# Sections register themselves as they are emitted, so the contents page and
# the headings can never disagree about a title, a target id or a one-line lead.
_TOC: list[tuple[str, str, str]] = []


def _anchor(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return f"sec-{slug or 'section'}"


def _h2(text: str, lead: str = "") -> str:
    """A section heading, optionally followed by the sentence that frames it."""
    _TOC.append((text, _anchor(text), lead))
    heading = f'<h2 id="{_anchor(text)}">{esc(text)}</h2>'
    return f'{heading}\n<p class="lead">{esc(lead)}</p>' if lead else heading


def _header_row(cells: Iterable[str]) -> str:
    return "<tr>" + "".join(f"<th>{esc(c)}</th>" for c in cells) + "</tr>"


def _row(cells: Iterable[str]) -> str:
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def _table(headers: Iterable[str], rows: list[str]) -> str:
    if not rows:
        return ""
    return f"<table><thead>{_header_row(headers)}</thead><tbody>{''.join(rows)}</tbody></table>"


LEVEL_TITLES = {1: "Executive dossier", 2: "Engineering dossier", 3: "Forensic dossier"}

LEVEL_BLURBS = {
    1: "Orientation for stakeholders: what the system is, what it contains, and where risk concentrates.",
    2: "Architecture for engineers: flows, modules, routes, data models and the routines that carry the logic.",
    3: "Evidence for reviewers: per-symbol call sites, file history, dynamic dispatch and the full appendix.",
}


# ---------------------------------------------------------------------------
# Level 1 sections
# ---------------------------------------------------------------------------

def _metric(value: Any, label: str, sub: str = "") -> str:
    note = f'<div class="sub">{esc(sub)}</div>' if sub else ""
    return (f'<div class="metric"><div class="v">{_fmt_int(value)}</div>'
            f'<div class="k">{esc(label)}</div>{note}</div>')


def _kpi(value: Any, label: str) -> str:
    """Card for the cluster and delta sections, styled like the headline metrics."""
    return _metric(value, label)


def _metric_notes(model: dict[str, Any]) -> str:
    """Facts that do not deserve the same weight as a headline number."""
    stats = model.get("stats", {}) or {}
    counts = (model.get("clusters", {}) or {}).get("counts", {}) or {}
    cyclic = counts.get("cyclic", 0)
    dynamic = counts.get("dynamic", 0)
    notes = [
        "no dependency cycles detected" if not cyclic
        else f"{cyclic} symbols sit in dependency cycles",
        f"{dynamic} dynamic dispatch site" + ("" if dynamic == 1 else "s"),
    ]
    tests = stats.get("test_functions", 0)
    production = stats.get("production_functions", 0)
    if tests or production:
        notes.append(f"{tests} test functions against {production} production functions")
    unresolved = stats.get("unresolved_call_names", 0)
    if unresolved:
        notes.append(f"{unresolved} call names unresolved outside the model")
    cells = "".join(f"<span>{esc(note)}</span>" for note in notes)
    return f'<div class="notes">{cells}</div>'


def section_metrics(model: dict[str, Any], level: int) -> str:
    """A curated handful of numbers; the smaller ones are demoted to notes."""
    s = model.get("stats", {}) or {}
    cards = [
        _metric(s.get("files", 0), "files", f"{s.get('production_files', 0)} production"),
        _metric(s.get("symbols", 0), "symbols",
                f"{s.get('functions', 0)} functions, {s.get('methods', 0)} methods, "
                f"{s.get('classes', 0)} classes"),
        _metric(s.get("resolved_call_edges", 0), "resolved call edges",
                f"across {s.get('modules', 0)} modules"),
        _metric(s.get("entry_points", 0), "entry points", "where execution can start"),
    ]
    def extra(value: Any, label: str, sub: str = "") -> list[str]:
        # A tile showing zero says nothing the notes underneath do not already say.
        return [_metric(value, label, sub)] if int(value or 0) else []

    if level >= 2:
        cards += extra(s.get("routes"), "routes", "heuristic detection")
        cards += extra(s.get("models"), "data models", "ORM declarations")
        cards += extra(s.get("services"), "outbound service calls", "client calls")
        cards += extra(len(model.get("flows") or []), "traced flows", "from entry points")
    if level >= 3:
        cards += extra(s.get("test_functions"), "test functions")
        cards += extra(s.get("production_functions"), "production functions")
        cards += extra(s.get("files_with_history"), "files with git history")
        cards += extra(len((model.get("clusters", {}) or {}).get("sccs") or []), "cycle groups")
    lead = ("Four numbers carry the shape of this codebase; the rest is detail." if level == 1
            else "The headline numbers first, then the layer counts this level adds.")
    return (_h2("Repository at a glance", lead)
            + f'<div class="metrics">{"".join(cards)}</div>'
            + _metric_notes(model))


def section_contents() -> str:
    """The contents page: sections in document order, each with the question it answers.

    No page numbers: see the note in scripts/render_pdf.mjs - Chromium cannot
    resolve them, and a guessed number is worse than none on a printed dossier.
    """
    rows = []
    for title, anchor, lead in _TOC:
        note = f'<span class="tn">{esc(lead)}</span>' if lead else ""
        rows.append(f'<li><span class="t"><a href="#{anchor}">{esc(title)}</a>{note}</span></li>')
    return (
        '<section class="contents">'
        '<h2 id="sec-contents">Contents</h2>'
        '<p class="lead">Every section at this level, in the order it appears, with the '
        'question it answers. The printed PDF carries the same order as bookmarks and '
        'numbers every page in its footer.</p>'
        f'<ol>{"".join(rows)}</ol></section>'
    )


def _cover_headline(model: dict[str, Any]) -> str:
    """The one sentence a reader should take from the cover."""
    from insights import language_list

    s = model.get("stats", {}) or {}
    languages = language_list(s.get("languages") or []) or "unrecognised languages"
    return (
        f'<p class="headline">{_fmt_int(s.get("files", 0))} files and '
        f'{_fmt_int(s.get("symbols", 0))} symbols across {_fmt_int(s.get("modules", 0))} '
        f'modules, written in {esc(languages)}.</p>'
    )


def _cover_facts(model: dict[str, Any]) -> str:
    s = model.get("stats", {}) or {}
    facts = [
        (_fmt_int(s.get("symbols", 0)), "symbols indexed"),
        (_fmt_int(s.get("files", 0)), "files scanned"),
        (_fmt_int(s.get("resolved_call_edges", 0)), "resolved call edges"),
    ]
    cells = "".join(
        f'<div class="fact"><div class="v">{esc(value)}</div><div class="k">{esc(label)}</div></div>'
        for value, label in facts
    )
    return f'<div class="facts">{cells}</div>'


def _cover_colophon(model: dict[str, Any]) -> str:
    """Where the logic concentrates, how tangled it is, and what generated this."""
    symbols = {sym["id"]: sym for sym in model.get("symbols", [])}
    pivotal = (model.get("pivotal") or [])[:1]
    counts = (model.get("clusters", {}) or {}).get("counts", {}) or {}
    lines = []
    hub = symbols.get(pivotal[0]["id"]) if pivotal else None
    if hub:
        lines.append(
            f"Highest-impact routine: {hub.get('qualified') or hub.get('name')} "
            f"({_fmt_int(pivotal[0].get('fan_in', 0))} callers, "
            f"{_fmt_int(pivotal[0].get('cross_file_callers', 0))} from other files)."
        )
    lines.append(
        "No dependency cycles detected." if not counts.get("cyclic")
        else f"{counts.get('cyclic')} symbols sit in dependency cycles."
    )
    lines.append(
        "Every count derives from one architecture model; AI-written text is labelled with its source, "
        "and unlabelled text is derived from the model. The PDF is a print of this document."
    )
    body = " ".join(esc(line) for line in lines)
    return f'<div class="colophon">{body}</div>'


def section_cover(model: dict[str, Any], level: int) -> str:
    repo = model.get("repo", {}) or {}
    fp = repo.get("fingerprint") or {}
    stats = model.get("stats", {}) or {}
    meta = model.get("meta", {}) or {}
    items = [
        ("Repository", repo.get("name") or "repository"),
        ("Branch", fp.get("branch") or "n/a"),
        ("Commit", (fp.get("head") or "n/a")[:12]),
        ("Working tree", "uncommitted changes present" if fp.get("dirty") else "clean"),
        ("Generated (UTC)", model.get("generated_at", "")),
        ("Analysis engine", str(meta.get("engine", "n/a"))),
        ("Languages", ", ".join(stats.get("languages") or []) or "n/a"),
        ("Model schema", model.get("schema", "")),
    ]
    pairs = "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in items)
    return (
        '<section class="cover">'
        '<div class="kicker">Architecture Storyteller</div>'
        '<div class="rule"></div>'
        f'<h1>{esc(repo.get("name") or "Repository")}</h1>'
        f'<div class="subtitle">{esc(LEVEL_TITLES.get(level, "Dossier"))} - Level {level}</div>'
        f'<p>{esc(LEVEL_BLURBS.get(level, ""))}</p>'
        f'{_cover_headline(model)}'
        f'{_cover_facts(model)}'
        f'<dl class="meta-grid">{pairs}</dl>'
        f'{_cover_colophon(model)}'
        '</section>'
    )


def section_exec_summary(narratives: dict[str, Any]) -> str:
    text = str(narratives.get("exec_summary") or "")
    if not text:
        return ""
    source_key = str(narratives.get("source") or "derived")
    source = _source_label({
        "source": source_key,
        "model": narratives.get("model"),
        "generated_at": narratives.get("generated_at"),
    })
    # The deterministic summary is structured HTML. Provider text is plain
    # prose and must never be printed raw: only the derived source may carry
    # markup, everything else is escaped paragraph by paragraph.
    structured = source_key in ("derived", "cached") and (
        "<p" in text or "<h4" in text or "<ul" in text
    )
    if structured:
        body = text
    else:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        body = "".join(f"<p>{esc(p)}</p>" for p in paragraphs) or "<p></p>"
    return (
        _h2("Executive summary", 'What this codebase is, what carries it, and where reading it gets expensive.')
        + '<div class="callout">'
        + body
        + f'<span class="src">Source: {esc(source)}</span>'
        + "</div>"
    )


def section_story(narratives: dict[str, Any]) -> str:
    chapters = narratives.get("story") or []
    if not chapters:
        return ""
    parts = [_h2("How this system reads", 'A narrated walkthrough: entry points, flows, hubs, state, and what is risky.')]
    for chapter in chapters:
        content = str(chapter.get("content", ""))
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        if len(lines) <= 1:
            body = f"<p>{esc(lines[0] if lines else content)}</p>"
        else:
            body = "<ul>" + "".join(f'<li class="mono">{esc(ln)}</li>' for ln in lines) + "</ul>"
        parts.append(f'<div class="avoid-break"><h3>{esc(chapter.get("title", ""))}</h3>{body}</div>')
    source = _source_label({
        "source": narratives.get("story_source") or narratives.get("source") or "derived",
        "model": narratives.get("model"),
        "generated_at": narratives.get("generated_at"),
    })
    parts.append(f'<p class="small">Source: {esc(source)}</p>')
    return "".join(parts)


def section_roadmap(narratives: dict[str, Any], limit: int) -> str:
    """Ordered modernization steps, AI-written when a provider answered."""
    steps = [str(step) for step in (narratives.get("roadmap") or []) if str(step).strip()][:limit]
    if not steps:
        return ""
    source = _source_label({
        "source": narratives.get("roadmap_source") or narratives.get("source") or "derived",
        "model": narratives.get("model"),
        "generated_at": narratives.get("generated_at"),
    })
    items = "".join(f'<li>{esc(step)}</li>' for step in steps)
    return (
        _h2("Modernization roadmap", 'What to change first, in order, grounded in the evidence in this model.')
        + f'<ol class="reading-order">{items}</ol>'
        + f'<p class="small">Source: {esc(source)}</p>'
    )


# ---------------------------------------------------------------------------
# Structural sections
# ---------------------------------------------------------------------------

def section_context(model: dict[str, Any]) -> str:
    svg = svg_context(model)
    body = svg or '<div class="note">No entry points or modules were detected.</div>'
    return _h2("System context", 'Entry points, modules and state on one diagram, so the shape is visible before the detail.') + body


def section_module_graph(model: dict[str, Any]) -> str:
    svg = svg_module_graph(model)
    return (_h2("Module dependencies", 'Modules as nodes, with the red ring marking a module inside a dependency cycle.') + svg) if svg else ""


def section_flows(model: dict[str, Any], limit: int) -> str:
    flows = (model.get("flows") or [])[:limit]
    if not flows:
        return ""
    parts = [_h2("Execution flows", 'Call chains followed from real entry points; where none resolve, hub routines stand in.')]
    for flow in flows:
        chain = flow.get("chain") or []
        steps = "".join(f'<span class="step">{esc(n.get("name", ""))}</span>' for n in chain)
        parts.append(
            '<div class="avoid-break">'
            f'<h4>{esc(flow.get("entry", ""))} <span class="tag">{esc(flow.get("kind", "flow"))}</span> '
            f'<span class="small mono">{esc(flow.get("file", ""))}</span></h4>'
            f'<div class="chain">{steps}</div></div>'
        )
    return "".join(parts)


def _layer_note(model: dict[str, Any], key: str) -> str:
    source = ((model.get("layers") or {}).get("sources") or {}).get(key, "")
    if not source:
        return ""
    return f'<p class="small">Detection source: {esc(source)}.</p>'


def section_routes(model: dict[str, Any], limit: int) -> str:
    routes = ((model.get("layers") or {}).get("routes") or [])[:limit]
    if not routes:
        return ""
    rows = []
    for r in routes:
        params = ", ".join(str(p) for p in (r.get("params") or []))
        rows.append(_row([
            f'<span class="mono">{esc(r.get("method", ""))}</span>',
            f'<span class="mono">{esc(r.get("path", ""))}</span>',
            esc(r.get("handler_name", "")),
            esc(r.get("framework", "")),
            f'<span class="mono small">{esc(r.get("file_path", ""))}:{_fmt_int(r.get("line_start", 0))}</span>',
            f'<span class="small">{esc(params)}</span>',
        ]))
    return (_h2(f"API routes ({len(routes)} shown)", 'Detected routes with their handler and source file; detection is heuristic and labelled as such.') + _layer_note(model, "routes")
            + _table(["Method", "Path", "Handler", "Framework", "Location", "Parameters"], rows))


def section_models(model: dict[str, Any], limit: int) -> str:
    models_ = ((model.get("layers") or {}).get("models") or [])[:limit]
    if not models_:
        return ""
    rows = []
    for m in models_:
        fields = len(m.get("fields") or [])
        rels = len(m.get("relationships") or [])
        rows.append(_row([
            f'<span class="mono">{esc(m.get("name", ""))}</span>',
            f'<span class="mono">{esc(m.get("table_name", ""))}</span>',
            esc(m.get("orm_type", "")),
            _fmt_int(fields),
            _fmt_int(rels),
            f'<span class="mono small">{esc(m.get("file_path", ""))}:{_fmt_int(m.get("line_start", 0))}</span>',
        ]))
    return (_h2(f"Data models ({len(models_)} shown)", 'Declared models and their fields, read from the ORM declarations in this repository.') + _layer_note(model, "models")
            + _table(["Model", "Table", "ORM", "Fields", "Relations", "Location"], rows))


def section_services(model: dict[str, Any], limit: int) -> str:
    services = ((model.get("layers") or {}).get("services") or [])[:limit]
    if not services:
        return ""
    rows = []
    for c in services:
        rows.append(_row([
            f'<span class="mono">{esc(c.get("function_name", ""))}</span>',
            f'<span class="mono">{esc(c.get("http_method", ""))}</span>',
            f'<span class="mono">{esc(c.get("target_endpoint", ""))}</span>',
            esc(c.get("client_library", "")),
            esc(c.get("calling_component", "")),
            f'<span class="mono small">{esc(c.get("file_path", ""))}:{_fmt_int(c.get("line_number", 0))}</span>',
        ]))
    return (_h2(f"Outbound service calls ({len(services)} shown)", 'Client calls leaving this process, grouped by the target they address.') + _layer_note(model, "services")
            + _table(["Function", "HTTP", "Target", "Client", "Caller", "Location"], rows))


# ---------------------------------------------------------------------------
# Risk register
# ---------------------------------------------------------------------------

def _risks(model: dict[str, Any]) -> list[dict[str, Any]]:
    symbols = _symbol_index(model)
    clusters = model.get("clusters", {}) or {}
    stats = model.get("stats", {}) or {}
    sccs = clusters.get("sccs") or []
    dynamic = clusters.get("dynamic") or []
    risks: list[dict[str, Any]] = []

    for group in sccs[:8]:
        members = [symbols[i] for i in group if i in symbols]
        names = [m["name"] for m in members[:6]]
        files = sorted({m["file_path"] for m in members})
        severity = "danger" if len(group) >= 3 else "warn"
        risks.append({
            "severity": severity,
            "title": f"Circular dependency across {len(group)} symbols",
            "detail": ("Mutual calls make isolated testing and extraction unsafe. Members: "
                       + ", ".join(names) + ("..." if len(group) > 6 else "") + "."),
            "evidence": f"{len(files)} file(s): " + ", ".join(files[:4]) + ("..." if len(files) > 4 else ""),
            "weight": 900 + len(group),
        })

    if dynamic:
        names = sorted(symbols[i]["name"] for i in dynamic[:8] if i in symbols)
        risks.append({
            "severity": "warn",
            "title": f"{len(dynamic)} symbols use dynamic dispatch",
            "detail": ("Calls through attributes, subscripts, namespaces or reflection cannot be "
                       "verified statically; the map shows resolved edges only."),
            "evidence": ", ".join(names) + ("..." if len(dynamic) > 8 else ""),
            "weight": 700 + min(len(dynamic), 99),
        })

    hotspots = sorted(
        (s for s in symbols.values()
         if s.get("kind") in ("function", "method") and int(s.get("complexity") or 0) >= 12),
        key=lambda s: (-int(s.get("complexity") or 0), s["id"]),
    )[:6]
    if hotspots:
        detail = "; ".join(
            f"{_display(s)} (complexity {s['complexity']}, {s['file_path']}:{s['line_start']})"
            for s in hotspots[:4]
        )
        risks.append({
            "severity": "warn" if len(hotspots) < 4 else "danger",
            "title": f"{len(hotspots)} routine(s) at complexity 12 or above",
            "detail": "High branching routines concentrate defects and resist safe change. " + detail + ".",
            "evidence": "Complexity computed per function body (Python AST, lexical fallback otherwise).",
            "weight": 600 + len(hotspots),
        })

    prod = int(stats.get("production_functions") or 0)
    tests = int(stats.get("test_functions") or 0)
    if prod and (tests == 0 or tests / max(prod, 1) < 0.15):
        risks.append({
            "severity": "warn",
            "title": "Thin test surface",
            "detail": f"{tests} test function(s) for {prod} production function(s). "
                      "Structural changes lack a safety net.",
            "evidence": "Test detection uses path and name conventions, not coverage data.",
            "weight": 500,
        })

    risks.sort(key=lambda r: (-int(r["weight"]), r["title"]))
    return risks


def section_risks(model: dict[str, Any], limit: int) -> str:
    risks = _risks(model)[:limit]
    if not risks:
        return _h2("Risk register", 'Findings ranked by evidence strength, each with the signal that produced it.') + '<div class="note">No structural risks were detected by the model.</div>'
    rows = []
    for risk in risks:
        tag = f'<span class="tag {risk["severity"]}">{risk["severity"]}</span>'
        rows.append(_row([
            tag,
            esc(risk["title"]),
            esc(risk["detail"]),
            f'<span class="small mono">{esc(risk["evidence"])}</span>',
        ]))
    return _h2("Risk register", 'Findings ranked by evidence strength, each with the signal that produced it.') + _table(["Severity", "Finding", "Why it matters", "Evidence"], rows)


# ---------------------------------------------------------------------------
# Ranked routines, clusters, delta
# ---------------------------------------------------------------------------

def section_key_functions(model: dict[str, Any], insights: Any, limit: int,
                          show_why: bool = False) -> str:
    if limit <= 0:
        return ""
    symbols = _symbol_index(model)
    records: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for entry in (model.get("pivotal") or []):
        sym = symbols.get(entry["id"])
        if not sym or sym.get("is_test"):
            continue
        records.append((entry, sym, _insight_for(insights, sym["id"])))
        if len(records) >= limit:
            break
    if not records:
        return ""
    has_insight = any(insight.get("micro") for _, _, insight in records)
    headers = ["#", "Routine", "Location", "Callers", "Cross-file", "Complexity", "Flags"]
    if has_insight:
        headers.append("What it does" + (" / why it matters" if show_why else ""))
    rows = []
    for rank, (entry, sym, insight) in enumerate(records, start=1):
        cells = [
            f'<span class="small">{rank}</span>',
            f'<span class="mono">{esc(_display(sym))}</span>',
            f'<span class="mono small">{esc(_loc(sym))}</span>',
            _fmt_int(entry.get("fan_in", 0)),
            _fmt_int(entry.get("cross_file_callers", 0)),
            _fmt_int(entry.get("complexity", 0)),
            " ".join(_flag_tag(f) for f in (sym.get("flags") or [])[:3]),
        ]
        if has_insight:
            micro = str(insight.get("micro") or "")
            why = str(insight.get("why") or "")
            detail = f'<span class="mono">{esc(micro)}</span>' if micro else '<span class="small">-</span>'
            if show_why and why:
                detail += f'<br><span class="small">{esc(why)}</span>'
            cells.append(detail)
        rows.append(_row(cells))
    note = ('<p class="small">Insight text is cached per symbol content hash: only added or changed '
            'symbols are sent to a provider on re-index.</p>') if has_insight else ""
    return _h2("Key routines (ranked by dependency impact)", 'Routines ranked by dependency impact: callers, fan-in and complexity, not line count.') + _table(headers, rows) + note


def section_clusters(model: dict[str, Any], level: int) -> str:
    clusters = model.get("clusters", {}) or {}
    counts = clusters.get("counts", {}) or {}
    if not any(counts.values()):
        return ""
    symbols = _symbol_index(model)
    cards = [
        _kpi(counts.get("independent", 0), "independent (no resolved calls)"),
        _kpi(counts.get("cyclic", 0), "inside dependency cycles"),
        _kpi(counts.get("dynamic", 0), "dynamic dispatch"),
    ]
    parts = [_h2("Dependency clusters", 'How the symbol graph partitions: independent work, cyclic groups and dynamic dispatch.'), f'<div class="metrics">{"".join(cards)}</div>',
             '<p class="small">Independent functions have no resolved outgoing calls. Cyclic symbols '
             'are strongly connected to each other. Dynamic symbols call through attributes, '
             'subscripts or namespaces and cannot be verified statically.</p>']
    if level >= 3:
        groups = clusters.get("sccs") or []
        if groups:
            rows = []
            for index, group in enumerate(groups[:30], start=1):
                members = [symbols[g] for g in group if g in symbols]
                names = ", ".join(_display(m) for m in members[:8])
                files = sorted({m["file_path"] for m in members})
                rows.append(_row([
                    f'<span class="small">{index}</span>',
                    _fmt_int(len(group)),
                    f'<span class="mono small">{esc(names)}</span>',
                    f'<span class="small mono">{esc(", ".join(files[:3]))}</span>',
                ]))
            parts.append(f'<h3>Cycle groups ({len(groups)})</h3>' + _table(["#", "Size", "Members", "Files"], rows))
    return "".join(parts)


def section_delta(delta: Optional[dict[str, Any]], level: int) -> str:
    if not delta:
        return ""
    counts = delta.get("counts") or {}
    if delta.get("first_run"):
        return (_h2("Index delta", 'What changed since the previous index of this repository.')
                + '<div class="note">First index for this cache: '
                + f'{_fmt_int(counts.get("added", 0))} symbol(s) recorded, '
                + f'{_fmt_int(counts.get("removed", 0))} pruned.</div>')
    cards = [
        _kpi(counts.get("added", 0), "added"),
        _kpi(counts.get("changed", 0), "changed"),
        _kpi(counts.get("removed", 0), "removed"),
        _kpi(counts.get("unchanged", 0), "unchanged"),
    ]
    body = _h2("Changes since last index", 'What changed since the previous index of this repository.') + f'<div class="metrics">{"".join(cards)}</div>'
    if delta.get("fingerprint_changed"):
        body += '<p class="small">The working-tree fingerprint changed since the previous index.</p>'
    if level >= 3:
        symbols = None
        for label, key in (("Added", "added"), ("Changed", "changed"), ("Removed", "removed")):
            ids = list(delta.get(key) or [])
            if ids:
                shown = ", ".join(ids[:40]) + ("..." if len(ids) > 40 else "")
                body += f'<h4>{label} ({len(ids)})</h4><p class="mono small">{esc(shown)}</p>'
    return body


# ---------------------------------------------------------------------------
# Forensic layer (Level 3)
# ---------------------------------------------------------------------------

def _deep_candidates(model: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    symbols = _symbol_index(model)
    clusters = model.get("clusters", {}) or {}
    flagged = set(clusters.get("cyclic") or []) | set(clusters.get("dynamic") or [])
    scored: list[tuple[float, dict[str, Any]]] = []
    for entry in (model.get("pivotal") or []):
        sym = symbols.get(entry["id"])
        if not sym or sym.get("is_test"):
            continue
        score = float(entry.get("score") or 0)
        if sym["id"] in flagged:
            score += 6
        if sym.get("flags"):
            score += 2
        scored.append((score, sym))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    picked: list[dict[str, Any]] = []
    per_file: dict[str, int] = {}
    for _, sym in scored:
        if per_file.get(sym["file_path"], 0) >= 3:
            continue
        per_file[sym["file_path"]] = per_file.get(sym["file_path"], 0) + 1
        picked.append(sym)
        if len(picked) >= limit:
            break
    return picked


def section_deep_symbols(model: dict[str, Any], insights: Any, root: Any, limit: int,
                         max_lines: int = 60) -> str:
    if limit <= 0 or not root:
        return ""
    symbols = _symbol_index(model)
    picks = _deep_candidates(model, limit)
    if not picks:
        return ""
    files_git = {f.get("path", ""): (f.get("git") or {}) for f in model.get("files", [])}
    parts = [
        _h2(f"Symbol evidence ({len(picks)} of {_fmt_int(len(symbols))} symbols)", 'Per-symbol evidence: call sites, stored summary, git history and the source on disk.'),
        '<p class="small">Highest-impact routines with call sites, recorded file history and source. '
        'Code is read from disk when the dossier is built and never stored in the model.</p>',
    ]
    for sym in picks:
        insight = _insight_for(insights, sym["id"])
        micro = str(insight.get("micro") or "")
        why = str(insight.get("why") or "")
        flags = " ".join(_flag_tag(f) for f in (sym.get("flags") or []))
        callers = [f"{_display(symbols[c])} ({_loc(symbols[c])})"
                   for c in sym.get("callers", []) if c in symbols]
        callees = [f"{_display(symbols[c])} ({_loc(symbols[c])})"
                   for c in sym.get("calls", []) if c in symbols]
        git = files_git.get(sym["file_path"]) or {}
        body: list[str] = [
            '<div class="head">'
            f'<span class="name">{esc(_display(sym))}</span>'
            f'<span class="where">{esc(sym.get("kind", ""))} - {esc(_loc(sym))} '
            f'(lines {_fmt_int(sym.get("line_start", 0))}-{_fmt_int(sym.get("line_end", 0))})</span></div>',
            '<p class="small">'
            f'complexity {_fmt_int(sym.get("complexity", 1))} | '
            f'{_fmt_int(len(sym.get("callers") or []))} caller(s) | '
            f'{_fmt_int(len(sym.get("calls") or []))} resolved call(s) | '
            f'{esc(sym.get("language", ""))} | {esc(sym.get("source", "ast"))}</p>',
        ]
        if flags:
            body.append(f"<p>{flags}</p>")
        if micro or why:
            body.append(
                '<div class="callout">'
                f'<p><span class="mono">{esc(micro)}</span>' + (f" {esc(why)}" if why else "") + '</p>'
                f'<span class="src">{esc(_source_label(insight))}</span></div>'
            )
        if git.get("last_commit"):
            body.append(
                '<p class="small">Last recorded change: '
                f'<span class="mono">{esc(git.get("last_commit", ""))}</span> '
                f'({esc(git.get("last_date", ""))}) - {esc(git.get("last_subject", ""))}. '
                f'{_fmt_int(git.get("commits", 0))} commit(s) touched this file in the scanned window.</p>'
            )
        if callers:
            body.append('<h4>Call sites</h4><ul>'
                        + "".join(f'<li class="mono small">{esc(c)}</li>' for c in callers[:12]) + '</ul>')
        if callees:
            body.append('<h4>Resolved calls</h4><ul>'
                        + "".join(f'<li class="mono small">{esc(c)}</li>' for c in callees[:12]) + '</ul>')
        source = read_symbol_source(root, sym, pad=0, max_lines=max_lines)
        if source:
            body.append(f"<pre>{esc(source)}</pre>")
        parts.append('<div class="symbol-card">' + "".join(body) + "</div>")
    return "".join(parts)


def section_appendix(model: dict[str, Any], limit: int) -> str:
    files = model.get("files", []) or []
    if limit <= 0 or not files:
        return ""
    ordered = sorted(files, key=lambda f: (-int(f.get("symbols") or 0), f.get("path", "")))[:limit]
    rows = []
    for f in ordered:
        git = f.get("git") or {}
        if f.get("is_test"):
            kind = '<span class="tag warn">test</span>'
        elif f.get("is_production"):
            kind = '<span class="tag ok">prod</span>'
        else:
            kind = ""
        rows.append(_row([
            f'<span class="mono small">{esc(f.get("path", ""))}</span>',
            esc(f.get("language", "")),
            _fmt_int(f.get("loc", 0)),
            _fmt_int(f.get("symbols", 0)),
            kind,
            f'<span class="mono small">{esc(git.get("last_commit", ""))}</span>',
            esc(git.get("last_date", "")),
            _fmt_int(git.get("commits", 0)),
            f'<span class="small">{esc((git.get("last_subject") or "")[:70])}</span>',
        ]))
    return (_h2(f"Appendix - files by symbol count ({len(ordered)} shown)", 'Full inventory of files by symbol count, including what the caps left out.')
            + _table(["Path", "Language", "LOC", "Symbols", "Layer", "Last commit", "Date",
                      "Commits", "Subject"], rows))


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def build_dossier(
    model: dict[str, Any],
    level: int = 2,
    insights: Any = None,
    narratives: Optional[dict[str, Any]] = None,
    root: Any = None,
    delta: Optional[dict[str, Any]] = None,
) -> str:
    """Assemble the complete HTML dossier: the single source for preview and PDF."""
    level = 3 if int(level) >= 3 else (1 if int(level) <= 1 else 2)
    caps = CAPS[level]
    narratives = dict(narratives or {})

    if not narratives.get("exec_summary") or not narratives.get("story") or not narratives.get("roadmap"):
        try:
            from insights import deterministic_exec_summary, deterministic_roadmap, deterministic_story
            if not narratives.get("exec_summary"):
                narratives["exec_summary"] = deterministic_exec_summary(model)
                narratives.setdefault("source", "derived")
            if not narratives.get("story"):
                narratives["story"] = deterministic_story(model)
                narratives.setdefault("story_source", "derived")
            if not narratives.get("roadmap"):
                narratives["roadmap"] = deterministic_roadmap(model)
                narratives.setdefault("roadmap_source", "derived")
        except Exception:
            pass

    repo_root = root or (model.get("repo", {}) or {}).get("root")
    _TOC.clear()
    body: list[Optional[str]] = [
        section_cover(model, level),
        section_metrics(model, level),
        section_exec_summary(narratives),
        section_story(narratives),
        section_context(model),
        section_entry_points(model, caps.get("entry_points", 0)),
        section_module_profiles(model, caps.get("modules", 0), caps.get("module_routines", 0)),
        section_reading_order(model, hubs=5 if level == 1 else 7),
        section_confidence(model, insights),
        section_delta(delta, level),
    ]
    if level >= 2:
        body += [
            section_module_graph(model),
            section_module_edges(model, caps.get("edges", 0)),
            section_flows(model, caps["flows"]),
            section_routes(model, caps.get("routes", 0)),
            section_models(model, caps.get("models", 0)),
            section_model_details(model, caps.get("models", 0)),
            section_services(model, caps.get("services", 0)),
            section_clusters(model, level),
        ]
    body += [
        section_risks(model, caps["risks"]),
        section_roadmap(narratives, caps.get("roadmap", 8)),
        section_key_functions(model, insights, caps["symbol_rows"], show_why=level >= 2),
        section_file_inventory(model, caps.get("files", 0)) if level >= 2 else "",
    ]
    if level >= 3:
        body += [
            _page_break(),
            section_deep_symbols(model, insights, repo_root, caps["deep_symbols"]),
            _page_break(),
            section_appendix(model, caps["appendix"]),
        ]
    fingerprint = ((model.get("repo", {}) or {}).get("fingerprint") or {}).get("hash", "")
    body.append(
        '<div class="footer-note">'
        f'Architecture Storyteller - {esc(LEVEL_TITLES[level])} (L{level}) - '
        f'model {esc(model.get("schema", ""))} - generated {esc(model.get("generated_at", ""))} - '
        f'fingerprint {esc(fingerprint)}. A higher level only adds sections and raises display caps.'
        '</div>'
    )
    # Generated last, so every heading in this level has registered itself.
    body.insert(1, section_contents())
    title = f'{(model.get("repo", {}) or {}).get("name", "Repository")} - {LEVEL_TITLES[level]}'
    return _doc_shell(title, "\n".join(part for part in body if part))


def _main(argv: list[str]) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Build the HTML architecture dossier.")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("-o", "--output", default="")
    parser.add_argument("-l", "--level", type=int, default=2, choices=(1, 2, 3))
    parser.add_argument("--languages", default="python,typescript,javascript,go")
    parser.add_argument("--bob-command", default="")
    parser.add_argument("--llm-url", default="")
    parser.add_argument("--llm-model", default="")
    parser.add_argument("--force", action="store_true", help="regenerate every insight")
    args = parser.parse_args(argv)

    from cache_store import StorytellerCache
    from insights import InsightService
    from model_builder import build_model, manifest_from_model

    root = Path(args.repo).resolve()
    languages = [item.strip() for item in args.languages.split(",") if item.strip()]
    model = build_model(root, languages)
    cache = StorytellerCache(root)
    delta = cache.compute_delta(manifest_from_model(model))
    service = InsightService(root, cache)
    report = service.ensure(
        model,
        bob_command=args.bob_command or None,
        llm_url=args.llm_url or None,
        llm_model=args.llm_model or None,
        force=args.force,
    )
    narratives = service.ensure_narratives(
        model,
        bob_command=args.bob_command or None,
        llm_url=args.llm_url or None,
        llm_model=args.llm_model or None,
    )
    document = build_dossier(model, args.level, service, narratives, root=root, delta=delta)
    out = Path(args.output) if args.output else root / "output" / f"dossier-L{args.level}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(document, encoding="utf-8")
    print(json.dumps({
        "output": str(out),
        "level": args.level,
        "provider": report.get("provider"),
        "generated": report.get("generated"),
        "removed": report.get("removed"),
        "delta": report.get("delta"),
        "sources": report.get("sources"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))


# ---------------------------------------------------------------------------
# Navigation depth: entry points, module profiles, files, reading order
# ---------------------------------------------------------------------------

def section_entry_points(model: dict[str, Any], limit: int) -> str:
    entries = model.get("entry_points") or []
    if limit <= 0 or not entries:
        return ""
    symbols = _symbol_index(model)
    flow_by_entry: dict[str, dict[str, Any]] = {}
    for flow in (model.get("flows") or []):
        flow_by_entry.setdefault(flow.get("entry_id") or flow.get("entry"), flow)
    rows = []
    for entry in entries[:limit]:
        symbol_id = entry.get("symbol_id", "")
        sym = symbols.get(symbol_id)
        flow = flow_by_entry.get(symbol_id) or flow_by_entry.get(entry.get("name"))
        reached = " -> ".join(str(n.get("name", "")) for n in (flow or {}).get("chain", [])[1:6])
        location = f'{entry.get("file_path", "")}:{entry.get("line") or (sym or {}).get("line_start", 0)}'
        rows.append(_row([
            f'<span class="mono">{esc(entry.get("name", ""))}</span>',
            f'<span class="tag">{esc(entry.get("kind", entry.get("type", "entry")))}</span>',
            f'<span class="mono small">{esc(location)}</span>',
            _fmt_int(len((sym or {}).get("calls") or [])) if sym else "n/a",
            f'<span class="mono small">{esc(reached)}</span>' if reached else '<span class="small">-</span>',
        ]))
    return (_h2(f"Entry points ({len(entries)} detected)", 'Where execution can start, and what each entry point reaches first.')
            + _table(["Entry", "Kind", "Location", "Resolved calls", "Reaches"], rows))


def section_module_profiles(model: dict[str, Any], limit: int, routines_per_module: int) -> str:
    nodes = [n for n in ((model.get("module_graph") or {}).get("nodes") or []) if n.get("id")]
    if limit <= 0 or not nodes:
        return ""
    shown = nodes[:limit]
    symbols = _symbol_index(model)
    module_of = {f.get("path"): f.get("module", "root") for f in (model.get("files") or [])}
    rank = {entry["id"]: index for index, entry in enumerate(model.get("pivotal") or [])}
    by_module: dict[str, list[dict[str, Any]]] = {}
    for sym in symbols.values():
        by_module.setdefault(module_of.get(sym["file_path"], "root"), []).append(sym)
    entries_by_module: dict[str, list[dict[str, Any]]] = {}
    for entry in (model.get("entry_points") or []):
        entries_by_module.setdefault(module_of.get(entry.get("file_path", ""), "root"), []).append(entry)

    parts = [_h2(f"Module profiles ({len(shown)} of {_fmt_int(len(nodes))} modules)", 'One profile per module: its size, the routines that matter, and how it is wired.')]
    for node in shown:
        module_id = node["id"]
        module_symbols = by_module.get(module_id, [])
        routines = [s for s in module_symbols if s.get("kind") in ("function", "method")]
        ranked = sorted(routines, key=lambda s: (rank.get(s["id"], 10 ** 6),
                                                 -int(s.get("complexity") or 0)))[:routines_per_module]
        tags = []
        if node.get("has_cycle"):
            tags.append('<span class="tag danger">dependency cycle</span>')
        if node.get("dynamic"):
            tags.append(f'<span class="tag warn">{_fmt_int(node["dynamic"])} dynamic</span>')
        body = [
            f'<h3>{esc(node.get("label", module_id))} {" ".join(tags)}</h3>',
            '<p class="small">'
            f'{_fmt_int(node.get("files", 0))} file(s) | {_fmt_int(node.get("symbols", 0))} symbol(s) | '
            f'{_fmt_int(len(routines))} routine(s) | {esc(", ".join(node.get("languages") or []))}</p>',
        ]
        module_entries = entries_by_module.get(module_id) or []
        if module_entries:
            names = ", ".join(f'<span class="mono">{esc(e.get("name", ""))}</span>' for e in module_entries[:6])
            body.append(f'<p class="small">Entry points: {names}</p>')
        if routines_per_module and ranked:
            rows = []
            for sym in ranked:
                rows.append(_row([
                    f'<span class="mono">{esc(_display(sym))}</span>',
                    f'<span class="mono small">{esc(_loc(sym))}</span>',
                    _fmt_int(len(sym.get("callers") or [])),
                    _fmt_int(sym.get("complexity", 0)),
                    " ".join(_flag_tag(f) for f in (sym.get("flags") or [])[:2]),
                ]))
            body.append(_table(["Routine", "Location", "Callers", "Complexity", "Flags"], rows))
        parts.append('<div class="module-block">' + "".join(body) + "</div>")
    return "".join(parts)


def section_reading_order(model: dict[str, Any], hubs: int = 5) -> str:
    symbols = _symbol_index(model)
    steps: list[tuple[str, str]] = []
    for entry in (model.get("entry_points") or [])[:3]:
        steps.append((f'Start at the entry point {entry.get("name", "")}',
                      f'{entry.get("kind", entry.get("type", "entry"))} in {entry.get("file_path", "")}'))
    taken = 0
    for entry in (model.get("pivotal") or []):
        sym = symbols.get(entry["id"])
        if not sym or sym.get("is_test"):
            continue
        steps.append((f'Read {_display(sym)}',
                      f"{_fmt_int(entry.get('fan_in', 0))} caller(s), "
                      f"{_fmt_int(entry.get('cross_file_callers', 0))} from other files, "
                      f"complexity {_fmt_int(entry.get('complexity', 0))} - {_loc(sym)}"))
        taken += 1
        if taken >= hubs:
            break
    models_ = (model.get("layers") or {}).get("models") or []
    if models_:
        names = ", ".join(str(m.get("name", "")) for m in models_[:4])
        steps.append(("Understand the data layer",
                      f"{_fmt_int(len(models_))} model(s): {names}"))
    if (model.get("clusters") or {}).get("counts", {}).get("cyclic"):
        steps.append(("Treat the cycle groups as hazardous",
                      "mutually recursive symbols are listed in the risk register"))
    if not steps:
        return ""
    items = "".join(f'<li>{esc(title)}<br><span class="small">{esc(detail)}</span></li>'
                    for title, detail in steps)
    return (_h2("Suggested reading order", 'A deliberate order for a new reader, from orientation down to the deepest logic.')
            + '<ol class="reading-order">' + items + "</ol>")


def section_file_inventory(model: dict[str, Any], limit: int) -> str:
    files = model.get("files") or []
    if limit <= 0 or not files:
        return ""
    ordered = sorted(files, key=lambda f: (-int(f.get("symbols") or 0), f.get("path", "")))[:limit]
    rows = []
    for f in ordered:
        if f.get("is_test"):
            layer = '<span class="tag warn">test</span>'
        elif f.get("is_production"):
            layer = '<span class="tag ok">prod</span>'
        else:
            layer = '<span class="tag">support</span>'
        rows.append(_row([
            f'<span class="mono small">{esc(f.get("path", ""))}</span>',
            f'<span class="mono small">{esc(f.get("module", ""))}</span>',
            esc(f.get("language", "")),
            _fmt_int(f.get("loc", 0)),
            _fmt_int(f.get("symbols", 0)),
            layer,
        ]))
    return (_h2(f"Source inventory ({len(ordered)} of {_fmt_int(len(files))} files)", 'Every scanned file with its language, symbol count and last recorded change.')
            + _table(["Path", "Module", "Language", "LOC", "Symbols", "Layer"], rows))


def section_model_details(model: dict[str, Any], limit: int) -> str:
    models_ = ((model.get("layers") or {}).get("models") or [])[:limit]
    if not models_:
        return ""
    parts = [_h2("Data model detail", 'Field-level detail for each detected model.')]
    for m in models_:
        parts.append(f'<h3>{esc(m.get("name", ""))} <span class="small">'
                     f'({esc(m.get("table_name", ""))}, {esc(m.get("orm_type", ""))})</span></h3>')
        rows = []
        for field in (m.get("fields") or []):
            marks = []
            if field.get("is_primary_key"):
                marks.append('<span class="tag ok">PK</span>')
            if field.get("is_foreign_key"):
                marks.append('<span class="tag warn">FK</span>')
            rows.append(_row([
                f'<span class="mono">{esc(field.get("name", ""))}</span>',
                esc(field.get("field_type", "")),
                " ".join(marks) or "",
                f'<span class="mono small">{esc(field.get("references") or "")}</span>',
            ]))
        parts.append(_table(["Field", "Type", "Key", "References"], rows))
        relationships = m.get("relationships") or []
        if relationships:
            parts.append('<p class="small">Relationships: '
                         + esc(", ".join(str(r) for r in relationships)) + "</p>")
        parts.append(f'<p class="small mono">{esc(m.get("file_path", ""))}:'
                     f'{_fmt_int(m.get("line_start", 0))}</p>')
    return "".join(parts)


# ---------------------------------------------------------------------------
# Confidence / provenance
# ---------------------------------------------------------------------------

def _insight_stats(insights: Any) -> dict[str, int]:
    if insights is None:
        return {}
    cache = getattr(insights, "cache", None)
    if cache is not None and hasattr(cache, "source_counts"):
        try:
            return cache.source_counts()
        except Exception:
            return {}
    if isinstance(insights, dict):
        counts: dict[str, int] = {}
        for entry in insights.values():
            source = str((entry or {}).get("source") or "unknown")
            counts[source] = counts.get(source, 0) + 1
        return counts
    return {}


def section_confidence(model: dict[str, Any], insights: Any) -> str:
    stats = model.get("stats", {}) or {}
    resolved = int(stats.get("resolved_call_edges") or 0)
    unresolved = int(stats.get("unresolved_call_names") or 0)
    total = resolved + unresolved
    rate = pct(resolved, total) if total else "n/a"
    files = model.get("files") or []
    with_history = sum(1 for f in files if (f.get("git") or {}).get("last_commit"))
    rows = [
        _row(["Static analysis engine", f'<span class="mono">{esc((model.get("meta") or {}).get("engine", "n/a"))}</span>',
              "Python AST for Python; built-in lexical extractors for TypeScript/JavaScript/Go."]),
        _row(["Call resolution", f'<span class="mono">{rate} resolved ({_fmt_int(resolved)} of {_fmt_int(total)})</span>',
              "Unresolved names are dynamic or external calls; they are excluded from cycles and flows."]),
        _row(["File history", f'<span class="mono">{_fmt_int(with_history)} of {_fmt_int(len(files))} files</span>',
              "Last-touch metadata from one bounded git log pass; no per-line blame."]),
        _row(["Dependency layers", f'<span class="mono">regex heuristics</span>',
              "Route, model and service detection is labelled at each table; it is not parsed structure."]),
    ]
    sources = _insight_stats(insights)
    if sources:
        detail = ", ".join(f"{_fmt_int(count)} {esc(name)}" for name, count in sorted(sources.items()))
        rows.append(_row([f"Symbol summaries ({_fmt_int(sum(sources.values()))})",
                          f'<span class="mono">{detail}</span>',
                          "Labelled per entry: bob / llm text is AI-written, fallback text is derived "
                          "from names, docstrings and the call graph."]))
    return (_h2("Model confidence and provenance", 'How complete this model is, how much of the call graph resolved, and where each fact came from.')
            + _table(["Property", "Value", "How to read it"], rows))


def section_module_edges(model: dict[str, Any], limit: int) -> str:
    edges = (model.get("module_graph") or {}).get("edges") or []
    if limit <= 0 or not edges:
        return ""
    rows = []
    for edge in edges[:limit]:
        label = "calls" if edge.get("type") == "calls" else "imports"
        rows.append(_row([
            f'<span class="mono">{esc(edge.get("from", ""))}</span>',
            f'<span class="mono">{esc(edge.get("to", ""))}</span>',
            f'<span class="tag">{esc(label)}</span>',
            _fmt_int(edge.get("weight", 0)),
        ]))
    return (_h2(f"Module dependencies, weighted ({len(rows)} of {_fmt_int(len(edges))} edges)")
            + _table(["From", "To", "Type", "Weight"], rows))
