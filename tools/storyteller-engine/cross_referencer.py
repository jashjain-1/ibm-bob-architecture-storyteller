"""
cross_referencer.py
~~~~~~~~~~~~~~~~~~~
Sub-Agent 4: Multi-Callsite Cross-Referencer & Complexity Evaluator.

Crucial Rule: Code context is cross-referenced according to ALL instances
where a function is called across the entire repository, not solely on isolated code logic.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from scan_filter import collect_files

# Weight applied to each distinct *other* file that calls a symbol. A helper
# invoked 30 times inside its own module is local plumbing; one invoked from
# four different modules is an architectural seam worth explaining to a new hire.
FAN_IN_WEIGHT = 3

# Complexity contributes to the score but must not dominate it, or a single
# deeply-branched private routine outranks every cross-module entry point.
MAX_COMPLEXITY_CONTRIBUTION = 20

# Bonus for reflection / eval / dynamic-dispatch flags — genuinely delicate code.
UNUSUAL_LOGIC_BONUS = 2


def _is_boilerplate_symbol(name: str) -> bool:
    """True for dunder methods.

    Cross-referencing is name-based, so every class's ``__init__`` collapses into
    one symbol with an inflated call count that means nothing architecturally.
    """
    return name.startswith("__") and name.endswith("__")


@dataclass
class CallSiteInstance:
    caller_file: str
    line_number: int
    enclosing_symbol: str
    snippet: str
    arguments: List[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CrossReferencedSymbol:
    name: str
    definition_file: str
    definition_line_start: int
    definition_line_end: int
    language: str
    cyclomatic_complexity: int
    unusual_logic_flags: List[str] = field(default_factory=list)
    call_sites: List[CallSiteInstance] = field(default_factory=list)
    outbound_calls: List[str] = field(default_factory=list)
    total_call_occurrences: int = 0
    definition_code: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "definition_file": self.definition_file,
            "definition_line_start": self.definition_line_start,
            "definition_line_end": self.definition_line_end,
            "language": self.language,
            "cyclomatic_complexity": self.cyclomatic_complexity,
            "unusual_logic_flags": self.unusual_logic_flags,
            "call_sites": [cs.to_dict() for cs in self.call_sites],
            "outbound_calls": self.outbound_calls,
            "total_call_occurrences": self.total_call_occurrences,
            "definition_code": self.definition_code,
        }


class CrossReferencer:
    """Discovers all call instances across the repository and computes architectural impact."""

    EXTENSIONS = (".py", ".ts", ".js", ".tsx", ".jsx", ".go")

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir).resolve()
        self._all_files: Optional[List[Path]] = None

    def _get_files(self) -> List[Path]:
        if self._all_files is None:
            self._all_files = collect_files(self.root_dir, self.EXTENSIONS)
        return self._all_files

    def analyze_symbol(self, target_function_name: str, target_file_hint: Optional[str] = None) -> Optional[CrossReferencedSymbol]:
        """Analyzes a specific function and cross-references all occurrences across the repo."""
        files = self._get_files()
        def_file, def_start, def_end, lang, def_code = self._find_definition(target_function_name, files, target_file_hint)
        if not def_file:
            return None

        # Calculate complexity & logic flags
        complexity, flags, out_calls = self._evaluate_logic_complexity(def_code, lang)

        # Cross-reference all call-sites across all files!
        call_sites = self._find_all_call_sites(target_function_name, files, def_file)

        return CrossReferencedSymbol(
            name=target_function_name,
            definition_file=str(def_file.relative_to(self.root_dir)).replace("\\", "/"),
            definition_line_start=def_start,
            definition_line_end=def_end,
            language=lang,
            cyclomatic_complexity=complexity,
            unusual_logic_flags=flags,
            call_sites=call_sites,
            outbound_calls=out_calls,
            total_call_occurrences=len(call_sites),
            definition_code=def_code,
        )

    def scan_all_complex_symbols(self, min_complexity: int = 4) -> List[CrossReferencedSymbol]:
        """Scans the entire repository to find and cross-reference all complex or pivotal functions."""
        files = self._get_files()
        candidates = []

        for fpath in files:
            ext = fpath.suffix.lower()
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            if ext == ".py":
                candidates.extend(self._find_py_functions(fpath, content))
            elif ext in (".ts", ".js", ".tsx", ".jsx"):
                candidates.extend(self._find_ts_functions(fpath, content))
            elif ext == ".go":
                candidates.extend(self._find_go_functions(fpath, content))

        results = []
        for name, fpath, start, end, lang, code in candidates:
            if _is_boilerplate_symbol(name):
                continue
            complexity, flags, out_calls = self._evaluate_logic_complexity(code, lang)
            if complexity >= min_complexity or flags:
                # Cross-reference all call sites
                call_sites = self._find_all_call_sites(name, files, fpath)
                results.append(CrossReferencedSymbol(
                    name=name,
                    definition_file=str(fpath.relative_to(self.root_dir)).replace("\\", "/"),
                    definition_line_start=start,
                    definition_line_end=end,
                    language=lang,
                    cyclomatic_complexity=complexity,
                    unusual_logic_flags=flags,
                    call_sites=call_sites,
                    outbound_calls=out_calls,
                    total_call_occurrences=len(call_sites),
                    definition_code=code,
                ))

        # Rank by cross-module reach first, then complexity — sorting on raw
        # occurrence count surfaces single-file helpers over real seams.
        results.sort(key=self._pivotal_score, reverse=True)
        seen_names = set()
        deduped = []
        for r in results:
            if r.name not in seen_names:
                seen_names.add(r.name)
                deduped.append(r)
        return deduped

    @staticmethod
    def _cross_file_fan_in(symbol: CrossReferencedSymbol) -> int:
        """Distinct files other than the definition file that call this symbol."""
        return len({
            cs.caller_file for cs in symbol.call_sites
            if cs.caller_file != symbol.definition_file
        })

    @classmethod
    def _pivotal_score(cls, symbol: CrossReferencedSymbol) -> tuple[int, int]:
        fan_in = cls._cross_file_fan_in(symbol)
        score = (
            fan_in * FAN_IN_WEIGHT
            + min(symbol.cyclomatic_complexity, MAX_COMPLEXITY_CONTRIBUTION)
            + (UNUSUAL_LOGIC_BONUS if symbol.unusual_logic_flags else 0)
        )
        return (score, fan_in)

    def _find_definition(self, func_name: str, files: List[Path], file_hint: Optional[str]) -> tuple[Optional[Path], int, int, str, str]:
        # Filter files if file_hint provided
        search_files = files
        if file_hint:
            norm_hint = file_hint.replace("\\", "/").lower()
            search_files = [f for f in files if norm_hint in str(f).replace("\\", "/").lower()] or files

        # Exact definition regexes (functions, classes, interfaces, types, constants, variables)
        py_re = re.compile(rf'^\s*(?:async\s+)?(?:def|class)\s+{re.escape(func_name)}\b|^\s*{re.escape(func_name)}\s*[:=]', re.MULTILINE)
        ts_re = re.compile(rf'(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\s+{re.escape(func_name)}\b|class\s+{re.escape(func_name)}\b|interface\s+{re.escape(func_name)}\b|type\s+{re.escape(func_name)}\b|(?:const|let|var)\s+{re.escape(func_name)}\b)')
        go_re = re.compile(rf'^\s*(?:func\s+(?:\([^)]+\)\s+)?{re.escape(func_name)}\b|type\s+{re.escape(func_name)}\b|(?:var|const)\s+{re.escape(func_name)}\b)', re.MULTILINE)

        for fpath in search_files:
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            ext = fpath.suffix.lower()
            lang = "python" if ext == ".py" else ("go" if ext == ".go" else "typescript")

            match = None
            if ext == ".py":
                match = py_re.search(content)
            elif ext in (".ts", ".js", ".tsx", ".jsx"):
                match = ts_re.search(content)
            elif ext == ".go":
                match = go_re.search(content)

            if match:
                start_line = content.count("\n", 0, match.start()) + 1
                lines = content.splitlines()
                # Find body end heuristic
                end_line = min(start_line + 40, len(lines))
                code = "\n".join(lines[start_line - 1:end_line])
                return fpath, start_line, end_line, lang, code

        return None, 0, 0, "", ""

    def _find_all_call_sites(self, func_name: str, files: List[Path], def_file: Path) -> List[CallSiteInstance]:
        """Scans every file in the repo to find all occurrences where func_name is called."""
        call_sites = []

        for fpath in files:
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            rel_file = str(fpath.relative_to(self.root_dir)).replace("\\", "/")
            lines = content.splitlines()

            # Fast pre-check
            if func_name not in content:
                continue

            # Determine enclosing symbol for lines
            enclosing_map = self._build_enclosing_symbols(lines, fpath.suffix.lower())

            for line_idx, line in enumerate(lines):
                if func_name in line:
                    # Ignore definition line itself in def_file
                    if fpath == def_file and (f"def {func_name}" in line or f"function {func_name}" in line or f"func {func_name}" in line or f"class {func_name}" in line or f"const {func_name}" in line or f"let {func_name}" in line or f"var {func_name}" in line):
                        continue

                    # Check for actual call pattern
                    m = re.search(rf'\b{re.escape(func_name)}\s*\(([^)]*)\)', line)
                    if m:
                        arg_str = m.group(1).strip()
                        args = [a.strip() for a in arg_str.split(",") if a.strip()]
                        snippet = line.strip()
                        enclosing = enclosing_map.get(line_idx, "module_scope")
                        call_sites.append(CallSiteInstance(
                            caller_file=rel_file,
                            line_number=line_idx + 1,
                            enclosing_symbol=enclosing,
                            snippet=snippet,
                            arguments=args,
                        ))

        return call_sites

    def _evaluate_logic_complexity(self, code: str, lang: str) -> tuple[int, List[str], List[str]]:
        complexity = 1
        flags = []
        outbound_calls = []

        # Cyclomatic branch tokens
        branch_tokens = ["if ", "elif ", "else if ", "case ", "for ", "while ", "catch ", "except ", " && ", " || ", " and ", " or "]
        for tok in branch_tokens:
            complexity += code.count(tok)

        # Unusual logic pattern heuristics
        if "retry" in code.lower() or "backoff" in code.lower():
            flags.append("Adaptive Retry / Exponential Backoff Logic")
        if "lock" in code.lower() or "mutex" in code.lower() or "semaphore" in code.lower():
            flags.append("Concurrency Synchronization (Lock / Mutex / Semaphore)")
        if "fallback" in code.lower() or "try" in code and "except" in code:
            flags.append("Defensive Fault Tolerance & Graceful Fallbacks")
        if "cache" in code.lower() or "ttl" in code.lower():
            flags.append("Performance Caching / Memoization Barrier")
        if "hack" in code.lower() or "fixme" in code.lower() or "workaround" in code.lower() or "todo" in code.lower():
            flags.append("Explicit Legacy Workaround / Inlined Hotfix")
        if "timeout" in code.lower() or "deadline" in code.lower():
            flags.append("Execution Deadline & Circuit Breaker Guard")

        # Outbound calls
        call_matches = re.findall(r'\b([a-zA-Z_]\w*)\s*\(', code)
        ignore_keywords = {"if", "for", "while", "switch", "catch", "def", "function", "return", "print", "len", "range", "dict", "list", "str", "int"}
        outbound_calls = list(dict.fromkeys([c for c in call_matches if c not in ignore_keywords]))[:10]

        return min(complexity, 25), flags, outbound_calls

    def _build_enclosing_symbols(self, lines: List[str], ext: str) -> Dict[int, str]:
        enclosing: Dict[int, str] = {}
        current = "module_level"
        def_re = re.compile(r'^\s*(?:async\s+)?(?:def|function|func)\s+([a-zA-Z_]\w*)')
        class_re = re.compile(r'^\s*class\s+([a-zA-Z_]\w*)')

        for idx, line in enumerate(lines):
            c_match = class_re.search(line)
            if c_match:
                current = f"class {c_match.group(1)}"
            d_match = def_re.search(line)
            if d_match:
                current = d_match.group(1)
            enclosing[idx] = current
        return enclosing

    def _find_py_functions(self, fpath: Path, content: str) -> List[tuple]:
        res = []
        lines = content.splitlines()
        for i, line in enumerate(lines):
            m = re.match(r'^\s*(?:async\s+)?def\s+([a-zA-Z_]\w*)\s*\(', line)
            if m:
                name = m.group(1)
                end = min(i + 35, len(lines))
                code = "\n".join(lines[i:end])
                res.append((name, fpath, i + 1, end, "python", code))
        return res

    def _find_ts_functions(self, fpath: Path, content: str) -> List[tuple]:
        res = []
        lines = content.splitlines()
        for i, line in enumerate(lines):
            m = re.search(r'(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z_]\w*)\s*\(', line)
            if m:
                name = m.group(1)
                end = min(i + 35, len(lines))
                code = "\n".join(lines[i:end])
                res.append((name, fpath, i + 1, end, "typescript", code))
        return res

    def _find_go_functions(self, fpath: Path, content: str) -> List[tuple]:
        res = []
        lines = content.splitlines()
        for i, line in enumerate(lines):
            m = re.match(r'^\s*func\s+(?:\([^)]+\)\s+)?([a-zA-Z_]\w*)\s*\(', line)
            if m:
                name = m.group(1)
                end = min(i + 35, len(lines))
                code = "\n".join(lines[i:end])
                res.append((name, fpath, i + 1, end, "go", code))
        return res
