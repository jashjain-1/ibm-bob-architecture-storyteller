#!/usr/bin/env python3
"""
cli.py
~~~~~~
Command line front door for Architecture Storyteller 2.0.

Every subcommand drives the same `StorytellerEngine`: one model, one cache, one
dossier builder. Nothing here re-implements analysis, so the CLI, the PDF and
the interactive map can never disagree.

    cli.py index     [--repo .] [--force] [--force-insights] [--json]
    cli.py dossier   [--repo .] [--level 2] [--output path.html] [--pdf]
    cli.py mindmap   [--repo .] [--symbol NAME] [--json]
    cli.py context   SYMBOL [--repo .] [--lines 40] [--json]
    cli.py usages    SYMBOL [--repo .] [--json]
    cli.py delta     [--repo .]
    cli.py model     [--repo .] [--full] [--output path.json]
    cli.py serve     [--repo .] [--port 8003] [--index] [--watch-parent]

The previous CLI is kept as `cli_legacy.py` for reference only; it is not wired
into anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from engine_server import StorytellerEngine, SymbolLookupError, run_forever  # noqa: E402


def _engine(args: argparse.Namespace) -> StorytellerEngine:
    languages = None
    if getattr(args, "languages", ""):
        languages = [item.strip() for item in args.languages.split(",") if item.strip()]
    return StorytellerEngine(
        args.repo,
        cache_dir=getattr(args, "cache_dir", None) or None,
        languages=languages,
    )


def _print(payload: object, as_json: bool, text: str = "") -> None:
    if as_json or not text:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(text)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_index(args: argparse.Namespace) -> int:
    engine = _engine(args)
    report = engine.index(
        force=args.force,
        force_insights=args.force_insights,
        bob_command=args.bob_command or None,
        llm_url=args.llm_url or None,
        llm_model=args.llm_model or None,
    )
    text = (
        f"Indexed {report['stats']['files']} file(s), {report['stats']['symbols']} symbol(s).\n"
        f"Delta: +{report['delta']['added']} added, ~{report['delta']['changed']} changed, "
        f"-{report['delta']['removed']} removed, {report['delta']['unchanged']} unchanged.\n"
        f"Insights generated: {report['generated']} ({report['provider']}), "
        f"cached total {report['cached_total']}."
    )
    _print(report, args.json, text)
    return 0


def cmd_dossier(args: argparse.Namespace) -> int:
    engine = _engine(args)
    bob = dict(
        bob_command=args.bob_command or None,
        llm_url=args.llm_url or None,
        llm_model=args.llm_model or None,
    )
    if args.pdf:
        output = args.output if (args.output or "").endswith(".pdf") else None
        result = engine.render_pdf(args.level, output, **bob)
        _print(result, True, f"Wrote {result['pdf']} ({result['bytes']:,} bytes)")
        return 0

    document = engine.dossier_html(args.level, **bob)
    output = args.output or ""
    if output and not output.endswith(".html"):
        output = str(Path(output) / f"dossier-L{args.level}.html")
    path = Path(output) if output else Path(args.repo).resolve() / "output" / f"dossier-L{args.level}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")
    result = {"level": args.level, "output": str(path), "bytes": len(document)}
    _print(result, True, f"Wrote {path} ({len(document):,} bytes). "
                         f"Render it with: node scripts/render_pdf.mjs --input {path}")
    return 0


def cmd_mindmap(args: argparse.Namespace) -> int:
    engine = _engine(args)
    payload = engine.tree()
    if args.symbol:
        context = engine.context(args.symbol, lines=0)
        payload = {"tree": payload, "focus": context["symbol"],
                   "callers": context["callers"], "calls": context["calls"]}
    stats = payload.get("stats", {}) if isinstance(payload, dict) else {}
    text = (f"{stats.get('files', 0)} file(s), {stats.get('symbols', 0)} symbol(s), "
            f"{stats.get('modules', 0)} module(s). "
            f"Pass --json for the tree payload the webview consumes.")
    _print(payload, args.json, text)
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    engine = _engine(args)
    context = engine.context(args.symbol, lines=args.lines)
    symbol = context["symbol"]
    insight = context.get("insight") or {}
    lines = [
        f"{symbol['qualified']} - {symbol['kind']} at {symbol['file']}:{symbol['line']}",
        f"  complexity {symbol.get('complexity')} | flags {', '.join(symbol.get('flags') or []) or 'none'}",
    ]
    if symbol.get("doc"):
        lines.append(f"  doc: {symbol['doc'].strip().splitlines()[0]}")
    if insight.get("micro"):
        lines.append(f"  summary: {insight['micro']} [{insight.get('source', 'auto')}]")
    if insight.get("why"):
        lines.append(f"  why: {insight['why']}")
    if context["callers"]:
        lines.append(f"  callers ({len(context['callers'])}): " +
                     ", ".join(f"{c['qualified']} ({c['file']}:{c['line']})" for c in context["callers"][:8]))
    if context["calls"]:
        lines.append(f"  calls ({len(context['calls'])}): " +
                     ", ".join(c["qualified"] for c in context["calls"][:8]))
    if context.get("flows"):
        for flow in context["flows"]:
            lines.append(f"  flow: {' -> '.join(flow['chain'])}")
    if args.lines and context.get("source"):
        lines.append("")
        lines.append(context["source"])
    _print(context, args.json, "\n".join(lines))
    return 0


def cmd_usages(args: argparse.Namespace) -> int:
    engine = _engine(args)
    usages = engine.usages(args.symbol)
    symbol = usages["symbol"]
    lines = [f"{symbol['qualified']} is called from {usages['call_site_count']} resolved site(s):"]
    for caller in usages["callers"]:
        raw = ", ".join(caller.get("raw_calls") or [])
        lines.append(f"  {caller['file']}:{caller['line']}  {caller['qualified']}"
                     + (f"   [{raw}]" if raw else ""))
    _print(usages, args.json, "\n".join(lines))
    return 0


def cmd_delta(args: argparse.Namespace) -> int:
    engine = _engine(args)
    delta = engine.delta()
    counts = delta["counts"]
    text = (f"Added {counts['added']}, changed {counts['changed']}, "
            f"removed {counts['removed']}, unchanged {counts['unchanged']}"
            + (" (first index)" if delta["first_run"] else ""))
    _print(delta, args.json, text)
    return 0


def cmd_model(args: argparse.Namespace) -> int:
    engine = _engine(args)
    payload = engine.model(full=args.full)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        _print({"output": str(path), "bytes": path.stat().st_size}, True, f"Wrote {path}")
        return 0
    _print(payload, True)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    engine = _engine(args)
    run_forever(engine, port=args.port, host=args.host, index_on_start=args.index,
                watch_parent=args.watch_parent, parent_pid=args.parent_pid or None)
    return 0


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=".", help="repository root (default: .)")
    parser.add_argument("--languages", default="python,typescript,javascript,go",
                        help="comma-separated languages to scan")
    parser.add_argument("--cache-dir", default="", help="override the .storyteller cache directory")
    parser.add_argument("--json", action="store_true", help="emit JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cli.py", description="Architecture Storyteller 2.0")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="build the model, refresh insights and report the delta")
    _common(p_index)
    p_index.add_argument("--force", action="store_true", help="rebuild the model even if unchanged")
    p_index.add_argument("--force-insights", action="store_true", help="regenerate every insight")
    p_index.add_argument("--bob-command", default="", help="IBM Bob / agent command for live insights")
    p_index.add_argument("--llm-url", default="", help="Ollama-compatible endpoint")
    p_index.add_argument("--llm-model", default="", help="model name for the local LLM")
    p_index.set_defaults(func=cmd_index)

    p_dossier = sub.add_parser("dossier", help="build the HTML dossier, optionally render the PDF")
    _common(p_dossier)
    p_dossier.add_argument("--level", "-l", type=int, default=2, choices=(1, 2, 3))
    p_dossier.add_argument("--output", "-o", default="")
    p_dossier.add_argument("--pdf", action="store_true", help="render the PDF with the installed Chromium")
    p_dossier.add_argument("--bob-command", default="",
                           help="IBM Bob / agent command that writes the dossier prose")
    p_dossier.add_argument("--llm-url", default="", help="Ollama-compatible endpoint for the prose")
    p_dossier.add_argument("--llm-model", default="", help="model name for the local LLM")
    p_dossier.set_defaults(func=cmd_dossier)

    p_map = sub.add_parser("mindmap", help="emit the tree payload consumed by the interactive map")
    _common(p_map)
    p_map.add_argument("--symbol", default=None, help="focus a symbol")
    p_map.set_defaults(func=cmd_mindmap)

    p_context = sub.add_parser("context", help="symbol context: callers, callees, insight, source")
    p_context.add_argument("symbol")
    _common(p_context)
    p_context.add_argument("--lines", type=int, default=40, help="source lines to include (0 for none)")
    p_context.set_defaults(func=cmd_context)

    p_usages = sub.add_parser("usages", help="every resolved call site of a symbol")
    p_usages.add_argument("symbol")
    _common(p_usages)
    p_usages.set_defaults(func=cmd_usages)

    p_delta = sub.add_parser("delta", help="cache delta since the last index")
    _common(p_delta)
    p_delta.set_defaults(func=cmd_delta)

    p_model = sub.add_parser("model", help="print the model (compact by default)")
    _common(p_model)
    p_model.add_argument("--full", action="store_true", help="include every symbol and edge")
    p_model.add_argument("--output", "-o", default="")
    p_model.set_defaults(func=cmd_model)

    p_serve = sub.add_parser("serve", help="run the long-lived HTTP engine for the IDE")
    _common(p_serve)
    p_serve.add_argument("--port", type=int, default=8003)
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--index", action="store_true", help="index once before serving")
    p_serve.add_argument("--watch-parent", action="store_true",
                         help="exit when the process that spawned the engine exits")
    p_serve.add_argument("--parent-pid", type=int, default=0,
                         help="explicit pid to watch (implies --watch-parent)")
    p_serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SymbolLookupError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 3
    except FileNotFoundError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
