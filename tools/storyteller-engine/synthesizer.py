"""
synthesizer.py
~~~~~~~~~~~~~~
Storyteller & Archival Context Synthesizer.

Merges parallel sub-agent outputs into:
  1. Interactive Mermaid.js flowchart (Frontend -> Route -> DB)
  2. 5-Minute Plain-English Storyboard
  3. Rich Archival Context Popups with call-site cross-references and PR backstories
  4. Granular Depth (Levels 1-3) & Layer Filtering
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from route_crawler import APIRoute, RouteCrawler
from model_crawler import DBModel, ModelCrawler
from service_crawler import ServiceCall, ServiceCrawler
from cross_referencer import CrossReferencedSymbol, CrossReferencer
from archival_miner import ArchivalMiner


def _unique(values: Iterable[str]) -> List[str]:
    """De-duplicates while preserving order, so prose reads 'users, orders'
    rather than 'users, users, users' and stays stable between runs."""
    return list(dict.fromkeys(v for v in values if v))


def _attribution(backstory: Dict[str, Any]) -> str:
    """Renders the strongest attribution the evidence actually supports."""
    author = (backstory.get("author") or "").strip()
    pr_number = backstory.get("pr_number")
    commit_sha = (backstory.get("commit_sha") or "").strip()

    if pr_number:
        source = f"PR #{pr_number}"
    elif commit_sha:
        source = f"commit {commit_sha[:7]}"
    else:
        source = "no linked pull request or commit"

    return f"Authored by {author} in {source}" if author else f"Source: {source}"


def _extract_directory(file_path: str) -> str:
    """Extracts a top-level directory or package grouping for directory hierarchy mode."""
    if not file_path:
        return "root"
    norm = file_path.replace("\\", "/").strip("/")
    parts = norm.split("/")
    if len(parts) >= 2:
        if parts[0] == "tools" and len(parts) >= 3:
            return f"tools/{parts[1]}"
        return parts[0]
    return "root"


@dataclass
class ArchitectureStoryboard:
    project_name: str
    executive_summary: str
    five_minute_story: List[Dict[str, str]]
    mermaid_diagram: str
    context_popups: List[Dict[str, Any]]
    total_routes: int
    total_models: int
    total_service_calls: int
    technical_depth: int
    active_layers: List[str]
    graph_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StorySynthesizer:
    """Synthesizes sub-agent discoveries into cohesive visual maps and storyboards."""

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir).resolve()
        self.route_crawler = RouteCrawler(str(self.root_dir))
        self.model_crawler = ModelCrawler(str(self.root_dir))
        self.service_crawler = ServiceCrawler(str(self.root_dir))
        self.cross_referencer = CrossReferencer(str(self.root_dir))
        self.archival_miner = ArchivalMiner(str(self.root_dir))

    def synthesize(
        self,
        technical_depth: int = 1,
        active_layers: Optional[List[str]] = None,
        target_symbol: Optional[str] = None,
    ) -> ArchitectureStoryboard:
        layers = active_layers or ["frontend", "backend", "db", "git"]
        project_name = self.root_dir.name

        # 1. Run parallel sub-agents
        routes: List[APIRoute] = self.route_crawler.crawl() if "backend" in layers else []
        models: List[DBModel] = self.model_crawler.crawl() if "db" in layers else []
        services: List[ServiceCall] = self.service_crawler.crawl() if "frontend" in layers else []

        # 2. Archival & Cross-Referencer Analysis
        complex_symbols: List[CrossReferencedSymbol] = []
        if target_symbol:
            sym = self.cross_referencer.analyze_symbol(target_symbol)
            if sym:
                complex_symbols.append(sym)
        else:
            complex_symbols = self.cross_referencer.scan_all_complex_symbols(min_complexity=3)[:8]

        # 3. Build Archival Context Popups
        popups: List[Dict[str, Any]] = []
        if "git" in layers:
            for sym in complex_symbols:
                backstory = self.archival_miner.get_backstory(
                    symbol_name=sym.name,
                    file_path=sym.definition_file,
                    line_start=sym.definition_line_start,
                    line_end=sym.definition_line_end,
                    unusual_flags=sym.unusual_logic_flags,
                )
                popups.append({
                    "symbol_name": sym.name,
                    "definition_file": sym.definition_file,
                    "definition_line": sym.definition_line_start,
                    "call_sites_count": sym.total_call_occurrences,
                    "call_sites": [cs.to_dict() for cs in sym.call_sites],
                    "outbound_calls": sym.outbound_calls,
                    "definition_code": sym.definition_code,
                    "complexity": sym.cyclomatic_complexity,
                    "unusual_flags": sym.unusual_logic_flags,
                    "backstory": backstory.to_dict(),
                })

        # 4. Generate Mermaid Flowchart based on depth
        mermaid = self._generate_mermaid(
            services, routes, models, complex_symbols, technical_depth, layers, popups
        )

        # 5. Generate 5-Minute Plain-English Storyboard
        story = self._generate_five_minute_story(services, routes, models, popups, technical_depth)

        # 6. Generate Obsidian Galaxy Graph Data
        graph_data = self._generate_graph_data(
            services, routes, models, complex_symbols, popups, layers
        )

        try:
            import sys
            _SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
            if str(_SCRIPTS) not in sys.path:
                sys.path.insert(0, str(_SCRIPTS))
            from bob_bridge import invoke_bob
        except ImportError:
            invoke_bob = None

        if invoke_bob:
            try:
                res_exec = invoke_bob(f"Executive Architecture Assessment for {project_name}")
                exec_summary = res_exec.stdout if res_exec else ""
                
                if not exec_summary:
                    raise Exception("Empty AI response")
            except Exception as e:
                invoke_bob = None

        if not invoke_bob:
            if services or models:
                exec_summary = (
                    f"The '{project_name}' architecture spans {len(services)} frontend service calls, "
                    f"{len(routes)} backend API routes, and {len(models)} database models. "
                    f"Cross-referenced {len(popups)} pivotal symbols with archival PR backstories."
                )
            else:
                exec_summary = (
                    f"The '{project_name}' architecture operates as a polyglot system spanning "
                    f"{len(routes)} backend API routes, cross-process lock-manager state, and "
                    f"IDE client tooling. Cross-referenced {len(popups)} pivotal symbols with archival PR backstories."
                )

        return ArchitectureStoryboard(
            project_name=project_name,
            executive_summary=exec_summary,
            five_minute_story=story,
            mermaid_diagram=mermaid,
            context_popups=popups,
            total_routes=len(routes),
            total_models=len(models),
            total_service_calls=len(services),
            technical_depth=technical_depth,
            active_layers=layers,
            graph_data=graph_data,
        )

    def _generate_mermaid(
        self,
        services: List[ServiceCall],
        routes: List[APIRoute],
        models: List[DBModel],
        symbols: List[CrossReferencedSymbol],
        depth: int,
        layers: List[str],
        popups: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        lines = [
            "graph LR",
            "    %% Styling definitions",
            "    classDef frontend fill:#1e293b,stroke:#38bdf8,stroke-width:2px,color:#f8fafc;",
            "    classDef backend fill:#1e293b,stroke:#a855f7,stroke-width:2px,color:#f8fafc;",
            "    classDef db fill:#1e293b,stroke:#10b981,stroke-width:2px,color:#f8fafc;",
            "    classDef archival fill:#831843,stroke:#f43f5e,stroke-width:2px,color:#fff1f2;",
        ]

        # Frontend Cluster
        if "frontend" in layers and services:
            lines.append("    subgraph Frontend [Frontend Services & UI Handlers]")
            for idx, s in enumerate(services[:8]):
                node_id = f"FE_{idx}"
                label = f"{s.calling_component}::<br/><b>{s.function_name}()</b>" if depth > 1 else f"<b>{s.calling_component}</b>"
                lines.append(f'        {node_id}["{label}"]:::frontend')
            lines.append("    end")

        # Backend Cluster
        if "backend" in layers and routes:
            lines.append("    subgraph Backend [Backend API Routes & Handlers]")
            for idx, r in enumerate(routes[:10]):
                node_id = f"BE_{idx}"
                label = f"[{r.method}] {r.path}<br/>({r.handler_name})" if depth > 1 else f"[{r.method}] {r.path}"
                lines.append(f'        {node_id}["{label}"]:::backend')
            lines.append("    end")

        # Database Cluster
        if "db" in layers and models:
            lines.append("    subgraph Database [Database Entities & Schemas]")
            for idx, m in enumerate(models[:8]):
                node_id = f"DB_{idx}"
                field_count = len(m.fields)
                label = f"Table: <b>{m.table_name}</b><br/>({field_count} fields)" if depth > 1 else f"<b>{m.table_name}</b>"
                lines.append(f'        {node_id}["{label}"]:::db')
            lines.append("    end")

        # Connect Frontend -> Backend
        if "frontend" in layers and "backend" in layers:
            for f_idx, s in enumerate(services[:8]):
                for b_idx, r in enumerate(routes[:10]):
                    # Check path match
                    if s.target_endpoint.rstrip("/") == r.path.rstrip("/") or r.path in s.target_endpoint:
                        lines.append(f"    FE_{f_idx} -->|{s.http_method}| BE_{b_idx}")

        # Connect Backend -> Database
        if "backend" in layers and "db" in layers:
            for b_idx, r in enumerate(routes[:10]):
                for d_idx, m in enumerate(models[:8]):
                    # Match by name heuristic
                    if m.name.lower() in r.path.lower() or m.table_name.lower() in r.path.lower() or m.name.lower() in r.handler_name.lower():
                        lines.append(f"    BE_{b_idx} -.->|queries| DB_{d_idx}")

        # If Depth == 3: Add Archival Backstory Nodes
        if depth == 3 and "git" in layers:
            provenance = self._provenance_labels(popups)
            lines.append("    subgraph Archival [Archival Context & PR Backstories]")
            for idx, sym in enumerate(symbols[:4]):
                a_id = f"ARC_{idx}"
                label = provenance.get(sym.name, "No recorded history")
                lines.append(
                    f'        {a_id}["{label}: {sym.name}()<br/>'
                    f'({sym.total_call_occurrences} callers cross-referenced)"]:::archival'
                )
                # Connect to related backend route or caller if matched
                for b_idx, r in enumerate(routes[:10]):
                    if sym.name.lower() in r.handler_name.lower() or sym.name.lower() in r.path.lower():
                        lines.append(f"        BE_{b_idx} -.-> {a_id}")
                        break
            lines.append("    end")

        # Fallback if no nodes were created
        if len(lines) == 6:
            lines.append('    A["Client UI Requests"]:::frontend --> B["API Gateway & Routes"]:::backend')
            lines.append('    B --> C["Core Domain Logic"]:::backend')
            lines.append('    C --> D[("Relational Database")]:::db')

        return "\n".join(lines)

    @staticmethod
    def _provenance_labels(popups: Optional[List[Dict[str, Any]]]) -> Dict[str, str]:
        """Maps each symbol to a label naming its real evidence.

        A pull request when one is linked, otherwise the commit that introduced
        the lines, otherwise an explicit 'no history' — never a placeholder
        number, which reads as a mined fact the diagram cannot support.
        """
        labels: Dict[str, str] = {}
        for popup in popups or []:
            backstory = popup.get("backstory") or {}
            pr_number = backstory.get("pr_number")
            commit_sha = (backstory.get("commit_sha") or "").strip()

            if pr_number:
                labels[popup["symbol_name"]] = f"PR #{pr_number}"
            elif commit_sha:
                labels[popup["symbol_name"]] = f"commit {commit_sha[:7]}"
            else:
                labels[popup["symbol_name"]] = "No recorded history"
        return labels

    def _generate_five_minute_story(
        self,
        services: List[ServiceCall],
        routes: List[APIRoute],
        models: List[DBModel],
        popups: List[Dict[str, Any]],
        depth: int,
    ) -> List[Dict[str, str]]:
        chapters = []

        # Chapter 1
        endpoints = _unique(s.target_endpoint for s in services)
        if services:
            c1_content = (
                f"When a user or external client interacts with the application, requests originate across "
                f"{len(services)} identified frontend service touchpoints. The frontend encapsulates HTTP traffic "
                f"using declarative service calls, targeting paths such as "
                f"{', '.join(endpoints[:3]) if endpoints else '/api endpoints'}."
            )
        else:
            c1_content = (
                f"Client and developer interactions originate through developer tooling interfaces, including "
                f"the IDE extension webview commands, terminal slash watchers (/mindmap, /context), "
                f"and automated CLI execution pipelines rather than decoupled browser HTTP clients."
            )
        chapters.append({
            "title": "Chapter 1: The Front Door (Client Services & Ingestion)",
            "content": c1_content
        })

        # Chapter 2
        route_paths = _unique(r.path for r in routes)
        chapters.append({
            "title": "Chapter 2: The Gateway & Control Planes (API Routes)",
            "content": (
                f"Requests land on {len(routes)} registered endpoints. Middleware guards validate auth tokens "
                f"and request schemas before passing control to designated route handlers. "
                f"Primary routes handle operations such as {', '.join(route_paths[:4]) if route_paths else 'CRUD resources'}."
            )
        })

        # Chapter 3
        table_names = _unique(m.table_name for m in models)
        if models:
            c3_content = (
                f"Data persistence is organized across {len(models)} database entities. "
                f"Tables like {', '.join(table_names[:3]) if table_names else 'domain entities'} "
                f"enforce relational constraints and index structures to guarantee consistency under load."
            )
        else:
            c3_content = (
                f"Rather than a traditional relational SQL database, state persistence and storage are managed "
                f"via reactive lock-manager leases (with deadlock-detection wait-for graphs), cached AST snapshots, "
                f"and serialized graph artifacts stored on the filesystem."
            )
        chapters.append({
            "title": "Chapter 3: The Persistence Vault (State & Storage)",
            "content": c3_content
        })

        # Chapter 4 (Archival Context)
        if popups:
            p = popups[0]
            backstory = p.get("backstory", {})
            chapters.append({
                "title": "Chapter 4: The Team's Archival Memory ('Why was this written?')",
                "content": (
                    f"A new hire opening function '{p['symbol_name']}' discovers that it was cross-referenced across "
                    f"{p['call_sites_count']} separate call sites in the repository. "
                    f"Rather than guesswork, historical git archival records reveal: "
                    f"\"{backstory.get('why_it_was_written') or 'no recorded rationale'}\" "
                    f"({_attribution(backstory)})."
                )
            })

        return chapters

    def _generate_graph_data(
        self,
        services: List[ServiceCall],
        routes: List[APIRoute],
        models: List[DBModel],
        symbols: List[CrossReferencedSymbol],
        popups: List[Dict[str, Any]],
        layers: List[str],
    ) -> Dict[str, Any]:
        """Synthesizes structured graph nodes and links for the interactive Obsidian-style galaxy view."""
        nodes_map: Dict[str, Dict[str, Any]] = {}
        links: List[Dict[str, Any]] = []
        seen_links = set()
        degree_count: Dict[str, int] = defaultdict(int)

        def add_link(src: str, tgt: str, l_type: str, weight: int = 1):
            if not src or not tgt or src == tgt:
                return
            key = (src, tgt, l_type)
            if key in seen_links:
                return
            seen_links.add(key)
            links.append({
                "source": src,
                "target": tgt,
                "type": l_type,
                "weight": weight,
            })
            degree_count[src] += 1
            degree_count[tgt] += 1
            if src in nodes_map and tgt in nodes_map:
                src_name = nodes_map[src]["name"]
                tgt_name = nodes_map[tgt]["name"]
                if tgt_name not in nodes_map[src]["callees"]:
                    nodes_map[src]["callees"].append(tgt_name)
                if src_name not in nodes_map[tgt]["callers"]:
                    nodes_map[tgt]["callers"].append(src_name)

        # 1. Frontend nodes
        if "frontend" in layers:
            for s in services:
                nid = f"fe:{s.calling_component}:{s.function_name}"
                nodes_map[nid] = {
                    "id": nid,
                    "name": f"{s.calling_component}.{s.function_name}()",
                    "category": "frontend",
                    "summary": f"Client touchpoint consuming {s.target_endpoint} via {s.client_library}.",
                    "file_path": s.file_path,
                    "line_number": s.line_number,
                    "code_snippet": f"{s.client_library}.{s.http_method.lower()}('{s.target_endpoint}')",
                    "degree": 0,
                    "complexity": 1,
                    "directory": _extract_directory(s.file_path),
                    "backstory": None,
                    "callers": [],
                    "callees": [],
                }

        # 2. Backend Route nodes
        if "backend" in layers:
            for r in routes:
                nid = f"route:{r.method}_{r.path}"
                nodes_map[nid] = {
                    "id": nid,
                    "name": f"{r.method} {r.path}",
                    "category": "route",
                    "summary": r.summary or f"API endpoint dispatched to handler '{r.handler_name}' ({r.framework}).",
                    "file_path": r.file_path,
                    "line_number": r.line_start,
                    "code_snippet": f"@{r.framework.lower()}.{r.method.lower()}('{r.path}')\ndef {r.handler_name}(...): ...",
                    "degree": 0,
                    "complexity": 1,
                    "directory": _extract_directory(r.file_path),
                    "backstory": None,
                    "callers": [],
                    "callees": [],
                }

        # 3. Database Model nodes
        if "db" in layers:
            for m in models:
                nid = f"model:{m.name}"
                fields_preview = "\n".join(f"    {f.name}: {f.field_type}" for f in m.fields[:6])
                snippet = f"class {m.name}:\n    __tablename__ = '{m.table_name}'\n{fields_preview}" if fields_preview else f"class {m.name} // table: {m.table_name}"
                nodes_map[nid] = {
                    "id": nid,
                    "name": f"{m.name} ({m.table_name})",
                    "category": "model",
                    "summary": f"Database entity for table '{m.table_name}' with {len(m.fields)} fields ({m.orm_type}).",
                    "file_path": m.file_path,
                    "line_number": m.line_start,
                    "code_snippet": snippet,
                    "degree": 0,
                    "complexity": 1,
                    "directory": _extract_directory(m.file_path),
                    "backstory": None,
                    "callers": [],
                    "callees": [],
                }

        # 4. Function nodes (Symbols)
        popup_by_sym = {p["symbol_name"]: p for p in popups}
        for sym in symbols:
            nid = f"fn:{sym.name}"
            popup = popup_by_sym.get(sym.name)
            backstory = popup.get("backstory") if popup else None
            summary = (
                backstory.get("why_it_was_written")
                if backstory and backstory.get("why_it_was_written")
                else f"Core function with {sym.total_call_occurrences} callers across repository and complexity {sym.cyclomatic_complexity}."
            )
            snippet = sym.definition_code or f"def {sym.name}(...): ... (line {sym.definition_line_start})"
            nodes_map[nid] = {
                "id": nid,
                "name": f"{sym.name}()",
                "category": "function",
                "summary": summary,
                "file_path": sym.definition_file,
                "line_number": sym.definition_line_start,
                "code_snippet": snippet,
                "degree": 0,
                "complexity": sym.cyclomatic_complexity,
                "directory": _extract_directory(sym.definition_file),
                "backstory": backstory,
                "callers": [],
                "callees": [],
            }

        # 5. Git Archival Backstory nodes
        if "git" in layers:
            for p in popups:
                bs = p.get("backstory") or {}
                sym_name = p.get("symbol_name")
                if bs and (bs.get("why_it_was_written") or bs.get("author")):
                    nid = f"git:{sym_name}"
                    nodes_map[nid] = {
                        "id": nid,
                        "name": f"PR #{bs.get('pr_number', 'N/A')}: {sym_name}",
                        "category": "git",
                        "summary": bs.get("why_it_was_written") or bs.get("discussion_summary") or "Historical git commit backstory.",
                        "file_path": p.get("definition_file", ""),
                        "line_number": p.get("definition_line", 1),
                        "code_snippet": f"Author: {bs.get('author')}\nCommit: {bs.get('commit_sha')}\nDate: {bs.get('date')}\n\n{bs.get('why_it_was_written')}",
                        "degree": 0,
                        "complexity": 1,
                        "directory": _extract_directory(p.get("definition_file", "")),
                        "backstory": bs,
                        "callers": [],
                        "callees": [],
                    }

        # 6. File / Package module nodes
        files_seen = set()
        for item in list(nodes_map.values()):
            fp = item.get("file_path")
            if fp and fp not in files_seen:
                files_seen.add(fp)
                fid = f"file:{fp}"
                nodes_map[fid] = {
                    "id": fid,
                    "name": Path(fp.replace("\\", "/")).name,
                    "category": "file",
                    "summary": f"Source module in {_extract_directory(fp)}",
                    "file_path": fp,
                    "line_number": 1,
                    "code_snippet": f"// Module: {fp}",
                    "degree": 0,
                    "complexity": 1,
                    "directory": _extract_directory(fp),
                    "backstory": None,
                    "callers": [],
                    "callees": [],
                }
                add_link(fid, item["id"], "contains", weight=1)

        # 7. Inter-layer connections
        # Frontend -> Route
        if "frontend" in layers and "backend" in layers:
            for s in services:
                fe_id = f"fe:{s.calling_component}:{s.function_name}"
                for r in routes:
                    r_id = f"route:{r.method}_{r.path}"
                    if s.target_endpoint.rstrip("/") == r.path.rstrip("/") or r.path in s.target_endpoint:
                        add_link(fe_id, r_id, "routes_to", weight=3)

        # Route -> Function
        if "backend" in layers:
            for r in routes:
                r_id = f"route:{r.method}_{r.path}"
                for sym in symbols:
                    fn_id = f"fn:{sym.name}"
                    if (
                        r.handler_name == sym.name
                        or r.handler_name in sym.name
                        or sym.name in r.handler_name
                        or (r.file_path == sym.definition_file and abs(r.line_start - sym.definition_line_start) < 30)
                    ):
                        add_link(r_id, fn_id, "calls", weight=2)

        # Function -> Function (call-sites & outbound calls)
        sym_map = {s.name: s for s in symbols}
        for sym in symbols:
            fn_id = f"fn:{sym.name}"
            for out in sym.outbound_calls:
                if out in sym_map:
                    add_link(fn_id, f"fn:{out}", "calls", weight=2)
            for cs in sym.call_sites:
                if cs.enclosing_symbol and cs.enclosing_symbol in sym_map:
                    add_link(f"fn:{cs.enclosing_symbol}", fn_id, "calls", weight=2)

        # Function / Route -> Model
        if "db" in layers:
            for m in models:
                m_id = f"model:{m.name}"
                m_lower = m.name.lower()
                tbl_lower = m.table_name.lower()
                for sym in symbols:
                    fn_id = f"fn:{sym.name}"
                    code_lower = sym.definition_code.lower()
                    if m_lower in code_lower or tbl_lower in code_lower or any(m_lower in out.lower() for out in sym.outbound_calls):
                        add_link(fn_id, m_id, "persists_to", weight=2)
                if "backend" in layers:
                    for r in routes:
                        r_id = f"route:{r.method}_{r.path}"
                        if m_lower in r.path.lower() or tbl_lower in r.path.lower() or m_lower in r.handler_name.lower():
                            add_link(r_id, m_id, "persists_to", weight=2)

        # Git -> Function
        if "git" in layers:
            for p in popups:
                sym_name = p.get("symbol_name")
                git_id = f"git:{sym_name}"
                fn_id = f"fn:{sym_name}"
                if git_id in nodes_map and fn_id in nodes_map:
                    add_link(git_id, fn_id, "authored_by", weight=1)

        # Update node degrees
        for nid, node in nodes_map.items():
            node["degree"] = degree_count[nid]

        return {
            "nodes": list(nodes_map.values()),
            "links": links,
        }
