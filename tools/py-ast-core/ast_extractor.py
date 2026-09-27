"""
ast_extractor.py
~~~~~~~~~~~~~~~~
Extracts a structured AST summary (symbols, entry points, dependency edges)
from a repository.

Primary engine  : tree-sitter (when grammar bindings are importable).
Fallback engine : zero-dependency native parsing
                  – Python  : stdlib `ast` + `ast.NodeVisitor`
                  – Go      : regex / lexical scan
                  – TS / JS : regex / lexical scan
"""

from __future__ import annotations

import ast
import fnmatch
import os
import re
from typing import Optional

# ---------------------------------------------------------------------------
# Tree-sitter availability probe
# ---------------------------------------------------------------------------
_TREESITTER_AVAILABLE = False
try:
    import tree_sitter  # noqa: F401
    _TREESITTER_AVAILABLE = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Language helpers
# ---------------------------------------------------------------------------
_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".go": "go",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
}

_DEFAULT_EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    "venv",
    ".venv",
    "env",
    ".env",
    "dist",
    "build",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".claude",
    ".gemini",
    ".vscode",
    ".bobide",
    "output",
    "traces",
    "worktrees",
    ".context-cache",
}

# ---------------------------------------------------------------------------
# Schema Data-mapping helpers
# ---------------------------------------------------------------------------

def _sym(
    *,
    name: str,
    sym_type: str,
    file_path: str,
    line_start: int,
    line_end: int,
    language: str,
    symbol_id: Optional[str] = None,
    exported: bool = False,
    parameters: Optional[list[dict]] = None,
    return_type: Optional[str] = None,
    calls: Optional[list[str]] = None,
    imports: Optional[list[str]] = None,
) -> dict:
    return {
        "id": symbol_id or f"{file_path}::{name}",
        "type": sym_type,
        "name": name,
        "file_path": file_path,
        "line_start": line_start,
        "line_end": line_end,
        "language": language,
        "exports": exported,
        "exported": exported,  # backward compatibility
        "parameters": parameters or [],
        "return_type": return_type,
        "calls": calls or [],
        "imports": imports or [],
    }


def _entry(*, symbol_id: str, kind: str, file_path: str, line: int) -> dict:
    # Normalize kind to schema type: main|route|cli|export
    entry_type = "main" if kind in ("main", "dunder_main") else kind
    return {
        "symbol_id": symbol_id,
        "type": entry_type,
        "kind": kind,
        "file_path": file_path,
        "line": line,
    }


def _edge(*, from_: str, to: str, edge_type: str) -> dict:
    return {"from": from_, "to": to, "type": edge_type}


# ===========================================================================
# Native Python extractor (stdlib ast)
# ===========================================================================

class _PythonCallCollector(ast.NodeVisitor):
    """Collect bare function-call names inside a function/method body."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            self.calls.append(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            parts = []
            cur: ast.expr = node.func
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
            self.calls.append(".".join(reversed(parts)))
        self.generic_visit(node)


def _py_annotation_str(node: Optional[ast.expr]) -> Optional[str]:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


def _extract_python_native(source: str, file_path: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (symbols, entry_points, edges) for a Python source string."""
    symbols: list[dict] = []
    entry_points: list[dict] = []
    edges: list[dict] = []

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return symbols, entry_points, edges

    import_modules: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                import_modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                import_modules.append(node.module)

    def _params(args: ast.arguments) -> list[dict]:
        params = []
        all_args = args.posonlyargs + args.args + args.kwonlyargs
        if args.vararg:
            all_args.append(args.vararg)
        if args.kwarg:
            all_args.append(args.kwarg)
        for arg in all_args:
            params.append(
                {
                    "name": arg.arg,
                    "type": _py_annotation_str(arg.annotation) or "",
                }
            )
        return params

    def _calls_in(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
        collector = _PythonCallCollector()
        collector.visit(func_node)
        return list(dict.fromkeys(collector.calls))

    def _end_line(node: ast.AST) -> int:
        return getattr(node, "end_lineno", node.lineno)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
            sym_id = f"{file_path}::{name}"
            exported = not name.startswith("_")
            calls = _calls_in(node)
            sym = _sym(
                name=name,
                sym_type="function",
                file_path=file_path,
                line_start=node.lineno,
                line_end=_end_line(node),
                language="python",
                exported=exported,
                parameters=_params(node.args),
                return_type=_py_annotation_str(node.returns),
                calls=calls,
                imports=import_modules,
            )
            symbols.append(sym)
            for c in calls:
                edges.append(_edge(from_=sym_id, to=c, edge_type="calls"))
            for m in import_modules:
                edges.append(_edge(from_=sym_id, to=m, edge_type="imports"))
            if name == "main":
                entry_points.append(_entry(symbol_id=sym_id, kind="main", file_path=file_path, line=node.lineno))

        elif isinstance(node, ast.ClassDef):
            cls_name = node.name
            cls_id = f"{file_path}::{cls_name}"
            exported = not cls_name.startswith("_")
            cls_sym = _sym(
                name=cls_name,
                sym_type="class",
                file_path=file_path,
                line_start=node.lineno,
                line_end=_end_line(node),
                language="python",
                exported=exported,
                imports=import_modules,
            )
            symbols.append(cls_sym)
            for base in node.bases:
                base_name = _py_annotation_str(base)
                if base_name:
                    edges.append(_edge(from_=cls_id, to=base_name, edge_type="extends"))
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_name = child.name
                    method_id = f"{file_path}::{cls_name}.{method_name}"
                    calls = _calls_in(child)
                    m_sym = _sym(
                        name=method_name,
                        symbol_id=method_id,
                        sym_type="method",
                        file_path=file_path,
                        line_start=child.lineno,
                        line_end=_end_line(child),
                        language="python",
                        exported=not method_name.startswith("_"),
                        parameters=_params(child.args),
                        return_type=_py_annotation_str(child.returns),
                        calls=calls,
                        imports=import_modules,
                    )
                    symbols.append(m_sym)
                    for c in calls:
                        edges.append(_edge(from_=method_id, to=c, edge_type="calls"))

        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for tgt in targets:
                if isinstance(tgt, ast.Name):
                    sym = _sym(
                        name=tgt.id,
                        sym_type="variable",
                        file_path=file_path,
                        line_start=node.lineno,
                        line_end=_end_line(node),
                        language="python",
                        exported=not tgt.id.startswith("_"),
                        return_type=_py_annotation_str(node.annotation)
                        if isinstance(node, ast.AnnAssign)
                        else None,
                    )
                    symbols.append(sym)

    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            if (
                isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id == "__name__"
                and len(test.ops) == 1
                and isinstance(test.ops[0], ast.Eq)
                and len(test.comparators) == 1
                and isinstance(test.comparators[0], ast.Constant)
                and test.comparators[0].value == "__main__"
            ):
                entry_points.append(
                    _entry(
                        symbol_id=f"{file_path}::__main__",
                        kind="dunder_main",
                        file_path=file_path,
                        line=node.lineno,
                    )
                )

    return symbols, entry_points, edges


# ===========================================================================
# Native Go extractor (regex-based lexical scan)
# ===========================================================================

_GO_FUNC_RE = re.compile(
    r"^func\s+(?:\((?P<recv>[^)]*)\)\s+)?(?P<name>\w+)\s*\((?P<params>[^)]*)\)"
    r"(?:\s*(?P<ret>[^\{]+))?\s*\{",
    re.MULTILINE,
)
_GO_TYPE_RE = re.compile(r"^type\s+(?P<name>\w+)\s+(?P<kind>struct|interface)\b", re.MULTILINE)
_GO_IMPORT_RE = re.compile(r'"(?P<mod>[^"]+)"')
_GO_CALL_RE = re.compile(r"\b(?P<name>\w+(?:\.\w+)*)\s*\(")
_GO_IMPORT_BLOCK_RE = re.compile(r'import\s*\(([^)]+)\)', re.DOTALL)
_GO_IMPORT_SINGLE_RE = re.compile(r'^import\s+"([^"]+)"', re.MULTILINE)


def _extract_go_native(source: str, file_path: str) -> tuple[list[dict], list[dict], list[dict]]:
    symbols: list[dict] = []
    entry_points: list[dict] = []
    edges: list[dict] = []

    import_modules: list[str] = []
    for block in _GO_IMPORT_BLOCK_RE.findall(source):
        import_modules.extend(_GO_IMPORT_RE.findall(block))
    import_modules.extend(_GO_IMPORT_SINGLE_RE.findall(source))
    import_modules = list(dict.fromkeys(import_modules))

    file_sym_id = file_path

    for m in import_modules:
        edges.append(_edge(from_=file_sym_id, to=m, edge_type="imports"))

    for m in _GO_TYPE_RE.finditer(source):
        name = m.group("name")
        kind_str = m.group("kind")
        sym_type = "interface" if kind_str == "interface" else "class"
        lineno = source[: m.start()].count("\n") + 1
        symbols.append(
            _sym(
                name=name,
                sym_type=sym_type,
                file_path=file_path,
                line_start=lineno,
                line_end=lineno,
                language="go",
                exported=name[0].isupper(),
            )
        )

    for m in _GO_FUNC_RE.finditer(source):
        recv = m.group("recv")
        name = m.group("name")
        params_raw = m.group("params") or ""
        ret_raw = (m.group("ret") or "").strip()
        lineno = source[: m.start()].count("\n") + 1

        params: list[dict] = []
        for part in [p.strip() for p in params_raw.split(",") if p.strip()]:
            tokens = part.split()
            if len(tokens) >= 2:
                params.append({"name": tokens[0], "type": " ".join(tokens[1:])})
            elif tokens:
                params.append({"name": tokens[0], "type": ""})

        brace_start = source.find("{", m.start())
        calls: list[str] = []
        end_line = lineno
        if brace_start != -1 and brace_start < m.start() + 500:
            depth = 0
            end_idx = brace_start
            for i, ch in enumerate(source[brace_start:], brace_start):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end_idx = i
                        break
            end_line = source[:end_idx].count("\n") + 1
            body = source[brace_start:end_idx]
            calls = list(
                dict.fromkeys(
                    c
                    for c in _GO_CALL_RE.findall(body)
                    if c not in {"if", "for", "switch", "select", "go", "defer", "return", "make", "len", "cap", "append", "copy", "delete", "new"}
                )
            )

        qual_name = f"{recv.split()[-1].lstrip('*')}.{name}" if recv else name
        sym_id = f"{file_path}::{qual_name}"
        sym_type = "method" if recv else "function"
        exported = name[0].isupper()

        sym = _sym(
            name=name,
            symbol_id=sym_id,
            sym_type=sym_type,
            file_path=file_path,
            line_start=lineno,
            line_end=end_line,
            language="go",
            exported=exported,
            parameters=params,
            return_type=ret_raw or None,
            calls=calls,
            imports=import_modules,
        )
        symbols.append(sym)

        for c in calls:
            edges.append(_edge(from_=sym_id, to=c, edge_type="calls"))

        if name == "main" and not recv:
            entry_points.append(_entry(symbol_id=sym_id, kind="main", file_path=file_path, line=lineno))

    return symbols, entry_points, edges


# ===========================================================================
# Native TypeScript / JavaScript extractor (regex-based lexical scan)
# ===========================================================================

_TS_FUNC_RE = re.compile(
    r"(?:^|(?<=\n))"
    r"(?P<export>export\s+)?"
    r"(?:async\s+)?"
    r"(?:function\*?\s+(?P<fname>\w+)|"
    r"(?:const|let|var)\s+(?P<aname>\w+)\s*=\s*(?:async\s+)?(?:function\*?\s*\w*|\([^)]*\)\s*=>|\w+\s*=>))",
    re.MULTILINE,
)
_TS_CLASS_RE = re.compile(
    r"(?P<export>export\s+)?(?:abstract\s+)?class\s+(?P<name>\w+)"
    r"(?:\s+extends\s+(?P<extends>\w+))?"
    r"(?:\s+implements\s+(?P<implements>[\w,\s]+))?",
    re.MULTILINE,
)
_TS_INTERFACE_RE = re.compile(
    r"(?P<export>export\s+)?interface\s+(?P<name>\w+)"
    r"(?:\s+extends\s+(?P<extends>[\w,\s]+))?",
    re.MULTILINE,
)
_TS_TYPE_RE = re.compile(r"(?P<export>export\s+)?type\s+(?P<name>\w+)\s*=", re.MULTILINE)
_TS_IMPORT_RE = re.compile(r"""(?:import|require)\s*\(?['"]([\w@/.\-]+)['"]\)?""")
_TS_CALL_RE = re.compile(r"\b(?P<name>[\w.]+)\s*\(")
_TS_ROUTE_RE = re.compile(
    r"(?:app|router)\s*\.\s*(?P<method>get|post|put|patch|delete|all|use)\s*\(",
    re.MULTILINE | re.IGNORECASE,
)


def _ts_end_line(source: str, brace_pos: int) -> int:
    depth = 0
    for i, ch in enumerate(source[brace_pos:], brace_pos):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[:i].count("\n") + 1
    return source.count("\n") + 1


def _extract_ts_native(source: str, file_path: str, language: str) -> tuple[list[dict], list[dict], list[dict]]:
    symbols: list[dict] = []
    entry_points: list[dict] = []
    edges: list[dict] = []

    import_modules = list(dict.fromkeys(_TS_IMPORT_RE.findall(source)))
    file_sym_id = file_path
    for m in import_modules:
        edges.append(_edge(from_=file_sym_id, to=m, edge_type="imports"))

    for m in _TS_INTERFACE_RE.finditer(source):
        name = m.group("name")
        lineno = source[: m.start()].count("\n") + 1
        sym_id = f"{file_path}::{name}"
        exported = bool(m.group("export"))
        symbols.append(
            _sym(
                name=name,
                sym_type="interface",
                file_path=file_path,
                line_start=lineno,
                line_end=lineno,
                language=language,
                exported=exported,
                imports=import_modules,
            )
        )
        extends_raw = m.group("extends") or ""
        for base in [b.strip() for b in extends_raw.split(",") if b.strip()]:
            edges.append(_edge(from_=sym_id, to=base, edge_type="extends"))

    for m in _TS_TYPE_RE.finditer(source):
        name = m.group("name")
        lineno = source[: m.start()].count("\n") + 1
        symbols.append(
            _sym(
                name=name,
                sym_type="type",
                file_path=file_path,
                line_start=lineno,
                line_end=lineno,
                language=language,
                exported=bool(m.group("export")),
                imports=import_modules,
            )
        )

    for m in _TS_CLASS_RE.finditer(source):
        name = m.group("name")
        lineno = source[: m.start()].count("\n") + 1
        sym_id = f"{file_path}::{name}"
        exported = bool(m.group("export"))
        symbols.append(
            _sym(
                name=name,
                sym_type="class",
                file_path=file_path,
                line_start=lineno,
                line_end=lineno,
                language=language,
                exported=exported,
                imports=import_modules,
            )
        )
        extends_raw = m.group("extends") or ""
        if extends_raw.strip():
            edges.append(_edge(from_=sym_id, to=extends_raw.strip(), edge_type="extends"))
        implements_raw = m.group("implements") or ""
        for iface in [i.strip() for i in implements_raw.split(",") if i.strip()]:
            edges.append(_edge(from_=sym_id, to=iface, edge_type="implements"))

    for m in _TS_FUNC_RE.finditer(source):
        name = m.group("fname") or m.group("aname")
        if not name:
            continue
        lineno = source[: m.start()].count("\n") + 1
        sym_id = f"{file_path}::{name}"
        exported = bool(m.group("export"))

        arrow_pos = source.find("=>", m.start())
        brace_pos = source.find("{", m.start())
        end_line = lineno
        calls: list[str] = []
        _skip = {"if", "for", "while", "switch", "catch", "function", "return", "typeof", "instanceof"}

        if brace_pos != -1 and (arrow_pos == -1 or brace_pos < arrow_pos + 100) and brace_pos < m.start() + 500:
            end_line = _ts_end_line(source, brace_pos)
            end_idx = brace_pos
            depth = 0
            for i, ch in enumerate(source[brace_pos:], brace_pos):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end_idx = i
                        break
            body = source[brace_pos:end_idx]
            calls = list(
                dict.fromkeys(
                    c for c in _TS_CALL_RE.findall(body) if c.split(".")[0] not in _skip
                )
            )
        elif arrow_pos != -1 and arrow_pos < m.start() + 200:
            # Concise arrow function
            next_semi = source.find(";", arrow_pos)
            next_nl = source.find("\n", arrow_pos)
            candidates = [idx for idx in (next_semi, next_nl) if idx != -1]
            end_idx = min(candidates) if candidates else len(source)
            body = source[arrow_pos + 2:end_idx]
            end_line = source[:end_idx].count("\n") + 1
            calls = list(
                dict.fromkeys(
                    c for c in _TS_CALL_RE.findall(body) if c.split(".")[0] not in _skip
                )
            )

        sym = _sym(
            name=name,
            sym_type="function",
            file_path=file_path,
            line_start=lineno,
            line_end=end_line,
            language=language,
            exported=exported,
            calls=calls,
            imports=import_modules,
        )
        symbols.append(sym)
        for c in calls:
            edges.append(_edge(from_=sym_id, to=c, edge_type="calls"))

        if name == "main":
            entry_points.append(_entry(symbol_id=sym_id, kind="main", file_path=file_path, line=lineno))

    for m in _TS_ROUTE_RE.finditer(source):
        lineno = source[: m.start()].count("\n") + 1
        http_method = m.group("method").lower()
        route_sym_id = f"{file_path}::route_{http_method}_{lineno}"
        entry_points.append(
            _entry(symbol_id=route_sym_id, kind="route", file_path=file_path, line=lineno)
        )

    return symbols, entry_points, edges


# ===========================================================================
# Tree-sitter engine
# ===========================================================================

def _extract_treesitter(
    source: str, file_path: str, language: str
) -> tuple[list[dict], list[dict], list[dict]] | None:
    if not _TREESITTER_AVAILABLE:
        return None
    try:
        from tree_sitter import Language, Parser

        lang_module_map = {
            "python": "tree_sitter_python",
            "go": "tree_sitter_go",
            "typescript": "tree_sitter_typescript",
            "javascript": "tree_sitter_javascript",
        }
        module_name = lang_module_map.get(language)
        if not module_name:
            return None

        lang_module = __import__(module_name)
        if hasattr(lang_module, "language"):
            ts_lang = Language(lang_module.language())
        elif hasattr(lang_module, "LANGUAGE"):
            ts_lang = Language(lang_module.LANGUAGE)
        else:
            return None

        parser = Parser(ts_lang)
        tree = parser.parse(source.encode())
        return None

    except Exception:
        return None


# ===========================================================================
# File dispatch & Filtering
# ===========================================================================

def _detect_language(file_path: str) -> Optional[str]:
    _, ext = os.path.splitext(file_path)
    return _EXT_TO_LANG.get(ext.lower())


def _extract_file(
    file_path: str, rel_path: str, language: str
) -> tuple[list[dict], list[dict], list[dict]]:
    try:
        with open(file_path, encoding="utf-8", errors="replace") as fh:
            source = fh.read()
    except OSError:
        return [], [], []

    result = _extract_treesitter(source, rel_path, language)
    if result is not None:
        return result

    if language == "python":
        return _extract_python_native(source, rel_path)
    elif language == "go":
        return _extract_go_native(source, rel_path)
    elif language in ("typescript", "javascript"):
        return _extract_ts_native(source, rel_path, language)

    return [], [], []


def _should_exclude_dir(dirname: str) -> bool:
    return dirname in _DEFAULT_EXCLUDE_DIRS


def _lang_from_filter(languages: Optional[list[str]]) -> Optional[set[str]]:
    if languages is None:
        return None
    return {lang.lower() for lang in languages}


def _matches_patterns(rel_path: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(os.path.basename(rel_path), pat):
            return True
    return False


# ===========================================================================
# Public async entry point
# ===========================================================================

async def extract_repo_ast_impl(
    repo_path: str,
    languages: Optional[list[str]] = None,
    include_patterns: Optional[list[str]] = None,
    exclude_patterns: Optional[list[str]] = None,
) -> dict:
    """
    Walk *repo_path* and extract a structured AST summary conforming to the
    ``extract_repo_ast`` JSON schema defined in ``tool-schemas.json``.
    """
    lang_filter: Optional[set[str]] = _lang_from_filter(languages)
    engine_used = "tree-sitter" if _TREESITTER_AVAILABLE else "native"

    all_symbols: list[dict] = []
    all_entry_points: list[dict] = []
    all_edges: list[dict] = []
    files_scanned = 0
    languages_found: set[str] = set()

    repo_path = os.path.abspath(repo_path)

    for dirpath, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = [
            d
            for d in dirnames
            if not _should_exclude_dir(d)
        ]

        for filename in filenames:
            abs_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(abs_path, repo_path).replace("\\", "/")

            language = _detect_language(filename)
            if language is None:
                continue

            if lang_filter is not None and language not in lang_filter:
                continue

            if include_patterns and not _matches_patterns(rel_path, include_patterns):
                continue

            if exclude_patterns and _matches_patterns(rel_path, exclude_patterns):
                continue

            files_scanned += 1
            languages_found.add(language)

            syms, eps, edgs = _extract_file(abs_path, rel_path, language)
            all_symbols.extend(syms)
            all_entry_points.extend(eps)
            all_edges.extend(edgs)

    seen_edges: set[tuple[str, str, str]] = set()
    unique_edges: list[dict] = []
    for e in all_edges:
        key = (e["from"], e["to"], e["type"])
        if key not in seen_edges:
            seen_edges.add(key)
            unique_edges.append(e)

    # Conforms strictly to tool-schemas.json with backward compatibility
    return {
        "repo_path": repo_path,
        "languages_detected": sorted(list(languages_found)),
        "files_parsed": files_scanned,
        "symbols": all_symbols,
        "entry_points": all_entry_points,
        "edges": unique_edges,
        "meta": {
            "files_scanned": files_scanned,
            "engine": engine_used,
            "languages_found": sorted(languages_found),
            "repo_path": repo_path,
        },
    }
