"""
model_builder.py
~~~~~~~~~~~~~~~~
Single source of truth for Architecture Storyteller 2.0.

Builds one deterministic `architecture-model@2` document from a repository and
derives every downstream artifact from it: the dossier, the interactive tree,
hover summaries, dependency and usages views. Nothing else scans the repository
independently, so numbers shown in the PDF and in the map cannot disagree.

Pipeline
--------
1. `ast_extractor` (py-ast-core) produces raw symbols / entry points / edges.
2. This module enriches them: real parents, qualified ids, docstrings, full-body
   complexity, factual capability flags, production/test classification.
3. Calls are *resolved* to concrete symbol ids (same-file first, then
   import-aware, then unique global), fixing the name-collision problem that
   made the old map merge every `get`/`run`/`search` into a single node.
4. Tarjan SCC clustering, pivotal ranking, entry-point flows and a module graph
   are derived from the resolved call graph.
5. Route / model / service detection is layered on top, source-tagged so the
   dossier can state how each fact was obtained.

The model is pure JSON-serialisable data. It never contains AI text.
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Optional

# ---------------------------------------------------------------------------
# Engine imports (py-ast-core sibling package)
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_PY_AST_CORE = _HERE.parent / "py-ast-core"
if str(_PY_AST_CORE) not in sys.path:
    sys.path.insert(0, str(_PY_AST_CORE))

from ast_extractor import extract_repo_ast_impl  # noqa: E402

if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from scan_filter import collect_files, is_test_path  # noqa: E402

SCHEMA = "storyteller/architecture-model@2"
SOURCE_EXTENSIONS = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".prisma")

_FUNC_KINDS = {"function", "method"}
_CLASS_KINDS = {"class", "interface", "type", "struct"}


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:20]


def run_sync(coro) -> Any:
    """Run an async coroutine from sync code, even inside a running loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    box: dict[str, Any] = {}

    def _runner() -> None:
        box["value"] = asyncio.run(coro)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    return box.get("value")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _git_fingerprint(root: Path) -> dict[str, Any]:
    def _git(*args: str) -> str:
        try:
            res = subprocess.run(
                ["git", *args], cwd=root, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=8,
            )
            return res.stdout.strip() if res.returncode == 0 else ""
        except Exception:
            return ""

    head = _git("rev-parse", "HEAD")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    # --untracked-files=no keeps this fast on repos with large untracked trees
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    return {"head": head, "branch": branch, "dirty": dirty,
            "hash": _sha(f"{head}|{branch}|{dirty}")}


def _git_file_history(root: Path, rel_files: Iterable[str], depth: int = 200) -> dict[str, dict[str, Any]]:
    """Per-file last-touch metadata from one bounded `git log` pass.

    File-level, not per-line blame: cheap on large repositories and honest in the
    dossier ("this file last changed in <commit>"), never invented per-symbol.
    """
    wanted = set(rel_files)
    if not wanted:
        return {}
    try:
        res = subprocess.run(
            ["git", "log", f"-n{depth}", "--pretty=format:@@%h|%aI|%s", "--name-only"],
            cwd=root, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=25,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if res.returncode != 0:
        return {}

    history: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    commit = date = subject = ""
    for line in res.stdout.splitlines():
        if line.startswith("@@"):
            parts = line[2:].split("|", 2)
            commit = parts[0]
            date = parts[1][:10] if len(parts) > 1 else ""
            subject = parts[2][:120] if len(parts) > 2 else ""
            continue
        rel = line.strip().replace("\\", "/")
        if rel and rel in wanted:
            counts[rel] = counts.get(rel, 0) + 1
            if rel not in history:
                history[rel] = {"last_commit": commit, "last_date": date,
                                "last_subject": subject, "commits": 0}
    for rel, count in counts.items():
        history[rel]["commits"] = count
    return history


# ---------------------------------------------------------------------------
# Symbol enrichment
# ---------------------------------------------------------------------------

_DYNAMIC_PATTERNS = (
    ("eval", r"\beval\s*\("),
    ("exec", r"\bexec\s*\("),
    ("importlib", r"importlib\.import_module|\b__import__\s*\("),
    ("reflection", r"\bgetattr\s*\(|\bsetattr\s*\(|\breflect\.|\bgetattr\b"),
    ("dynamic_require", r"\brequire\s*\(\s*[A-Za-z_$]|new\s+Function\s*\("),
    ("go_plugin", r"plugin\.Open"),
    ("namespace", r"(globals|locals|vars)\s*\("),
    ("subscript_dispatch", r"\[\s*[A-Za-z_][\w\s.\-]*\]\s*\("),
)

_FLAG_PATTERNS = (
    ("concurrency", r"\b(lock|mutex|semaphore|Atomic|threading|asyncio\.Lock|sync\.Mutex|sync\.RWMutex)\b|\bgo\s+func\b|\bchan\s"),
    ("retry", r"\b(retry|backoff|max_attempts|maxRetries)\b"),
    ("cache", r"\b(cache|memoiz|ttl|lru_cache)\b"),
    ("timeout", r"\b(timeout|deadline|circuit.?breaker)\b"),
    ("io", r"\b(requests\.|httpx|axios|fetch\s*\(|http\.Get|urllib|urlopen)\b"),
    ("db", r"(\.query\s*\(|\.execute\s*\(|session\.(add|commit|query)|prisma\.|SELECT\s+\w|INSERT\s+INTO)"),
    ("filesystem", r"\b(open\s*\(|Path\s*\(|read_text|write_text|os\.walk)\b"),
)

_COMPLEXITY_TOKENS = re.compile(
    r"\b(if|elif|else\s+if|for|while|case|catch|except|when|&&|\|\||and|or)\b"
)


def _strip_comments_for_flags(body: str, language: str) -> str:
    """Cheap comment stripping for flag/complexity scans (offsets irrelevant)."""
    if language == "python":
        body = re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', "", body)
        return re.sub(r"#[^\n]*", "", body)
    body = re.sub(r"/\*[\s\S]*?\*/", "", body)
    return re.sub(r"//[^\n]*", "", body)


def _capabilities(body: str, language: str) -> list[str]:
    flags: list[str] = []
    for name, pattern in _DYNAMIC_PATTERNS:
        if re.search(pattern, body):
            flags.append(f"dynamic:{name}")
    for name, pattern in _FLAG_PATTERNS:
        if re.search(pattern, body):
            flags.append(name)
    return flags


def _py_complexity(node: ast.AST) -> int:
    count = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp)):
            count += 1
        elif isinstance(child, ast.BoolOp):
            count += max(1, len(child.values) - 1)
        elif isinstance(child, ast.Match):
            count += len(child.cases)
    return min(count, 80)


def _lexical_complexity(body: str) -> int:
    return min(1 + len(_COMPLEXITY_TOKENS.findall(body)), 80)


def _leading_doc(lines: list[str], index: int) -> str:
    """Best-effort doc from the comment block directly above `index` (0-based)."""
    collected: list[str] = []
    i = index - 1
    while i >= 0:
        line = lines[i].strip()
        if not line:
            break
        if line.startswith("//") or line.startswith("*") or line.startswith("/*") or line.startswith("#"):
            collected.append(line)
            i -= 1
            continue
        break
    if not collected:
        return ""
    text = " ".join(reversed(collected))
    text = re.sub(r"^(//|/\*|\*+|#)\s*", "", text).strip()
    text = re.sub(r"\*/\s*$", "", text).strip()
    return text[:400]


def _python_docs(source: str) -> dict[tuple[str, int], str]:
    """(name, lineno) -> docstring first paragraph for every def/class."""
    docs: dict[tuple[str, int], str] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return docs
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node) or ""
            docs[(node.name, node.lineno)] = doc.strip()[:400]
    return docs


def _python_complexity(source: str) -> dict[tuple[str, int], int]:
    out: dict[tuple[str, int], int] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[(node.name, node.lineno)] = _py_complexity(node)
    return out


# ---------------------------------------------------------------------------
# TypeScript class-method augmentation
# ---------------------------------------------------------------------------

_TS_CLASS_METHOD_RE = re.compile(
    r"^(?P<indent>[ \t]+)"
    r"(?:(?:public|private|protected|static|async|readonly|override|abstract|declare)\s+)*"
    r"(?:get\s+|set\s+)?"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*\(",
)


def _brace_range(lines: list[str], start: int) -> int:
    """0-based line index of the closing brace of the block opening at/after `start`."""
    depth = 0
    began = False
    for i in range(start, len(lines)):
        for ch in lines[i]:
            if ch == "{":
                depth += 1
                began = True
            elif ch == "}":
                depth -= 1
                if began and depth <= 0:
                    return i
    return len(lines) - 1


def _ts_method_symbols(rel: str, source: str, existing_ids: set[str]) -> list[dict]:
    """Capture class methods, which the raw regex extractor misses."""
    lines = source.splitlines()
    found: list[dict] = []
    class_re = re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)")
    for idx, line in enumerate(lines):
        m = class_re.match(line)
        if not m:
            continue
        class_name = m.group(1)
        end = _brace_range(lines, idx)
        for j in range(idx + 1, end):
            mm = _TS_CLASS_METHOD_RE.match(lines[j])
            if not mm:
                continue
            name = mm.group("name")
            if name in {"constructor", "if", "for", "while", "switch", "return", "catch", "function"}:
                continue
            sym_id = f"{rel}::{class_name}.{name}"
            if sym_id in existing_ids:
                continue
            found.append({
                "id": sym_id,
                "type": "method",
                "name": name,
                "file_path": rel,
                "line_start": j + 1,
                "line_end": _brace_range(lines, j) + 1,
                "language": "typescript",
                "exported": False,
                "parameters": [],
                "return_type": None,
                "calls": [],
                "imports": [],
                "_parent_class": class_name,
                "_synthetic": True,
            })
    return found


# ---------------------------------------------------------------------------
# Tarjan SCC (iterative) - no recursion limits on large graphs
# ---------------------------------------------------------------------------

def _tarjan_sccs(graph: dict[str, list[str]]) -> list[list[str]]:
    index_counter = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    result: list[list[str]] = []

    for root in graph:
        if root in indices:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            node, child_i = work[-1]
            if child_i == 0:
                indices[node] = low[node] = index_counter
                index_counter += 1
                stack.append(node)
                on_stack.add(node)

            children = graph.get(node, [])
            if child_i < len(children):
                child = children[child_i]
                work[-1] = (node, child_i + 1)
                if child not in indices:
                    work.append((child, 0))
                elif child in on_stack:
                    low[node] = min(low[node], indices[child])
            else:
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
                if low[node] == indices[node]:
                    comp: list[str] = []
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        comp.append(w)
                        if w == node:
                            break
                    result.append(comp)
    return result


# ---------------------------------------------------------------------------
# Call & import resolution
# ---------------------------------------------------------------------------

def _qualified_tail(sym_id: str, name: str) -> str:
    return sym_id.split("::", 1)[1] if "::" in sym_id else name


def _parent_of(sym_id: str, name: str) -> Optional[str]:
    """Parent qualified name for `Class.method` ids, else None."""
    qual = _qualified_tail(sym_id, name)
    if "." in qual:
        return qual.rsplit(".", 1)[0]
    return None


def _build_name_index(symbols: list[dict]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for sym in symbols:
        index.setdefault(sym["name"], []).append(sym["id"])
    return index


def _anchor_indexes(symbols: list[dict]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Module stem -> files, and class/type name -> files.

    Used to resolve attribute calls such as `helpers.fetch_row(...)` or
    `StorytellerCache.exists(...)` without inventing edges for calls made on
    arbitrary objects.
    """
    module_files: dict[str, set[str]] = {}
    class_files: dict[str, set[str]] = {}
    for sym in symbols:
        stem = sym["file_path"].rsplit("/", 1)[-1]
        for ext in (".py", ".ts", ".tsx", ".js", ".jsx", ".go"):
            if stem.endswith(ext):
                stem = stem[: -len(ext)]
                break
        module_files.setdefault(stem, set()).add(sym["file_path"])
        if sym["kind"] in _CLASS_KINDS:
            class_files.setdefault(sym["name"], set()).add(sym["file_path"])
    return module_files, class_files


def _split_call(raw: str) -> tuple[str, str]:
    """Return (tail name, receiver) for a raw call expression.

    `helpers.fetch_row(x)` -> ("fetch_row", "helpers"); `run(x)` -> ("run", "").
    """
    base = raw.split("(")[0].strip()
    parts = [part.strip() for part in base.split(".") if part.strip()]
    if not parts:
        return "", ""
    tail = parts[-1]
    receiver = parts[-2] if len(parts) >= 2 else ""
    return tail, receiver


def _resolve_calls(
    symbols: list[dict],
    name_index: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Map symbol id -> resolved callee ids.

    Rules, in order:

    * `self.method()` / `this.method()` -> the unique method of the enclosing
      class, else a unique symbol of the same file.
    * `module.func()` / `ClassName.method()` -> a candidate whose file is the
      named module or class, so `helpers.fetch_row()` resolves and `dict.get()`
      does not.
    * bare `func()` -> free functions, classes and types only (a bare name can
      never be another class's method in these languages), preferring the same
      file, then a unique repository-wide match.

    Anything ambiguous stays unresolved rather than guessed, so the graph never
    invents an edge.
    """
    by_id = {s["id"]: s for s in symbols}
    module_files, class_files = _anchor_indexes(symbols)
    resolved: dict[str, list[str]] = {}

    for sym in symbols:
        hits: list[str] = []
        parent = sym.get("parent") or _parent_of(sym["id"], sym["name"])
        for raw in sym.get("raw_calls") or []:
            tail, receiver = _split_call(raw)
            candidates = name_index.get(tail) or []
            if not candidates:
                continue
            pick: Optional[str] = None

            if receiver in ("self", "cls", "this"):
                if parent:
                    same_class = [c for c in candidates if by_id[c].get("parent") == parent]
                    if len(same_class) == 1:
                        pick = same_class[0]
                if pick is None:
                    same_file = [c for c in candidates if by_id[c]["file_path"] == sym["file_path"]]
                    if len(same_file) == 1:
                        pick = same_file[0]
            elif receiver:
                anchor_files = module_files.get(receiver) or class_files.get(receiver) or set()
                anchored = [c for c in candidates if by_id[c]["file_path"] in anchor_files]
                if len(anchored) == 1:
                    pick = anchored[0]
            else:
                callable_by_name = [c for c in candidates if by_id[c]["kind"] != "method"]
                same_file = [c for c in callable_by_name if by_id[c]["file_path"] == sym["file_path"]]
                if len(same_file) == 1:
                    pick = same_file[0]
                elif len(callable_by_name) == 1:
                    pick = callable_by_name[0]

            if pick is not None and pick != sym["id"] and pick not in hits:
                hits.append(pick)
        resolved[sym["id"]] = hits
    return resolved


def _resolve_import_target_uncached(root: Path, import_path: str, language: str) -> Optional[str]:
    """Best-effort import -> repository file mapping (module graph edges only)."""
    if not import_path:
        return None
    if language in ("typescript", "javascript"):
        if not import_path.startswith("."):
            return None
        base = root / import_path
        for suffix in ("", ".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx", "/index.js"):
            candidate = Path(str(base) + suffix)
            if candidate.is_file():
                return _rel(root, candidate)
        return None
    if language == "python":
        module = import_path.split(":", 1)[0].strip(".")
        if not module:
            return None
        parts = module.split(".")
        candidate = root.joinpath(*parts[:-1], parts[-1] + ".py")
        if candidate.is_file():
            return _rel(root, candidate)
        package = root.joinpath(*parts, "__init__.py")
        if package.is_file():
            return _rel(root, package)
        # sys.path-style imports in monorepos (`from ast_extractor import ...`)
        # do not map onto the repository layout. Fall back to a unique module
        # stem anywhere in the tree: only unambiguous matches become edges.
        stem = parts[-1]
        matches = [rel for rel in _FILE_INDEX if rel.endswith(f"/{stem}.py") or rel == f"{stem}.py"]
        if len(matches) == 1:
            return matches[0]
        return None
    if language == "go":
        tail = "/".join(import_path.split("/")[-2:]) if import_path.count("/") >= 1 else import_path
        for rel in _FILE_INDEX:
            if rel.endswith(".go") and tail and tail in rel:
                return rel
        return None
    return None


# ---------------------------------------------------------------------------
# Symbol enrichment
# ---------------------------------------------------------------------------

_KIND_MAP = {
    "function": "function",
    "method": "method",
    "class": "class",
    "interface": "interface",
    "type": "type",
    "variable": "variable",
    "const": "const",
    "struct": "class",
}


def _enrich_symbols(
    root: Path,
    raw_symbols: list[dict],
    contents: dict[str, str],
    ts_synthetic: dict[str, list[dict]],
) -> list[dict]:
    docs_cache: dict[str, dict[tuple[str, int], str]] = {}
    cx_cache: dict[str, dict[tuple[str, int], int]] = {}

    for rel, text in contents.items():
        if rel.endswith(".py"):
            docs_cache[rel] = _python_docs(text)
            cx_cache[rel] = _python_complexity(text)

    enriched: list[dict] = []
    seen_ids: set[str] = set()

    def _convert(raw: dict, synthetic: bool = False) -> Optional[dict]:
        rel = raw["file_path"]
        text = contents.get(rel, "")
        lines = text.splitlines()
        start = max(1, int(raw.get("line_start") or 1))
        end = min(max(start, int(raw.get("line_end") or start)), max(1, len(lines)))
        body = "\n".join(lines[start - 1:end]) if lines else ""
        name = raw.get("name") or ""
        if not name:
            return None
        kind = _KIND_MAP.get(raw.get("type", ""), raw.get("type", "function"))
        language = raw.get("language", "")
        if language == "javascript":
            language = "javascript"

        if language == "python":
            doc = docs_cache.get(rel, {}).get((name, start), "")
            complexity = cx_cache.get(rel, {}).get((name, start), _lexical_complexity(body))
        else:
            doc = _leading_doc(lines, start - 1)
            complexity = _lexical_complexity(body)

        clean_body = _strip_comments_for_flags(body, language)
        flags = _capabilities(clean_body, language)

        parent = raw.get("_parent_class") or _parent_of(raw["id"], name)
        sym = {
            "id": raw["id"],
            "name": name,
            "qualified": raw["id"].split("::", 1)[1] if "::" in raw["id"] else name,
            "kind": kind,
            "file_path": rel,
            "line_start": start,
            "line_end": end,
            "language": language,
            "parent": parent,
            "children": [],
            "exported": bool(raw.get("exported")),
            "private": name.startswith("_"),
            "is_test": is_test_path(root / rel),
            "doc": doc,
            "complexity": min(int(complexity), 80),
            "flags": flags,
            "parameters": raw.get("parameters") or [],
            "returns": raw.get("return_type") or "",
            "raw_calls": [c for c in (raw.get("calls") or [])][:80],
            "calls": [],
            "callers": [],
            "imports": [i for i in (raw.get("imports") or [])][:60],
            "hash": _sha(body),
            "deps_hash": "",
            "source": "regex" if synthetic or raw.get("_synthetic") else "ast",
        }
        return sym

    for raw in raw_symbols:
        sym = _convert(raw)
        if sym and sym["id"] not in seen_ids:
            seen_ids.add(sym["id"])
            enriched.append(sym)

    for rel, extra in ts_synthetic.items():
        for raw in extra:
            if raw["id"] in seen_ids:
                continue
            sym = _convert(raw, synthetic=True)
            if sym:
                seen_ids.add(sym["id"])
                enriched.append(sym)

    return enriched


# ---------------------------------------------------------------------------
# Derived data: call graph, clusters, pivotal ranking, flows, module graph
# ---------------------------------------------------------------------------

def _finalise_call_graph(symbols: list[dict], resolved: dict[str, list[str]]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    callers: dict[str, list[str]] = {s["id"]: [] for s in symbols}
    for sym in symbols:
        hits = resolved.get(sym["id"], [])
        sym["calls"] = hits
        sym["deps_hash"] = _sha("|".join(sorted(hits)) + "|" + "|".join(sorted(sym.get("raw_calls") or [])))
        for target in hits:
            callers.setdefault(target, []).append(sym["id"])
    for sym in symbols:
        sym["callers"] = sorted(set(callers.get(sym["id"], [])))
    for sym in symbols:
        parent = sym.get("parent")
        if parent:
            for candidate in symbols:
                if candidate["file_path"] == sym["file_path"] and candidate["qualified"] == parent:
                    candidate["children"].append(sym["id"])
                    break
    return resolved, callers


def _clusters(symbols: list[dict]) -> dict[str, Any]:
    """Tarjan SCC over resolved call edges between functions/methods."""
    funcs = [s for s in symbols if s["kind"] in _FUNC_KINDS]
    ids = {s["id"] for s in funcs}
    graph: dict[str, list[str]] = {}
    for sym in funcs:
        graph[sym["id"]] = sorted({c for c in sym["calls"] if c in ids})

    sccs = _tarjan_sccs(graph)
    cyclic: list[str] = []
    for comp in sccs:
        if len(comp) > 1:
            cyclic.extend(comp)
        elif comp and graph.get(comp[0], []) == [comp[0]]:
            cyclic.append(comp[0])

    dynamic = [
        s["id"] for s in funcs
        if any(f.startswith("dynamic:") for f in s["flags"])
    ]
    independent = [
        s["id"] for s in funcs
        if not graph.get(s["id"]) and s["id"] not in set(cyclic) and s["id"] not in set(dynamic)
    ]

    groups = []
    for comp in sccs:
        if len(comp) > 1:
            groups.append(sorted(comp, key=lambda i: -len(graph.get(i, []))))
    groups.sort(key=len, reverse=True)

    return {
        "independent": independent,
        "cyclic": sorted(set(cyclic)),
        "dynamic": sorted(set(dynamic)),
        "sccs": groups[:40],
        "counts": {
            "independent": len(independent),
            "cyclic": len(set(cyclic)),
            "dynamic": len(set(dynamic)),
        },
    }


def _pivotal(symbols: list[dict], limit: int = 200) -> list[dict]:
    by_id = {s["id"]: s for s in symbols}
    scored: list[dict] = []
    for sym in symbols:
        if sym["kind"] not in _FUNC_KINDS:
            continue
        fan_in = len(sym["callers"])
        fan_out = len(sym["calls"])
        cross_file = len({by_id[c]["file_path"] for c in sym["callers"] if c in by_id and by_id[c]["file_path"] != sym["file_path"]})
        score = cross_file * 3 + fan_in * 0.5 + min(sym["complexity"], 15) + (2 if sym["flags"] else 0)
        scored.append({
            "id": sym["id"],
            "score": round(score, 2),
            "fan_in": fan_in,
            "fan_out": fan_out,
            "cross_file_callers": cross_file,
            "complexity": sym["complexity"],
        })
    scored.sort(key=lambda r: (-r["score"], r["id"]))
    return scored[:limit]


def _flows(entry_points: list[dict], symbols: list[dict], max_flows: int = 12, depth: int = 4) -> list[dict]:
    by_id = {s["id"]: s for s in symbols}
    flows: list[dict] = []
    seen: set[tuple[str, ...]] = set()

    entries = list(entry_points)
    if not any(by_id.get(e.get("symbol_id", "")) for e in entries):
        hubs = sorted(
            [s for s in symbols if s["kind"] in _FUNC_KINDS and s["calls"]],
            key=lambda s: (-len(s["calls"]), -len(s["callers"]), s["id"]),
        )[:8]
        entries = [{"symbol_id": s["id"], "kind": "hub", "file_path": s["file_path"]} for s in hubs]

    for entry in entries:
        target = by_id.get(entry.get("symbol_id", ""))
        if not target or target["kind"] not in _FUNC_KINDS:
            continue
        chains: list[list[dict]] = []
        stack: list[tuple[str, list[dict], set[str]]] = [(target["id"], [target], {target["id"]})]
        while stack:
            node_id, chain, visited = stack.pop()
            node = by_id.get(node_id)
            if not node:
                continue
            if len(chain) >= depth or not node["calls"]:
                chains.append(chain)
                continue
            progressed = False
            ranked = sorted(
                [c for c in node["calls"] if c in by_id],
                key=lambda c: (-len(by_id[c]["callers"]), c),
            )[:2]
            for nxt in ranked:
                if nxt in visited:
                    continue
                progressed = True
                stack.append((nxt, chain + [by_id[nxt]], visited | {nxt}))
            if not progressed:
                chains.append(chain)
        chains.sort(key=len, reverse=True)
        for chain in chains[:2]:
            key = tuple(n["id"] for n in chain)
            if key in seen or len(chain) < 2:
                continue
            seen.add(key)
            flows.append({
                "entry": chain[0]["name"],
                "entry_id": chain[0]["id"],
                "kind": entry.get("kind", "entry"),
                "file": chain[0]["file_path"],
                "chain": [
                    {"id": n["id"], "name": n["name"], "qualified": n["qualified"],
                     "file": n["file_path"], "line": n["line_start"], "language": n["language"]}
                    for n in chain
                ],
            })
            if len(flows) >= max_flows:
                return flows
    return flows


def _module_key(rel: str) -> str:
    parts = rel.split("/")
    if len(parts) >= 3 and parts[0] in ("tools", "packages", "apps", "services"):
        return "/".join(parts[:2])
    if len(parts) >= 2:
        return parts[0]
    return "root"


def _module_graph(
    symbols: list[dict],
    resolved: dict[str, list[str]],
    clusters: dict[str, Any],
) -> dict[str, Any]:
    by_id = {s["id"]: s for s in symbols}
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], int] = {}
    cyclic = set(clusters.get("cyclic") or [])

    for sym in symbols:
        mod = _module_key(sym["file_path"])
        node = nodes.setdefault(mod, {
            "id": mod, "label": mod, "symbols": 0, "files": 0,
            "languages": [], "has_cycle": False, "dynamic": 0,
        })
        node["symbols"] += 1
        if sym["language"] and sym["language"] not in node["languages"]:
            node["languages"].append(sym["language"])
        if sym["id"] in cyclic:
            node["has_cycle"] = True
        if any(f.startswith("dynamic:") for f in sym["flags"]):
            node["dynamic"] += 1

    files_per_mod: dict[str, set[str]] = {}
    for sym in symbols:
        files_per_mod.setdefault(_module_key(sym["file_path"]), set()).add(sym["file_path"])
    for mod, files in files_per_mod.items():
        nodes[mod]["files"] = len(files)

    for sym in symbols:
        src_mod = _module_key(sym["file_path"])
        for target in sym["calls"]:
            tgt = by_id.get(target)
            if not tgt:
                continue
            tgt_mod = _module_key(tgt["file_path"])
            if tgt_mod == src_mod:
                continue
            key = (src_mod, tgt_mod, "calls")
            edges[key] = edges.get(key, 0) + 1
        for imp in sym.get("imports") or []:
            src_file = sym["file_path"]
            target_file = _resolve_import_target(_MODEL_ROOT_HINT, imp, sym["language"]) if _MODEL_ROOT_HINT else None
            if not target_file or target_file == src_file:
                continue
            tgt_mod = _module_key(target_file)
            if tgt_mod == src_mod:
                continue
            key = (src_mod, tgt_mod, "imports")
            edges[key] = edges.get(key, 0) + 1

    return {
        "nodes": sorted(nodes.values(), key=lambda n: (-n["symbols"], n["id"])),
        "edges": [
            {"from": a, "to": b, "type": t, "weight": w}
            for (a, b, t), w in sorted(edges.items(), key=lambda kv: -kv[1])
        ][:400],
    }


_MODEL_ROOT_HINT: Optional[Path] = None
_FILE_INDEX: list[str] = []
_IMPORT_CACHE: dict[tuple[str, str], Optional[str]] = {}


def _resolve_import_target(root: Path, import_path: str, language: str) -> Optional[str]:
    """Memoised wrapper; the project has only a few dozen distinct imports."""
    key = (language, import_path)
    if key not in _IMPORT_CACHE:
        _IMPORT_CACHE[key] = _resolve_import_target_uncached(root, import_path, language)
    return _IMPORT_CACHE[key]


# ---------------------------------------------------------------------------
# Layer entities (routes / models / services) - heuristic projections
# ---------------------------------------------------------------------------

def _layer_entities(root: Path, prod_files: list[str], cap: int = 200) -> dict[str, Any]:
    """Route/model/service detection, source-tagged.

    These are regex heuristics layered on top of the AST model. They enrich the
    narrative but are never used for counts that the dossier presents as
    structurally certain.
    """
    out: dict[str, Any] = {"routes": [], "models": [], "services": [], "sources": {}}

    def _run(key: str, module: str, class_name: str) -> None:
        try:
            mod = __import__(module, fromlist=[class_name])
            crawler = getattr(mod, class_name)(str(root))
            items = crawler.crawl(prod_files)
            out[key] = [item.to_dict() if hasattr(item, "to_dict") else item for item in items][:cap]
            out["sources"][key] = "regex-heuristic"
        except Exception as exc:  # crawler unavailable or parse failure
            out["sources"][key] = f"unavailable ({type(exc).__name__})"

    _run("routes", "route_crawler", "RouteCrawler")
    _run("models", "model_crawler", "ModelCrawler")
    _run("services", "service_crawler", "ServiceCrawler")
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_model(
    repo: str | Path,
    languages: Optional[list[str]] = None,
    include: Optional[list[str]] = None,
    exclude: Optional[list[str]] = None,
    detect_layers: bool = True,
    max_symbols: int = 20000,
) -> dict[str, Any]:
    """Build the architecture model for `repo`.

    Deterministic: same tree in, same model out (timestamps and git fingerprint
    aside). No AI, no network, no writes.
    """
    global _MODEL_ROOT_HINT
    started = time.time()
    root = Path(repo).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Not a directory: {root}")
    _MODEL_ROOT_HINT = root

    raw = run_sync(extract_repo_ast_impl(
        str(root),
        languages=languages,
        include_patterns=include,
        exclude_patterns=exclude,
    ))

    files = collect_files(root, SOURCE_EXTENSIONS, include_tests=True, include_engine_source=True)
    contents = {_rel(root, p): _read(p) for p in files}
    _FILE_INDEX.clear()
    _FILE_INDEX.extend(sorted(contents))
    _IMPORT_CACHE.clear()
    prod_rel = {rel for rel in contents if not is_test_path(root / rel)}

    existing_ids = {s["id"] for s in raw.get("symbols", [])}
    ts_synth: dict[str, list[dict]] = {}
    for rel, text in contents.items():
        if rel.endswith((".ts", ".tsx", ".js", ".jsx")):
            extra = _ts_method_symbols(rel, text, existing_ids)
            if extra:
                ts_synth[rel] = extra
                existing_ids.update(e["id"] for e in extra)

    symbols = _enrich_symbols(root, raw.get("symbols", []), contents, ts_synth)
    if len(symbols) > max_symbols:
        symbols = sorted(symbols, key=lambda s: (s["is_test"], -len(s["raw_calls"])))[:max_symbols]

    name_index = _build_name_index(symbols)
    resolved = _resolve_calls(symbols, name_index)
    _finalise_call_graph(symbols, resolved)

    clusters = _clusters(symbols)
    pivotal = _pivotal(symbols)
    flows = _flows(raw.get("entry_points") or [], symbols)
    module_graph = _module_graph(symbols, resolved, clusters)

    if detect_layers:
        prod_files = [str(root / rel) for rel in sorted(prod_rel)]
        layers = _layer_entities(root, prod_files)
    else:
        layers = {"routes": [], "models": [], "services": [], "sources": {}}

    entry_points = []
    by_id = {s["id"]: s for s in symbols}
    for entry in raw.get("entry_points") or []:
        target = by_id.get(entry.get("symbol_id", ""))
        entry_points.append({
            **entry,
            "name": target["name"] if target else entry.get("symbol_id", "").split("::")[-1],
            "resolved": bool(target),
            "language": target["language"] if target else "",
        })
    return _assemble(root, raw, symbols, contents, prod_rel, resolved,
                     clusters, pivotal, flows, module_graph, layers,
                     entry_points, started)


_LANG_BY_EXT = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".go": "go", ".prisma": "prisma",
}


def _assemble(
    root: Path,
    raw: dict,
    symbols: list[dict],
    contents: dict[str, str],
    prod_rel: set[str],
    resolved: dict[str, list[str]],
    clusters: dict,
    pivotal: list[dict],
    flows: list[dict],
    module_graph: dict,
    layers: dict,
    entry_points: list[dict],
    started: float,
) -> dict[str, Any]:
    from datetime import datetime, timezone

    per_file: dict[str, int] = {}
    for sym in symbols:
        per_file[sym["file_path"]] = per_file.get(sym["file_path"], 0) + 1

    history = _git_file_history(root, sorted(contents))

    files_meta = []
    for rel in sorted(contents):
        ext = "." + rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
        files_meta.append({
            "path": rel,
            "language": _LANG_BY_EXT.get(ext, ""),
            "module": _module_key(rel),
            "loc": contents[rel].count("\n") + 1,
            "is_test": is_test_path(root / rel),
            "is_production": rel in prod_rel,
            "symbols": per_file.get(rel, 0),
            "git": history.get(rel, {}),
        })

    funcs = [s for s in symbols if s["kind"] in _FUNC_KINDS]
    prod_funcs = [s for s in funcs if not s["is_test"]]
    raw_call_total = sum(len(s["raw_calls"]) for s in funcs)
    resolved_total = sum(len(s["calls"]) for s in funcs)
    languages = sorted({s["language"] for s in symbols if s["language"]})

    stats = {
        "files": len(files_meta),
        "production_files": len(prod_rel),
        "symbols": len(symbols),
        "functions": len([s for s in symbols if s["kind"] == "function"]),
        "methods": len([s for s in symbols if s["kind"] == "method"]),
        "classes": len([s for s in symbols if s["kind"] in _CLASS_KINDS]),
        "production_functions": len(prod_funcs),
        "test_functions": len([s for s in funcs if s["is_test"]]),
        "resolved_call_edges": resolved_total,
        "unresolved_call_names": max(0, raw_call_total - resolved_total),
        "entry_points": len(entry_points),
        "modules": len(module_graph.get("nodes", [])),
        "routes": len(layers.get("routes", [])),
        "models": len(layers.get("models", [])),
        "services": len(layers.get("services", [])),
        "clusters": clusters.get("counts", {}),
        "languages": languages,
        "files_with_history": sum(1 for m in files_meta if (m.get("git") or {}).get("last_commit")),
    }

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": {
            "root": str(root),
            "name": root.name,
            "fingerprint": _git_fingerprint(root),
        },
        "meta": {
            "engine": raw.get("meta", {}).get("engine", "native"),
            "files_scanned": raw.get("meta", {}).get("files_scanned", len(files_meta)),
            "languages": raw.get("meta", {}).get("languages_found", languages),
            "duration_ms": int((time.time() - started) * 1000),
            "detect_layers": bool(layers.get("sources")),
        },
        "files": files_meta,
        "symbols": symbols,
        "entry_points": entry_points,
        "layers": layers,
        "clusters": clusters,
        "pivotal": pivotal,
        "flows": flows,
        "module_graph": module_graph,
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# Downstream payload helpers
# ---------------------------------------------------------------------------

def read_symbol_source(root: str | Path, symbol: dict, pad: int = 0, max_lines: int = 120) -> str:
    """Read a symbol's source straight from disk (never stored in the model)."""
    path = Path(root) / symbol.get("file_path", "")
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    start = max(1, int(symbol.get("line_start") or 1) - pad)
    end = min(len(lines), int(symbol.get("line_end") or start) + pad)
    end = min(end, start + max_lines - 1)
    return "\n".join(lines[start - 1:end])


def tree_payload(model: dict[str, Any], max_calls: int = 40, max_doc: int = 200) -> dict[str, Any]:
    """Compact model for the webview tree/graph (link lists capped)."""
    symbols = []
    for sym in model.get("symbols", []):
        symbols.append({
            "id": sym["id"],
            "name": sym["name"],
            "qualified": sym["qualified"],
            "kind": sym["kind"],
            "file": sym["file_path"],
            "line": sym["line_start"],
            "end": sym["line_end"],
            "parent": sym.get("parent"),
            "children": sym.get("children", [])[:max_calls],
            "complexity": sym.get("complexity", 1),
            "flags": sym.get("flags", [])[:6],
            "calls": sym.get("calls", [])[:max_calls],
            "callers": sym.get("callers", [])[:max_calls],
            "doc": (sym.get("doc") or "")[:max_doc],
            "is_test": sym.get("is_test", False),
            "private": sym.get("private", False),
            "exported": sym.get("exported", False),
            "language": sym.get("language", ""),
            "hash": sym.get("hash", ""),
        })
    return {
        "schema": model.get("schema"),
        "generated_at": model.get("generated_at"),
        "repo": model.get("repo"),
        "meta": model.get("meta"),
        "stats": model.get("stats"),
        "files": model.get("files", []),
        "symbols": symbols,
        "entry_points": model.get("entry_points", []),
        "clusters": model.get("clusters", {}),
        "pivotal": model.get("pivotal", []),
        "flows": model.get("flows", []),
        "module_graph": model.get("module_graph", {}),
    }


def manifest_from_model(model: dict[str, Any]) -> dict[str, Any]:
    """Content-addressed manifest used by the insight cache to detect deltas."""
    symbols: dict[str, dict[str, Any]] = {}
    for sym in model.get("symbols", []):
        if sym["kind"] not in _FUNC_KINDS and sym["kind"] not in _CLASS_KINDS:
            continue
        symbols[sym["id"]] = {
            "hash": sym.get("hash", ""),
            "deps_hash": sym.get("deps_hash", ""),
            "file": sym["file_path"],
            "kind": sym["kind"],
            "name": sym["name"],
            "qualified": sym["qualified"],
            "is_test": sym.get("is_test", False),
        }
    return {
        "schema": "storyteller/manifest@1",
        "fingerprint": (model.get("repo", {}).get("fingerprint") or {}).get("hash", ""),
        "generated_at": model.get("generated_at", ""),
        "stats": {
            "symbols": len(symbols),
            "files": len(model.get("files", [])),
            **(model.get("stats") or {}),
        },
        "symbols": symbols,
    }
