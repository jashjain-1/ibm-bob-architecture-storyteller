"""
cli.py
~~~~~~
Unified Command-Line Interface and Local Agent Service for:
  - /mindmap  -> Visual Architecture Map & 5-minute Storyboard
  - /context  -> Cross-Referenced Symbol Archival Backstory & Popups
  - /pdf      -> Publication Dossier Generation
  - serve     -> Local JSON-RPC / REST API for VS Code Extension & IBM Bob MCP
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from synthesizer import StorySynthesizer


def main():
    parser = argparse.ArgumentParser(description="The Architecture Storyteller & Archival Context Engine")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: mindmap
    p_mindmap = subparsers.add_parser("mindmap", help="Generate Mermaid flowchart and plain-English storyboard")
    p_mindmap.add_argument("--repo", default=".", help="Root path of repository")
    p_mindmap.add_argument("--depth", type=int, default=1, choices=[1, 2, 3], help="Technical Depth (1=High, 2=Flow, 3=Archival Forensic)")
    p_mindmap.add_argument("--layers", default="frontend,backend,db,git", help="Comma-separated layers")
    p_mindmap.add_argument("--symbol", default=None, help="Target specific function/symbol to focus on")
    p_mindmap.add_argument("--json", action="store_true", help="Output raw JSON instead of markdown")

    # Command: context
    p_context = subparsers.add_parser("context", help="Archival context and cross-reference analysis for a symbol")
    p_context.add_argument("symbol", help="Target function or symbol name")
    p_context.add_argument("--repo", default=".", help="Root path of repository")
    p_context.add_argument("--depth", type=int, default=3, choices=[1, 2, 3], help="Technical Depth")
    p_context.add_argument("--layers", default="git,backend", help="Comma-separated layers")
    p_context.add_argument("--json", action="store_true", help="Output raw JSON")

    # Command: pdf
    p_pdf = subparsers.add_parser("pdf", help="Export architecture dossier to PDF")
    p_pdf.add_argument("--repo", default=".", help="Root path of repository")
    p_pdf.add_argument("--output", default="output/architecture_dossier.pdf", help="Output PDF file path")
    p_pdf.add_argument("--output-dir", default=None, help="Output directory path")
    p_pdf.add_argument("--layers", default="frontend,backend,db,git", help="Comma-separated layers")
    p_pdf.add_argument("--depth", type=int, default=2, help="Technical Depth")

    # Command: serve
    p_serve = subparsers.add_parser("serve", help="Run local HTTP server for VS Code extension and IBM Bob MCP")
    p_serve.add_argument("--port", type=int, default=8003, help="Port to listen on")
    p_serve.add_argument("--repo", default=".", help="Root path of repository")

    args = parser.parse_args()

    if not args.command or args.command == "mindmap":
        repo = getattr(args, "repo", ".")
        depth = getattr(args, "depth", 1)
        layers = [l.strip() for l in getattr(args, "layers", "frontend,backend,db,git").split(",") if l.strip()]
        symbol = getattr(args, "symbol", None)
        as_json = getattr(args, "json", False)

        synth = StorySynthesizer(repo)
        result = synth.synthesize(technical_depth=depth, active_layers=layers, target_symbol=symbol)

        if as_json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            _render_markdown_mindmap(result)

    elif args.command == "context":
        layers = [l.strip() for l in getattr(args, "layers", "git,backend").split(",") if l.strip()]
        synth = StorySynthesizer(args.repo)
        result = synth.synthesize(technical_depth=args.depth, active_layers=layers, target_symbol=args.symbol)

        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            _render_markdown_context(result, args.symbol)

    elif args.command == "pdf":
        out_target = getattr(args, "output", "output/architecture_dossier.pdf")
        out_dir = getattr(args, "output_dir", None)
        if out_dir:
            out_target = str(Path(out_dir) / "architecture_dossier.pdf")
        layers = [l.strip() for l in getattr(args, "layers", "frontend,backend,db,git").split(",") if l.strip()]
        _export_pdf(args.repo, out_target, args.depth, layers)

    elif args.command == "serve":
        _run_server(args.repo, args.port)


def _render_markdown_mindmap(res: Any):
    print(f"# 🗺️ Architecture Storyboard: {res.project_name}")
    print(f"\n> **Executive Summary:** {res.executive_summary}\n")
    print(f"**Depth Level:** {res.technical_depth} | **Active Layers:** {', '.join(res.active_layers)}\n")
    print("## 📊 Architecture Flowchart\n")
    print("```mermaid")
    print(res.mermaid_diagram)
    print("```\n")
    print("## 📖 5-Minute Plain-English Storyboard\n")
    for chapter in res.five_minute_story:
        print(f"### {chapter['title']}")
        print(f"{chapter['content']}\n")


def _render_markdown_context(res: Any, symbol_name: str):
    print(f"# 🔍 Archival Context: `{symbol_name}`\n")
    if not res.context_popups:
        print(f"No definition or call instances found for `{symbol_name}`.")
        return

    p = res.context_popups[0]
    backstory = p.get("backstory", {})

    print(f"**Defined in:** `{p['definition_file']}:{p['definition_line']}`")
    print(f"**Total Call-Sites Cross-Referenced:** {p['call_sites_count']}")
    print(f"**Cyclomatic Complexity:** {p['complexity']}")
    if p["unusual_flags"]:
        print(f"**Logic Flags:** {', '.join(p['unusual_flags'])}")

    print(f"\n### 💬 Team Backstory ({backstory.get('data_source_tier', 'Historical')})")
    print(f"**PR #{backstory.get('pr_number', 'N/A')}:** {backstory.get('pr_title', 'Feature implementation')}")
    print(f"**Author:** @{backstory.get('author', 'teammate')}")
    print(f"**Why this was written:**\n> {backstory.get('why_it_was_written')}\n")

    print("### 📍 Cross-Referenced Call Sites")
    for idx, cs in enumerate(p["call_sites"][:10], 1):
        print(f"{idx}. `{cs['caller_file']}:{cs['line_number']}` (inside `{cs['enclosing_symbol']}`)")
        print(f"   ```\n   {cs['snippet']}\n   ```")


def _export_pdf(repo: str, output_path: str, depth: int, layers: list | None = None):
    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    synth = StorySynthesizer(repo)
    res = synth.synthesize(technical_depth=depth, active_layers=layers or ["frontend", "backend", "db", "git"])
    
    # Query AI for extra insights for HTML
    ai_cluster_html = "AI Module Unavailable."
    ai_roadmap_html = "AI Module Unavailable."
    try:
        _SCRIPTS = _HERE.parent.parent / "scripts"
        if str(_SCRIPTS) not in sys.path:
            sys.path.insert(0, str(_SCRIPTS))
        from bob_bridge import invoke_bob
        c_res = invoke_bob(f"Cluster B & C Deep Dive for {res.project_name}")
        r_res = invoke_bob(f"Modernization Roadmap for {res.project_name}")
        if c_res: ai_cluster_html = c_res.stdout.replace('\n', '<br>')
        if r_res: ai_roadmap_html = r_res.stdout.replace('\n', '<br>')
    except Exception:
        pass

    # Generate HTML report that can be opened or rendered to PDF via headless browser/VS Code
    # Enhanced enterprise HTML dossier template
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Enterprise Architecture Dossier – {res.project_name}</title>
    <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
    <script>
        document.addEventListener("DOMContentLoaded", function() {{
            mermaid.initialize({{
                startOnLoad: true,
                theme: 'dark',
                flowchart: {{ useMaxWidth: true, htmlLabels: true, curve: 'basis' }}
            }});
        }});
    </script>
    <style>
        :root {{
            --bg-primary: #0b0f19;
            --bg-surface: #111827;
            --bg-card: #1f2937;
            --border-color: #374151;
            --text-main: #f3f4f6;
            --text-muted: #9ca3af;
            --accent-blue: #3b82f6;
            --accent-cyan: #06b6d4;
            --accent-emerald: #10b981;
            --accent-rose: #f43f5e;
            --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            --font-mono: "JetBrains Mono", "Cascadia Code", Consolas, monospace;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: var(--font-family);
            background: var(--bg-primary);
            color: var(--text-main);
            line-height: 1.6;
            padding: 40px 24px;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        header {{
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 24px;
            margin-bottom: 32px;
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            flex-wrap: wrap;
            gap: 16px;
        }}
        .header-left h1 {{
            font-size: 28px;
            font-weight: 700;
            color: var(--text-main);
            letter-spacing: -0.5px;
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .header-left p {{ color: var(--text-muted); font-size: 14px; margin-top: 6px; }}
        .classification-badge {{
            display: inline-block;
            padding: 6px 14px;
            border-radius: 9999px;
            background: rgba(59, 130, 246, 0.15);
            border: 1px solid var(--accent-blue);
            color: var(--accent-blue);
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 16px;
            margin-bottom: 32px;
        }}
        .stat-card {{
            background: var(--bg-surface);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 20px;
            display: flex;
            flex-direction: column;
            position: relative;
            overflow: hidden;
        }}
        .stat-card::before {{
            content: "";
            position: absolute;
            top: 0; left: 0; right: 0; height: 3px;
            background: var(--accent-blue);
        }}
        .stat-card.cyan::before {{ background: var(--accent-cyan); }}
        .stat-card.emerald::before {{ background: var(--accent-emerald); }}
        .stat-card.rose::before {{ background: var(--accent-rose); }}
        .stat-num {{ font-size: 32px; font-weight: 800; color: #ffffff; line-height: 1.1; }}
        .stat-label {{ font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); margin-top: 6px; }}
        
        .section-card {{
            background: var(--bg-surface);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 28px;
            margin-bottom: 28px;
        }}
        .section-title {{
            font-size: 18px;
            font-weight: 600;
            color: #ffffff;
            margin-bottom: 16px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .exec-prose {{
            font-size: 15px;
            color: #d1d5db;
            line-height: 1.7;
            background: var(--bg-card);
            padding: 16px 20px;
            border-radius: 8px;
            border-left: 4px solid var(--accent-blue);
        }}
        .ai-callout {{
            background: #0b1528;
            border-left: 4px solid #3b82f6;
            padding: 16px 20px;
            margin-top: 12px;
            color: #e5e7eb;
            font-size: 14px;
        }}
        .mermaid-container {{
            background: #0d1117;
            padding: 24px;
            border-radius: 10px;
            border: 1px solid var(--border-color);
            overflow-x: auto;
            text-align: center;
        }}
        .story-chapter {{
            background: var(--bg-card);
            border-radius: 8px;
            padding: 18px 22px;
            margin-bottom: 16px;
            border: 1px solid rgba(255,255,255,0.05);
        }}
        .story-chapter h4 {{
            color: var(--accent-cyan);
            font-size: 15px;
            font-weight: 600;
            margin-bottom: 8px;
        }}
        .story-chapter p {{ color: #e5e7eb; font-size: 13.5px; line-height: 1.6; }}
        
        .footer {{
            margin-top: 48px;
            padding-top: 20px;
            border-top: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12px;
            color: var(--text-muted);
        }}
        @media print {{
            body {{ background: #ffffff; color: #111827; padding: 0; }}
            .section-card, .stat-card, .exec-prose, .story-chapter {{
                background: #ffffff; border-color: #e5e7eb; color: #111827;
            }}
            .stat-num {{ color: #111827; }}
            .stat-card::before {{ display: none; }}
            .ai-callout {{
            background: #0b1528;
            border-left: 4px solid #3b82f6;
            padding: 16px 20px;
            margin-top: 12px;
            color: #e5e7eb;
            font-size: 14px;
        }}
        .mermaid-container {{ background: #ffffff; border-color: #e5e7eb; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="header-left">
                <h1>🏛️ {res.project_name}</h1>
                <p>Enterprise Architecture Storyboard &amp; Safe Refactor Blueprint</p>
            </div>
            <div class="header-right">
                <span class="classification-badge">Strictly Confidential • Level {res.technical_depth}</span>
            </div>
        </header>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-num">{res.total_routes}</div>
                <div class="stat-label">API Route Endpoints</div>
            </div>
            <div class="stat-card cyan">
                <div class="stat-num">{res.total_models}</div>
                <div class="stat-label">Database Schemas</div>
            </div>
            <div class="stat-card emerald">
                <div class="stat-num">{res.total_service_calls}</div>
                <div class="stat-label">Service Ingestion Points</div>
            </div>
            <div class="stat-card rose">
                <div class="stat-num">{len(res.context_popups)}</div>
                <div class="stat-label">Archival Forensic Nodes</div>
            </div>
        </div>

        <div class="section-card">
            <div class="section-title">📌 Executive Architecture Summary</div>
            <div class="exec-prose">
                {res.executive_summary}
            </div>
        </div>

        <div class="section-card">
            <div class="section-title">📊 Architectural Flow &amp; Service Mindmap</div>
            <div class="mermaid-container">
                <div class="mermaid">
{res.mermaid_diagram}
                </div>
            </div>
        </div>
        
        <div class="section-card">
            <div class="section-title">🔎 Cluster Deep Dive</div>
            <div class="ai-callout">
                {ai_cluster_html}
            </div>
        </div>
        
        <div class="section-card">
            <div class="section-title">🚀 Modernization Roadmap</div>
            <div class="ai-callout">
                {ai_roadmap_html}
            </div>
        </div>

        <div class="section-card">
            <div class="section-title">📖 5-Minute Plain-English Storyboard</div>
            {''.join(f'<div class="story-chapter"><h4>{c["title"]}</h4><p>{c["content"]}</p></div>' for c in res.five_minute_story)}
        </div>

        <div class="footer">
            <div>Generated by <strong>IBM Bob 2.0 Polyglot Engine</strong> &bull; Architecture Storyteller</div>
            <div>Technical Depth: Level {res.technical_depth} &bull; Layers: {", ".join(res.active_layers)}</div>
        </div>
    </div>
</body>
</html>"""
    html_file = out_file.with_suffix(".html")
    html_file.write_text(html_content, encoding="utf-8")
    print(f"[OK] Generated Architecture Dossier HTML: {html_file}")
    
    pdf_file = out_file.with_suffix(".pdf")
    try:
        # Dynamically append tools/py-ast-core to sys.path to load enterprise pdf generator
        py_ast_dir = (_HERE.parent / "py-ast-core")
        if str(py_ast_dir) not in sys.path:
            sys.path.insert(0, str(py_ast_dir))

        from pdf_generator import build_pdf
        from ast_extractor import extract_repo_ast_impl
        import asyncio

        ast_res = asyncio.run(extract_repo_ast_impl(repo))
        project_name = Path(repo).name
        
        # --- AI INGESTION ---
        try:
            _SCRIPTS = _HERE.parent.parent / "scripts"
            if str(_SCRIPTS) not in sys.path:
                sys.path.insert(0, str(_SCRIPTS))
            from bob_bridge import invoke_bob
            
            print("[INFO]  Querying IBM Bob AI for Executive Architecture Assessment...")
            res_exec = invoke_bob(f"Executive Architecture Assessment for {project_name}")
            ast_res["meta"]["ai_exec_assessment"] = res_exec.stdout if res_exec else ""
            
            print("[INFO]  Querying IBM Bob AI for Cluster Deep Dive...")
            res_cluster = invoke_bob(f"Cluster B & C Deep Dive for {project_name}")
            ast_res["meta"]["ai_cluster_deep_dive"] = res_cluster.stdout if res_cluster else ""
            
            print("[INFO]  Querying IBM Bob AI for Modernization Roadmap...")
            res_roadmap = invoke_bob(f"Modernization Roadmap for {project_name}")
            ast_res["meta"]["ai_roadmap"] = res_roadmap.stdout if res_roadmap else ""
        except Exception as e:
            print(f"[WARN]  Failed to invoke Bob AI: {e}", file=sys.stderr)
            ast_res["meta"]["ai_exec_assessment"] = "AI Module Unavailable."
            ast_res["meta"]["ai_cluster_deep_dive"] = "AI Module Unavailable."
            ast_res["meta"]["ai_roadmap"] = "AI Module Unavailable."

        build_pdf(ast_res, project_name, str(pdf_file))
        print(f"[OK] PDF written: {pdf_file}")
    except Exception as exc:
        import traceback
        print(f"[WARN] Vector PDF generation failed: {exc}")
        traceback.print_exc()
        print(f"[INFO] Falling back to HTML dossier: {html_file}")
    print(f"[TIP] Open {html_file.name} in browser or VS Code and press Ctrl+P -> Save as PDF for vector rendering.")


def _run_server(repo: str, port: int):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import urllib.parse

    class StoryHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._handle(self.path, body=None)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b""
            # Accept JSON body params as overrides; fall back to query string
            try:
                body = json.loads(raw) if raw else {}
            except Exception:
                body = {}
            self._handle(self.path, body=body)

        def _handle(self, path: str, body: dict | None):
            parsed = urllib.parse.urlparse(path)
            if parsed.path == "/health":
                self._send_json({"status": "ok", "service": "storyteller-engine"})
                return

            qs = urllib.parse.parse_qs(parsed.query)
            b = body or {}

            raw_depth = b.get("depth") or qs.get("depth", [1])[0]
            depth = int(raw_depth)

            raw_layers = b.get("layers") or qs.get("layers", ["frontend,backend,db,git"])[0]
            if isinstance(raw_layers, list):
                layers = [l.strip() for l in raw_layers if l.strip()]
            else:
                layers = [l.strip() for l in raw_layers.split(",") if l.strip()]

            symbol = b.get("symbol") or qs.get("symbol", [None])[0]

            try:
                synth = StorySynthesizer(repo)
                res = synth.synthesize(technical_depth=depth, active_layers=layers, target_symbol=symbol)
                self._send_json(res.to_dict())
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)

        def _send_json(self, data: dict, status: int = 200):
            payload = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, fmt: str, *args) -> None:  # silence per-request access logs
            pass

    # Probe the port before binding so Windows SO_REUSEADDR doesn't silently
    # let two servers coexist on the same port.
    import socket as _socket
    _probe = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    _probe.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 0)
    try:
        _probe.bind(("127.0.0.1", port))
        _probe.close()
    except OSError as exc:
        _probe.close()
        print(f"[ERROR] Cannot bind to port {port}: {exc}", flush=True)
        sys.exit(1)

    try:
        server = HTTPServer(("127.0.0.1", port), StoryHandler)
    except OSError as exc:
        print(f"[ERROR] Cannot bind to port {port}: {exc}", flush=True)
        sys.exit(1)

    print(f"Storyteller Agent Server running at http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
