"""
service_crawler.py
~~~~~~~~~~~~~~~~~~
Sub-Agent 3: Crawls frontend service calls, HTTP client requests, and API consumers:
  - Axios (axios.get, api.post, apiClient.delete)
  - Native Fetch (fetch('/api/...'))
  - TanStack React Query (useQuery, useMutation)
  - RTK Query / Custom API wrappers
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, List, Optional

from scan_filter import blank_comments, collect_files


@dataclass
class ServiceCall:
    function_name: str
    target_endpoint: str
    http_method: str
    file_path: str
    line_number: int
    client_library: str
    calling_component: str = "Unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ServiceCrawler:
    """Sub-agent responsible for discovering frontend service calls and endpoint invocations."""

    EXTENSIONS = (".ts", ".js", ".tsx", ".jsx", ".py")

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir).resolve()

    def crawl(self, target_files: Optional[List[str]] = None) -> List[ServiceCall]:
        calls: List[ServiceCall] = []
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

            # A fetch() shown in a comment is an example, not a live call.
            content = blank_comments(content, ext)
            rel_path = str(path_obj.relative_to(self.root_dir)).replace("\\", "/")

            if ext in (".ts", ".js", ".tsx", ".jsx"):
                calls.extend(self._crawl_js_ts_services(content, rel_path))
            elif ext == ".py":
                calls.extend(self._crawl_python_http_clients(content, rel_path))

        return calls

    def _crawl_js_ts_services(self, content: str, file_path: str) -> List[ServiceCall]:
        calls = []
        lines = content.splitlines()

        # Component / Enclosing function heuristic
        current_component = Path(file_path).stem

        # Pattern 1: axios.get('/api/users') or api.post(`/api/users/${id}`)
        axios_pattern = re.compile(
            r'\b(?:axios|api|client|apiClient|httpClient)\.(get|post|put|delete|patch)\s*\(\s*[`\'"]([^`\'"]+)[`\'"]',
            re.IGNORECASE,
        )

        # Pattern 2: fetch('/api/...')
        fetch_pattern = re.compile(
            r'\bfetch\s*\(\s*[`\'"]([^`\'"]+)[`\'"](?:\s*,\s*\{\s*method:\s*[`\'"]([A-Z]+)[`\'"])?',
            re.IGNORECASE,
        )

        # Pattern 3: Named exported service functions e.g. export const fetchUsers = () => axios.get(...)
        named_export_pattern = re.compile(
            r'export\s+(?:const|function|async\s+function)\s+([a-zA-Z_]\w*)'
        )

        current_func = current_component
        for i, line in enumerate(lines):
            # Track enclosing function / export
            f_match = named_export_pattern.search(line)
            if f_match:
                current_func = f_match.group(1)

            # Check Axios
            for m in axios_pattern.finditer(line):
                method = m.group(1).upper()
                endpoint = m.group(2)
                calls.append(ServiceCall(
                    function_name=current_func,
                    target_endpoint=endpoint,
                    http_method=method,
                    file_path=file_path,
                    line_number=i + 1,
                    client_library="Axios",
                    calling_component=current_component,
                ))

            # Check Fetch
            for m in fetch_pattern.finditer(line):
                endpoint = m.group(1)
                method = (m.group(2) or "GET").upper()
                calls.append(ServiceCall(
                    function_name=current_func,
                    target_endpoint=endpoint,
                    http_method=method,
                    file_path=file_path,
                    line_number=i + 1,
                    client_library="Fetch",
                    calling_component=current_component,
                ))

        return calls

    def _crawl_python_http_clients(self, content: str, file_path: str) -> List[ServiceCall]:
        calls = []
        lines = content.splitlines()
        comp = Path(file_path).stem

        # requests.get("http://.../api/...") or httpx.post(...)
        pattern = re.compile(
            r'\b(?:requests|httpx|session|client)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
            re.IGNORECASE,
        )
        for i, line in enumerate(lines):
            for m in pattern.finditer(line):
                method = m.group(1).upper()
                endpoint = m.group(2)
                calls.append(ServiceCall(
                    function_name=comp,
                    target_endpoint=endpoint,
                    http_method=method,
                    file_path=file_path,
                    line_number=i + 1,
                    client_library="Requests/HTTPX",
                    calling_component=comp,
                ))

        return calls
