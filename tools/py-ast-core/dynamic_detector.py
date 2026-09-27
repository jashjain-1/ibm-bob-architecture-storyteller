"""
dynamic_detector.py — Static heuristic detection of dynamic invocation patterns.

Implements: detect_dynamic_invocations tool from tool-schemas.json
Supports:   Go, Python, TypeScript, JavaScript

Detects dynamic patterns:
  - reflection:       getattr(), reflect.ValueOf(), reflect.MethodByName(), Reflect.get()
  - dynamic_import:   importlib.import_module(), require(variable), dynamic import()
  - eval:             eval(), exec(), new Function()
  - event_emitter:    EventEmitter.on(), EventEmitter.emit(), addEventListener()
  - env_conditional:  os.environ, os.getenv(), os.Getenv(), process.env
  - string_dispatch:  string-based method lookup, config-driven routing
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any, Optional

ALL_PATTERNS = [
    "reflection",
    "dynamic_import",
    "eval",
    "event_emitter",
    "env_conditional",
    "string_dispatch",
]

# Regex definitions for pattern heuristics across languages
PATTERN_REGEXES = {
    "reflection": [
        (re.compile(r"\bgetattr\s*\("), "Python dynamic getattr lookup", 0.9),
        (re.compile(r"\bsetattr\s*\("), "Python dynamic setattr mutation", 0.9),
        (re.compile(r"\bhasattr\s*\("), "Python reflection hasattr check", 0.8),
        (re.compile(r"\bdelattr\s*\("), "Python reflection delattr", 0.8),
        (re.compile(r"\breflect\.ValueOf\s*\("), "Go reflect.ValueOf introspection", 0.95),
        (re.compile(r"\breflect\.TypeOf\s*\("), "Go reflect.TypeOf introspection", 0.95),
        (re.compile(r"\.MethodByName\s*\("), "Go dynamic method lookup via reflection", 0.95),
        (re.compile(r"\.FieldByName\s*\("), "Go dynamic field lookup via reflection", 0.95),
        (re.compile(r"\bReflect\.(?:get|set|apply|construct)\s*\("), "JavaScript / TypeScript Reflect API call", 0.9),
    ],
    "dynamic_import": [
        (re.compile(r"\bimportlib\.import_module\s*\("), "Python importlib dynamic module loading", 0.95),
        (re.compile(r"\b__import__\s*\("), "Python __import__ built-in dynamic load", 0.95),
        (re.compile(r"\bimportlib\."), "Python importlib subsystem invocation", 0.85),
        (re.compile(r"\brequire\s*\(\s*(?!['\"][^'\"]+['\"]\s*\))"), "Node.js dynamic require with variable argument", 0.9),
        (re.compile(r"\bimport\s*\(\s*(?!['\"][^'\"]+['\"]\s*\))"), "Dynamic import() with expression argument", 0.85),
        (re.compile(r"\bplugin\.Open\s*\("), "Go dynamic plugin loading", 0.95),
    ],
    "eval": [
        (re.compile(r"\beval\s*\("), "Runtime eval() code execution", 0.95),
        (re.compile(r"\bexec\s*\("), "Python exec() arbitrary code execution", 0.95),
        (re.compile(r"\bnew\s+Function\s*\("), "JavaScript new Function constructor invocation", 0.95),
        (re.compile(r"\bcompile\s*\([^)]*['\"]exec['\"]"), "Python compile with mode='exec'", 0.85),
    ],
    "event_emitter": [
        (re.compile(r"\.(?:on|once)\s*\(\s*['\"][^'\"]+['\"]"), "Event emitter listener subscription", 0.85),
        (re.compile(r"\.emit\s*\(\s*['\"][^'\"]+['\"]"), "Event emitter notification dispatch", 0.85),
        (re.compile(r"\.addEventListener\s*\("), "DOM / EventTarget listener registration", 0.85),
        (re.compile(r"\.removeEventListener\s*\("), "DOM / EventTarget listener removal", 0.75),
        (re.compile(r"\.addListener\s*\("), "Node.js EventEmitter addListener", 0.85),
    ],
    "env_conditional": [
        (re.compile(r"\bos\.environ(?:\.get)?\s*[\[\(]"), "Python environment variable lookup", 0.9),
        (re.compile(r"\bos\.getenv\s*\("), "Python os.getenv invocation", 0.9),
        (re.compile(r"\bos\.Getenv\s*\("), "Go os.Getenv environment lookup", 0.9),
        (re.compile(r"\bos\.LookupEnv\s*\("), "Go os.LookupEnv environment check", 0.9),
        (re.compile(r"\bprocess\.env\.[A-Za-z0-9_]+"), "Node.js process.env property access", 0.9),
        (re.compile(r"\bprocess\.env\["), "Node.js process.env dynamic access", 0.9),
    ],
    "string_dispatch": [
        (re.compile(r"(?:actions|handlers|routes|commands|dispatch_table)\[[^\]]+\]\s*\("), "Table-driven string dispatch function call", 0.85),
        (re.compile(r"\bgetattr\s*\([^,]+,\s*[A-Za-z0-9_]+\s*\)\s*\("), "Dynamic getattr invoked immediately as function", 0.95),
    ],
}


class PythonASTDynamicDetector(ast.NodeVisitor):
    """Deep AST-level scanner for Python dynamic patterns."""

    def __init__(self, file_path: str, target_symbol_id: Optional[str] = None):
        self.file_path = file_path.replace("\\", "/")
        self.target_symbol_id = target_symbol_id
        self.findings: list[dict[str, Any]] = []
        self.scope_stack: list[str] = []

    def _current_symbol(self) -> str:
        mod_prefix = self.file_path.replace("/", ".").rstrip(".py")
        if self.scope_stack:
            return f"{mod_prefix}.{'.'.join(self.scope_stack)}"
        return mod_prefix

    def _matches_symbol(self) -> bool:
        if not self.target_symbol_id:
            return True
        curr = self._current_symbol()
        return curr == self.target_symbol_id or self.target_symbol_id.startswith(curr)

    def visit_ClassDef(self, node: ast.ClassDef):
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call):
        if not self._matches_symbol():
            self.generic_visit(node)
            return

        curr_sym = self._current_symbol()
        func_name = None

        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr

        # 1. Reflection: getattr / setattr / hasattr
        if func_name in {"getattr", "setattr", "hasattr", "delattr"}:
            desc = f"Python built-in '{func_name}()' dynamic attribute reflection"
            self.findings.append({
                "pattern_type": "reflection",
                "file_path": self.file_path,
                "line_number": node.lineno,
                "symbol_id": curr_sym,
                "confidence": 0.95,
                "description": desc,
            })

        # 2. Dynamic import: importlib.import_module or __import__
        if func_name in {"import_module", "__import__"}:
            self.findings.append({
                "pattern_type": "dynamic_import",
                "file_path": self.file_path,
                "line_number": node.lineno,
                "symbol_id": curr_sym,
                "confidence": 0.95,
                "description": f"Dynamic module loader '{func_name}()'",
            })

        # 3. Eval / Exec
        if func_name in {"eval", "exec"}:
            self.findings.append({
                "pattern_type": "eval",
                "file_path": self.file_path,
                "line_number": node.lineno,
                "symbol_id": curr_sym,
                "confidence": 0.95,
                "description": f"Arbitrary runtime code execution via '{func_name}()'",
            })

        # 4. Env conditional: os.getenv
        if func_name in {"getenv"}:
            self.findings.append({
                "pattern_type": "env_conditional",
                "file_path": self.file_path,
                "line_number": node.lineno,
                "symbol_id": curr_sym,
                "confidence": 0.9,
                "description": "Environment variable retrieval via os.getenv()",
            })

        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript):
        if not self._matches_symbol():
            self.generic_visit(node)
            return

        curr_sym = self._current_symbol()

        # Check os.environ[...]
        if isinstance(node.value, ast.Attribute) and node.value.attr == "environ":
            self.findings.append({
                "pattern_type": "env_conditional",
                "file_path": self.file_path,
                "line_number": node.lineno,
                "symbol_id": curr_sym,
                "confidence": 0.95,
                "description": "Environment variable lookup via os.environ index",
            })

        self.generic_visit(node)


def scan_file_heuristics(
    file_path: str,
    code: str,
    selected_patterns: list[str],
    symbol_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Line-by-line regex scanner for dynamic patterns across languages."""
    norm_path = file_path.replace("\\", "/")
    results: list[dict[str, Any]] = []
    lines = code.splitlines()

    for line_idx, line in enumerate(lines, 1):
        clean_line = line.strip()
        if clean_line.startswith(("//", "#", "/*", "*")):
            continue

        for pat_type in selected_patterns:
            for regex, desc, conf in PATTERN_REGEXES.get(pat_type, []):
                if regex.search(line):
                    results.append({
                        "pattern_type": pat_type,
                        "file_path": norm_path,
                        "line_number": line_idx,
                        "symbol_id": symbol_id or norm_path,
                        "confidence": conf,
                        "description": desc,
                    })
                    break  # Avoid multiple regex matches on same line for same pattern

    return results


async def detect_dynamic_invocations_impl(
    file_path: str,
    symbol_id: Optional[str] = None,
    patterns: Optional[list[str]] = None,
) -> list[dict]:
    """
    Scans a source file for dynamic invocation patterns.
    """
    target = Path(file_path).resolve()
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"Source file not found: {file_path}")

    selected_patterns = patterns if patterns else ALL_PATTERNS
    selected_patterns = [p for p in selected_patterns if p in ALL_PATTERNS]

    code = target.read_text(encoding="utf-8", errors="replace")
    norm_path = os.path.relpath(target, Path.cwd()).replace("\\", "/")
    ext = target.suffix.lower()

    findings: list[dict[str, Any]] = []

    # If Python, combine deep AST visitor with regex heuristics
    if ext == ".py":
        try:
            tree = ast.parse(code, filename=str(target))
            ast_detector = PythonASTDynamicDetector(norm_path, symbol_id)
            ast_detector.visit(tree)
            # Filter by selected patterns
            findings.extend([
                f for f in ast_detector.findings
                if f["pattern_type"] in selected_patterns
            ])
        except SyntaxError:
            pass

    # Run general regex scanner to catch remaining/cross-language patterns
    regex_findings = scan_file_heuristics(
        norm_path,
        code,
        selected_patterns,
        symbol_id=symbol_id,
    )

    # De-duplicate findings by (pattern_type, line_number)
    seen: set[tuple[str, int]] = set()
    combined: list[dict[str, Any]] = []
    for f in findings + regex_findings:
        key = (f["pattern_type"], f["line_number"])
        if key not in seen:
            seen.add(key)
            combined.append(f)

    # Sort deterministically by line number
    combined.sort(key=lambda x: (x["line_number"], x["pattern_type"]))
    return combined
