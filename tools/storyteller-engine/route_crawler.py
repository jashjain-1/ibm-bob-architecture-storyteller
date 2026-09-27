"""
route_crawler.py
~~~~~~~~~~~~~~~~
Sub-Agent 1: Crawls backend API routes across polyglot frameworks:
  - Python: FastAPI (@app.get, @router.post), Flask (@app.route), Django (path(...))
  - TypeScript/JavaScript: Express (app.get, router.post), Next.js App Router (export async function GET), NestJS
  - Go: Gin (r.GET), Chi (r.Post), Standard net/http (mux.HandleFunc)
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from scan_filter import blank_comments, collect_files


@dataclass
class APIRoute:
    method: str
    path: str
    handler_name: str
    file_path: str
    line_start: int
    line_end: int
    framework: str
    params: List[str] = field(default_factory=list)
    middleware: List[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RouteCrawler:
    """Sub-agent responsible for discovering API routes and handler linkages."""

    EXTENSIONS = (".py", ".ts", ".js", ".tsx", ".jsx", ".go")

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir).resolve()

    def crawl(self, target_files: Optional[List[str]] = None) -> List[APIRoute]:
        routes: List[APIRoute] = []
        files = target_files or collect_files(self.root_dir, self.EXTENSIONS)

        for fpath in files:
            path_obj = Path(fpath)
            if not path_obj.is_file():
                continue
            ext = path_obj.suffix.lower()
            try:
                content = path_obj.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            # A route decorator quoted in a comment is documentation, not a route.
            content = blank_comments(content, ext)
            rel_path = str(path_obj.relative_to(self.root_dir)).replace("\\", "/")

            if ext == ".py":
                routes.extend(self._crawl_python(content, rel_path))
            elif ext in (".ts", ".js", ".tsx", ".jsx"):
                routes.extend(self._crawl_typescript_javascript(content, rel_path))
            elif ext == ".go":
                routes.extend(self._crawl_go(content, rel_path))

        return routes

    def _crawl_python(self, content: str, file_path: str) -> List[APIRoute]:
        routes = []
        lines = content.splitlines()

        # Pattern 1: FastAPI / Flask decorators: @app.get("/path"), @router.post("/path")
        decorator_pattern = re.compile(
            r'@(?:\w+\.)?(get|post|put|delete|patch|options|head|route)\s*\(\s*["\']([^"\']+)["\']',
            re.IGNORECASE,
        )
        def_pattern = re.compile(r'^\s*(?:async\s+)?def\s+([a-zA-Z_]\w*)\s*\((.*?)\)', re.MULTILINE)

        for i, line in enumerate(lines):
            match = decorator_pattern.search(line)
            if match:
                method = match.group(1).upper()
                if method == "ROUTE":
                    # Check for methods=['POST'] etc.
                    m_match = re.search(r'methods\s*=\s*\[["\'](\w+)["\']\]', line, re.IGNORECASE)
                    method = m_match.group(1).upper() if m_match else "GET"

                path = match.group(2)
                # Look ahead for def
                handler_name = "unknown_handler"
                params = []
                line_end = i + 1
                for j in range(i + 1, min(i + 15, len(lines))):
                    def_match = def_pattern.search(lines[j])
                    if def_match:
                        handler_name = def_match.group(1)
                        param_str = def_match.group(2)
                        params = [p.strip().split(":")[0].strip() for p in param_str.split(",") if p.strip() and p.strip() != "self"]
                        line_end = j + 1
                        break

                routes.append(APIRoute(
                    method=method,
                    path=path,
                    handler_name=handler_name,
                    file_path=file_path,
                    line_start=i + 1,
                    line_end=line_end,
                    framework="FastAPI/Flask",
                    params=params,
                    summary=f"{method} {path} handled by {handler_name}",
                ))

        # Pattern 2: Django path('api/users/', views.user_list)
        django_pattern = re.compile(
            r'path\s*\(\s*["\']([^"\']+)["\']\s*,\s*([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)',
            re.IGNORECASE,
        )
        for i, line in enumerate(lines):
            m = django_pattern.search(line)
            if m:
                path = "/" + m.group(1).lstrip("/")
                handler = m.group(2).split(".")[-1]
                routes.append(APIRoute(
                    method="ANY",
                    path=path,
                    handler_name=handler,
                    file_path=file_path,
                    line_start=i + 1,
                    line_end=i + 1,
                    framework="Django",
                    summary=f"ANY {path} -> {handler}",
                ))

        return routes

    def _crawl_typescript_javascript(self, content: str, file_path: str) -> List[APIRoute]:
        routes = []
        lines = content.splitlines()

        # Express: router.get('/path', handler), app.post('/path', auth, handler)
        express_pattern = re.compile(
            r'\b(?:app|router|server)\.(get|post|put|delete|patch|use)\s*\(\s*["\']([^"\']+)["\']\s*,\s*(.*)',
            re.IGNORECASE,
        )
        for i, line in enumerate(lines):
            match = express_pattern.search(line)
            if match:
                method = match.group(1).upper()
                path = match.group(2)
                rest = match.group(3).strip()
                # Extract handler name
                handler_match = re.search(r'([a-zA-Z_]\w*)(?:\s*,|\s*\))', rest)
                handler_name = handler_match.group(1) if handler_match else "anonymous_handler"
                routes.append(APIRoute(
                    method=method,
                    path=path,
                    handler_name=handler_name,
                    file_path=file_path,
                    line_start=i + 1,
                    line_end=i + 1,
                    framework="Express",
                    summary=f"{method} {path} -> {handler_name}",
                ))

        # Next.js App Router: api/users/route.ts -> export async function GET(req)
        if "app/" in file_path and ("route.ts" in file_path or "route.js" in file_path):
            # Compute path from directory
            norm = file_path.replace("\\", "/")
            api_idx = norm.find("/app/")
            route_sub = norm[api_idx + 5:].replace("/route.ts", "").replace("/route.js", "")
            route_path = "/" + route_sub

            next_func_pattern = re.compile(r'export\s+(?:async\s+)?function\s+(GET|POST|PUT|DELETE|PATCH)\s*\(', re.IGNORECASE)
            for i, line in enumerate(lines):
                m = next_func_pattern.search(line)
                if m:
                    method = m.group(1).upper()
                    routes.append(APIRoute(
                        method=method,
                        path=route_path,
                        handler_name=f"{method}_{route_sub.replace('/', '_')}",
                        file_path=file_path,
                        line_start=i + 1,
                        line_end=i + 1,
                        framework="Next.js App Route",
                        summary=f"{method} {route_path}",
                    ))

        return routes

    def _crawl_go(self, content: str, file_path: str) -> List[APIRoute]:
        routes = []
        lines = content.splitlines()

        # Gin / Chi: r.GET("/path", handler), router.POST("/path", handler)
        go_route_pattern = re.compile(
            r'\b\w+\.(GET|POST|PUT|DELETE|PATCH|HandleFunc)\s*\(\s*["\']([^"\']+)["\']\s*,\s*([a-zA-Z_]\w*)',
        )
        for i, line in enumerate(lines):
            match = go_route_pattern.search(line)
            if match:
                raw_method = match.group(1)
                method = "ANY" if raw_method == "HandleFunc" else raw_method.upper()
                path = match.group(2)
                handler_name = match.group(3)
                routes.append(APIRoute(
                    method=method,
                    path=path,
                    handler_name=handler_name,
                    file_path=file_path,
                    line_start=i + 1,
                    line_end=i + 1,
                    framework="Go/Gin/Chi",
                    summary=f"{method} {path} -> {handler_name}",
                ))

        return routes
