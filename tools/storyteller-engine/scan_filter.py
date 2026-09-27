"""
scan_filter.py
~~~~~~~~~~~~~~
Shared source-discovery and noise-stripping helpers for the storyteller crawlers.

Two responsibilities:

1. ``collect_files`` — one walker and one exclusion policy for every crawler,
   replacing four copies of the same ``_collect_files`` / ``exclude_dirs`` pair.

2. ``blank_comments`` — blanks comment and docstring text before pattern
   matching, so documentation examples are never reported as real routes,
   models or service calls. Line and column offsets are preserved exactly, so
   every line number a crawler reports still points at the right source line.

Inline string literals are deliberately left intact: crawlers read route paths
out of ``@app.get("/users")`` and table names out of ``__tablename__ = "users"``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, List, Optional, Set

# Directories that never contain first-party source worth analysing.
DEFAULT_EXCLUDE_DIRS: frozenset[str] = frozenset({
    ".git", "node_modules", "__pycache__", "venv", ".venv",
    "dist", "build", ".next", ".turbo", "vendor",
    ".claude", ".context-cache", ".pytest_cache", ".mypy_cache",
    "output", "traces", "worktrees",
})

# The storyteller's own source tree. Analysing it makes the engine rediscover
# the example snippets in its own docstrings — the reason a self-scan used to
# report three phantom `users` tables.
ENGINE_DIR: Path = Path(__file__).resolve().parent

_TEST_STEM_RE = re.compile(r'(?:^test_|_test$|\.test$|\.spec$)', re.IGNORECASE)
_TEST_DIR_PARTS: frozenset[str] = frozenset({
    "tests", "test", "__tests__", "spec", "testdata", "fixtures",
})


def is_test_path(path: Path) -> bool:
    """True for test files, whose fixtures mimic real routes and models."""
    if any(part.lower() in _TEST_DIR_PARTS for part in path.parts):
        return True
    return bool(_TEST_STEM_RE.search(path.stem))


def is_engine_source(path: Path) -> bool:
    """True when ``path`` is part of the storyteller engine itself."""
    try:
        path.resolve().relative_to(ENGINE_DIR)
    except (ValueError, OSError):
        return False
    return True


def collect_files(
    root: Path | str,
    extensions: Iterable[str],
    *,
    exclude_dirs: Optional[Set[str]] = None,
    include_tests: bool = False,
    include_engine_source: bool = False,
) -> List[Path]:
    """Walks ``root`` and returns analysable source files, sorted for determinism.

    Sorting matters: crawler output feeds Mermaid node ids and story prose, and
    ``os.walk`` order varies between filesystems.
    """
    root_path = Path(root).resolve()
    skip_dirs = set(exclude_dirs) if exclude_dirs is not None else set(DEFAULT_EXCLUDE_DIRS)
    wanted = {ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in extensions}

    collected: List[Path] = []
    for current, dirs, files in os.walk(root_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for name in files:
            candidate = Path(current) / name
            if candidate.suffix.lower() not in wanted:
                continue
            if not include_tests and is_test_path(candidate):
                continue
            if not include_engine_source and is_engine_source(candidate):
                continue
            collected.append(candidate)

    return sorted(collected)


# ── Comment / docstring blanking ─────────────────────────────────────────────

_PYTHON_LANGS: frozenset[str] = frozenset({"py", "python", "pyi"})
_C_LIKE_LANGS: frozenset[str] = frozenset({
    "ts", "js", "tsx", "jsx", "mts", "cts", "go", "prisma", "java", "c", "cc", "cpp", "h",
})


def blank_comments(content: str, language: str) -> str:
    """Blanks comments and docstrings, preserving every line and column offset.

    ``language`` accepts a bare name (``"python"``) or a file suffix (``".ts"``).
    Unknown languages are returned unchanged.
    """
    lang = language.lower().lstrip(".")
    if lang in _PYTHON_LANGS:
        return _blank_python(content)
    if lang in _C_LIKE_LANGS:
        return _blank_c_like(content)
    return content


def _blank_span(chars: List[str], start: int, end: int) -> None:
    """Overwrites ``chars[start:end]`` with spaces, leaving newlines in place."""
    for index in range(start, end):
        if chars[index] != "\n":
            chars[index] = " "


def _skip_quoted(content: str, start: int, quote: str, *, multiline: bool = False) -> int:
    """Returns the index just past the quoted literal opening at ``start``."""
    index = start + 1
    length = len(content)
    while index < length:
        char = content[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            return index + 1
        if char == "\n" and not multiline:
            return index + 1
        index += 1
    return length


def _blank_python(content: str) -> str:
    chars = list(content)
    index, length = 0, len(content)

    while index < length:
        char = content[index]

        if char == "#":
            line_end = content.find("\n", index)
            line_end = length if line_end == -1 else line_end
            _blank_span(chars, index, line_end)
            index = line_end
            continue

        if char in "\"'":
            delimiter = content[index:index + 3]
            if delimiter in ('"""', "'''"):
                close = content.find(delimiter, index + 3)
                end = length if close == -1 else close + 3
                _blank_span(chars, index, end)
                index = end
                continue
            index = _skip_quoted(content, index, char)
            continue

        index += 1

    return "".join(chars)


def _blank_c_like(content: str) -> str:
    chars = list(content)
    index, length = 0, len(content)

    while index < length:
        char = content[index]

        if char == "/" and index + 1 < length:
            following = content[index + 1]
            if following == "/":
                line_end = content.find("\n", index)
                line_end = length if line_end == -1 else line_end
                _blank_span(chars, index, line_end)
                index = line_end
                continue
            if following == "*":
                close = content.find("*/", index + 2)
                end = length if close == -1 else close + 2
                _blank_span(chars, index, end)
                index = end
                continue

        if char in "\"'`":
            index = _skip_quoted(content, index, char, multiline=(char == "`"))
            continue

        index += 1

    return "".join(chars)
