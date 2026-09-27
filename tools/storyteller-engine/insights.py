"""
insights.py
~~~~~~~~~~~
Live-first AI insight generation with a deterministic fallback.

Provider chain (first available wins, per batch):

1. `BobCliProvider`   - a configured IBM Bob / agent command (setting or env).
2. `LocalLlmProvider` - any Ollama-compatible HTTP endpoint
                        (`STORYTELLER_LLM_URL`, default http://127.0.0.1:11434).
3. `DeterministicProvider` - factual phrasing derived from names, docstrings,
   call graph and git metadata. Always available, never blank, never invented.

Every stored entry records its `source` (`bob`, `llm`, or `auto`) and the
content key it was generated for, so the dossier can label AI prose honestly and
the cache can regenerate exactly the symbols whose code or dependencies changed.

Micro summaries are hard-capped at 5 words, per the product requirement.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Optional

from cache_store import StorytellerCache, insight_key

MAX_MICRO_WORDS = 5
BATCH_SIZE = 60
DEFAULT_LLM_URL = os.environ.get("STORYTELLER_LLM_URL", "http://127.0.0.1:11434")
DEFAULT_LLM_MODEL = os.environ.get("STORYTELLER_LLM_MODEL", "")
PROVIDER_TIMEOUT_S = float(os.environ.get("STORYTELLER_PROVIDER_TIMEOUT", "120"))

_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U00002190-\U000021FF\uFE0F]"
)
_WS_RE = re.compile(r"\s+")
_STOPWORDS = {"the", "a", "an", "to", "of", "for", "in", "on", "and", "or", "with", "from", "at"}

_VERB_MAP = {
    "get": "Returns", "fetch": "Fetches", "load": "Loads", "read": "Reads",
    "write": "Writes", "save": "Saves", "store": "Stores", "persist": "Persists",
    "create": "Creates", "make": "Builds", "build": "Builds", "init": "Initializes",
    "setup": "Configures", "configure": "Configures", "run": "Runs", "start": "Starts",
    "stop": "Stops", "close": "Closes", "open": "Opens", "parse": "Parses",
    "extract": "Extracts", "scan": "Scans", "find": "Finds", "search": "Searches",
    "match": "Matches", "validate": "Validates", "verify": "Verifies", "check": "Checks",
    "assert": "Asserts", "handle": "Handles", "process": "Processes", "render": "Renders",
    "draw": "Draws", "paint": "Paints", "print": "Prints", "main": "Entry point",
    "use": "Uses", "apply": "Applies", "update": "Updates", "delete": "Deletes",
    "remove": "Removes", "add": "Adds", "insert": "Inserts", "map": "Maps",
    "sort": "Sorts", "filter": "Filters", "collect": "Collects", "gather": "Gathers",
    "resolve": "Resolves", "route": "Routes", "dispatch": "Dispatches",
    "compute": "Computes", "calculate": "Calculates", "analyse": "Analyzes",
    "analyze": "Analyzes", "detect": "Detects", "infer": "Infers", "emit": "Emits",
    "send": "Sends", "receive": "Receives", "listen": "Listens", "serve": "Serves",
    "publish": "Publishes", "subscribe": "Subscribes", "encode": "Encodes",
    "decode": "Decodes", "normalize": "Normalizes", "format": "Formats",
    "index": "Indexes", "hash": "Hashes", "sign": "Signs", "encrypt": "Encrypts",
    "decrypt": "Decrypts", "merge": "Merges", "split": "Splits", "join": "Joins",
    "copy": "Copies", "move": "Moves", "clean": "Cleans", "strip": "Strips",
    "cache": "Caches", "refresh": "Refreshes", "sync": "Synchronises",
    "test": "Tests", "mock": "Mocks", "assert_": "Asserts",
}

_PREFIX_HANDLERS = (
    ("is_", "Checks"), ("has_", "Checks"), ("can_", "Checks"), ("should_", "Checks"),
    ("to_", "Converts"), ("from_", "Converts"), ("on_", "Handles"),
    ("test_", "Tests"), ("_", "Internal"),
)


def strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub("", text or "")


def clean_text(text: str) -> str:
    text = strip_emoji(text)
    text = text.replace("`", "").replace("*", "").replace("_", " ")
    return _WS_RE.sub(" ", text).strip()


def split_identifier(name: str) -> list[str]:
    parts = re.split(r"[^A-Za-z0-9]+", name)
    words: list[str] = []
    for part in parts:
        if not part:
            continue
        words.extend(re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+", part))
    return [w for w in words if w]


def cap_words(text: str, limit: int = MAX_MICRO_WORDS) -> str:
    words = [w for w in clean_text(text).split(" ") if w]
    return " ".join(words[:limit])


# ---------------------------------------------------------------------------
# Deterministic summaries (always available)
# ---------------------------------------------------------------------------

def deterministic_micro(symbol: dict[str, Any]) -> str:
    """<=5-word factual label: docstring intent first, then name semantics."""
    doc = clean_text(symbol.get("doc") or "")
    if doc:
        sentence = re.split(r"(?<=[.!?])\s+", doc)[0]
        words = [w for w in sentence.split(" ") if w]
        if words:
            text = " ".join(words[:MAX_MICRO_WORDS])
            text = text.rstrip(".,:;")
            if len(text) >= 5:
                return text[0].upper() + text[1:]

    name = symbol.get("name") or "symbol"
    words = split_identifier(name)
    if not words:
        return "Core routine"

    cleaned: list[str] = []
    for prefix, verb in _PREFIX_HANDLERS:
        if name.startswith(prefix) and prefix != "_":
            cleaned = [verb] + words[1:]
            break
    if not cleaned:
        first = words[0].lower()
        if first in _VERB_MAP:
            cleaned = [_VERB_MAP[first]] + words[1:]
        else:
            if symbol.get("kind") in ("class", "interface", "type"):
                return cap_words("Type " + " ".join(words))
            cleaned = [words[0][0].upper() + words[0][1:]] + words[1:]

    kept = [cleaned[0]] + [w for w in cleaned[1:] if w.lower() not in _STOPWORDS]
    return cap_words(" ".join(kept))


def deterministic_why(symbol: dict[str, Any]) -> str:
    """One factual sentence; never invents intent the model cannot support."""
    doc = clean_text(symbol.get("doc") or "")
    if len(doc) > 20:
        sentences = re.split(r"(?<=[.!?])\s+", doc)
        text = " ".join(sentences[:2])[:280]
        if text:
            return text

    kind = symbol.get("kind", "function")
    fan_in = len(symbol.get("callers") or [])
    fan_out = len(symbol.get("calls") or [])
    complexity = symbol.get("complexity", 1)
    bits = [
        f"{kind.capitalize()} defined in {symbol.get('file_path')}:{symbol.get('line_start')}.",
        f"Referenced by {fan_in} caller(s); invokes {fan_out} resolved symbol(s); complexity {complexity}.",
    ]
    flags = [f for f in (symbol.get("flags") or []) if not f.startswith("filesystem")]
    if flags:
        bits.append("Signals: " + ", ".join(flags[:4]) + ".")
    if symbol.get("is_test"):
        bits.append("Part of the test suite.")
    return " ".join(bits)


class ProviderUnavailable(RuntimeError):
    """Raised when a provider cannot run (missing command, no endpoint, ...)."""


class ProviderResult:
    __slots__ = ("items", "source", "model")

    def __init__(self, items: dict[str, Any], source: str, model: str = ""):
        self.items = items
        self.source = source
        self.model = model


def _normalize_items(raw: Any, wanted: Iterable[str]) -> dict[str, dict[str, str]]:
    """Accept dict- or list-shaped provider output and clamp it to the contract."""
    wanted_set = set(wanted)
    items: dict[str, dict[str, str]] = {}

    def _add(symbol_id: Any, entry: Any) -> None:
        if not isinstance(symbol_id, str) or symbol_id not in wanted_set:
            return
        if not isinstance(entry, dict):
            return
        micro = cap_words(str(entry.get("micro") or entry.get("summary") or ""))
        why = clean_text(str(entry.get("why") or entry.get("rationale") or ""))[:320]
        if micro:
            items[symbol_id] = {"micro": micro, "why": why}

    if isinstance(raw, dict):
        for key, value in raw.items():
            if key == "items" and isinstance(value, dict):
                for sid, entry in value.items():
                    _add(sid, entry)
            elif isinstance(value, dict):
                _add(key, value)
    elif isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict):
                _add(entry.get("id"), entry)
    return items


def _extract_json(text: str) -> Any:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in provider output")
    return json.loads(text[start:end + 1])


MAX_NARRATIVE_CHARS = 2000
MAX_STORY_CHAPTERS = 8
MAX_ROADMAP_ITEMS = 12


def _clean_prose(text: str) -> str:
    """Narrative text: drop emoji and markdown noise, keep code identifiers.

    Unlike `clean_text` this leaves underscores alone: prose routinely names
    routines like `compute_total`, and rewriting them would falsify the text.
    """
    text = strip_emoji(text).replace("`", "").replace("*", "")
    return _WS_RE.sub(" ", text).strip()


def _normalize_narrative(raw: Any) -> dict[str, Any]:
    """Clamp provider narrative output to the documented shape; per-field.

    Missing or unusable fields are simply absent, so the caller falls back to
    the deterministic text for exactly those fields.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}

    paragraphs = [_clean_prose(p) for p in re.split(r"\n\s*\n", str(raw.get("exec_summary") or raw.get("summary") or ""))]
    paragraphs = [p for p in paragraphs if p]
    if paragraphs:
        out["exec_summary"] = "\n\n".join(paragraphs)[:MAX_NARRATIVE_CHARS]

    story_in = raw.get("story") or raw.get("chapters") or []
    chapters: list[dict[str, str]] = []
    if isinstance(story_in, list):
        for item in story_in:
            if not isinstance(item, dict):
                continue
            title = _clean_prose(str(item.get("title") or ""))[:80]
            content = _clean_prose(str(item.get("content") or item.get("text") or ""))[:1200]
            if title and content:
                chapters.append({"title": title, "content": content})
            if len(chapters) >= MAX_STORY_CHAPTERS:
                break
    if chapters:
        out["story"] = chapters

    roadmap_in = raw.get("roadmap") or raw.get("steps") or []
    items: list[str] = []
    if isinstance(roadmap_in, list):
        for step in roadmap_in:
            text = _clean_prose(str(step))[:240]
            if text:
                items.append(text)
            if len(items) >= MAX_ROADMAP_ITEMS:
                break
    if items:
        out["roadmap"] = items
    return out


class BobCliProvider:
    """Runs a configured IBM Bob / agent command.

    Command contract (placeholders optional):

        my-agent --request {request} --out {response}

    - `{request}`  path to a JSON request file
    - `{response}` path the command should write JSON to
    - with neither placeholder, the request JSON is piped to stdin and the
      response is read from stdout.

    Response shape: {"items": {"<symbol id>": {"micro": "...", "why": "..."}}}
    """

    def __init__(self, command: str | None = None, cwd: str | Path | None = None):
        self.command = (command or os.environ.get("STORYTELLER_BOB_CMD") or "").strip()
        self.cwd = cwd

    def available(self) -> bool:
        return bool(self.command)

    def describe(self) -> str:
        return self.command or "(unset)"

    def generate(self, batch: list[dict[str, Any]]) -> ProviderResult:
        if not self.available():
            raise ProviderUnavailable("no Bob command configured")
        payload = {
            "task": "summarize_symbols",
            "instructions": (
                "For each item write micro (AT MOST 5 words, no period) and why "
                "(one factual sentence). Reply with JSON only: "
                '{"items": {"<id>": {"micro": "...", "why": "..."}}}'
            ),
            "items": batch,
        }
        parsed = self._dispatch(payload)
        items = _normalize_items(parsed, [item["id"] for item in batch])
        if not items:
            raise ProviderUnavailable("Bob response contained no usable items")
        return ProviderResult(items, "bob", model="bob")

    def generate_narrative(self, digest: dict[str, Any]) -> ProviderResult:
        """Repository-level prose for the dossier (exec summary, story, roadmap)."""
        if not self.available():
            raise ProviderUnavailable("no Bob command configured")
        payload = {
            "task": "summarize_repository",
            "instructions": (
                "You are documenting a repository for a developer who has never seen it. "
                "Write: exec_summary (2-4 short factual paragraphs, plain text), "
                "story (5-7 chapters, each {title, content}, walking from entry points "
                "through the main flows to the riskiest logic), and roadmap "
                "(3-8 ordered modernization steps grounded in the evidence given). "
                "Never invent behaviour the given fields do not support. "
                'Reply with JSON only: {"exec_summary": "...", '
                '"story": [{"title": "...", "content": "..."}], "roadmap": ["..."]}'
            ),
            "repository": digest,
        }
        parsed = self._dispatch(payload)
        items = _normalize_narrative(parsed)
        if not items:
            raise ProviderUnavailable("Bob response contained no usable narrative")
        return ProviderResult(items, "bob", model="bob")

    def _dispatch(self, payload: dict[str, Any]) -> Any:
        """Run the configured command with the request/response contract."""
        with tempfile.TemporaryDirectory(prefix="storyteller-bob-") as tmp:
            tmp_path = Path(tmp)
            request_path = tmp_path / "request.json"
            response_path = tmp_path / "response.json"
            request_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            # posix=False keeps Windows backslashes in paths (shlex posix mode
            # would strip them); its quotes stay on the tokens, so drop those.
            parts = shlex.split(self.command, posix=(os.name != "nt"))
            if os.name == "nt":
                parts = [p[1:-1] if len(p) >= 2 and p[0] == p[-1] == '"' else p for p in parts]
            used_placeholder = any("{request}" in p or "{response}" in p for p in parts)
            argv = [p.replace("{request}", str(request_path)).replace("{response}", str(response_path)) for p in parts]
            try:
                proc = subprocess.run(
                    argv,
                    cwd=str(self.cwd) if self.cwd else None,
                    input=None if used_placeholder else json.dumps(payload, ensure_ascii=False),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=PROVIDER_TIMEOUT_S,
                    shell=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ProviderUnavailable(f"Bob command failed to run: {exc}") from exc

            if proc.returncode != 0 and not response_path.exists():
                raise ProviderUnavailable(f"Bob command exited {proc.returncode}: {(proc.stderr or '')[:200]}")

            raw_text = ""
            if response_path.exists():
                raw_text = response_path.read_text(encoding="utf-8", errors="replace")
            if not raw_text.strip() and proc.stdout.strip():
                raw_text = proc.stdout
            if not raw_text.strip():
                raise ProviderUnavailable("Bob command produced no response")

            try:
                return _extract_json(raw_text)
            except ValueError as exc:
                raise ProviderUnavailable(f"Bob response was not JSON: {exc}") from exc


class LocalLlmProvider:
    """Ollama-compatible local endpoint; no API key, no external network."""

    def __init__(self, url: str | None = None, model: str | None = None):
        self.url = (url or DEFAULT_LLM_URL).rstrip("/")
        self.model = (model or DEFAULT_LLM_MODEL).strip()
        self._available: Optional[bool] = None

    def _post(self, path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.url + path, data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))

    def available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            with urllib.request.urlopen(self.url + "/api/tags", timeout=1.5) as resp:
                tags = json.loads(resp.read().decode("utf-8", errors="replace"))
            models = [m.get("name", "") for m in tags.get("models", []) if m.get("name")]
            if not self.model and models:
                self.model = models[0]
            self._available = bool(self.model)
        except Exception:
            self._available = False
        return self._available

    def generate(self, batch: list[dict[str, Any]]) -> ProviderResult:
        if not self.available():
            raise ProviderUnavailable("no local LLM endpoint available")
        prompt = (
            "You document source code factually. For each item below write:\n"
            '- "micro": AT MOST 5 words naming what it does (no trailing period)\n'
            '- "why": one factual sentence about its role and dependencies\n'
            "Never invent behaviour that the given fields do not support.\n"
            'Reply with JSON only: {"items": {"<id>": {"micro": "...", "why": "..."}}}\n\n'
            "Items:\n" + json.dumps(batch, ensure_ascii=False)
        )
        try:
            result = self._post("/api/generate", {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1},
            }, timeout=PROVIDER_TIMEOUT_S)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ProviderUnavailable(f"local LLM request failed: {exc}") from exc

        text = result.get("response") or ""
        try:
            parsed = _extract_json(text)
        except ValueError as exc:
            raise ProviderUnavailable(f"local LLM response was not JSON: {exc}") from exc
        items = _normalize_items(parsed, [item["id"] for item in batch])
        if not items:
            raise ProviderUnavailable("local LLM response contained no usable items")
        return ProviderResult(items, "llm", model=self.model)

    def generate_narrative(self, digest: dict[str, Any]) -> ProviderResult:
        """Repository-level prose for the dossier (exec summary, story, roadmap)."""
        if not self.available():
            raise ProviderUnavailable("no local LLM endpoint available")
        prompt = (
            "You document repositories for developers who have never seen them, factually.\n"
            "Write:\n"
            '- "exec_summary": 2-4 short plain-text paragraphs\n'
            '- "story": 5-7 chapters, each {"title": ..., "content": ...}, walking from '
            "entry points through the main flows to the riskiest logic\n"
            '- "roadmap": 3-8 ordered modernization steps grounded in the evidence given\n'
            "Never invent behaviour the given fields do not support.\n"
            'Reply with JSON only: {"exec_summary": "...", "story": [{"title": "...", '
            '"content": "..."}], "roadmap": ["..."]}\n\n'
            "Repository facts:\n" + json.dumps(digest, ensure_ascii=False)
        )
        try:
            result = self._post("/api/generate", {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1},
            }, timeout=PROVIDER_TIMEOUT_S)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ProviderUnavailable(f"local LLM request failed: {exc}") from exc
        text = result.get("response") or ""
        try:
            parsed = _extract_json(text)
        except ValueError as exc:
            raise ProviderUnavailable(f"local LLM response was not JSON: {exc}") from exc
        items = _normalize_narrative(parsed)
        if not items:
            raise ProviderUnavailable("local LLM response contained no usable narrative")
        return ProviderResult(items, "llm", model=self.model)


class DeterministicProvider:
    name = "deterministic"

    def available(self) -> bool:
        return True

    def generate(self, batch: list[dict[str, Any]]) -> ProviderResult:
        items: dict[str, dict[str, str]] = {}
        for item in batch:
            items[item["id"]] = {
                "micro": deterministic_micro(item),
                "why": deterministic_why(item),
            }
        return ProviderResult(items, "auto", model="deterministic")


# ---------------------------------------------------------------------------
# Insight service: cache-aware batch generation
# ---------------------------------------------------------------------------

def _batch_item(sym: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    def _names(ids: Iterable[str], limit: int = 8) -> list[str]:
        out = []
        for sid in ids:
            target = by_id.get(sid)
            if target:
                out.append(target["name"])
            if len(out) >= limit:
                break
        return out

    return {
        "id": sym["id"],
        "name": sym.get("name", ""),
        "qualified": sym.get("qualified", ""),
        "kind": sym.get("kind", ""),
        "language": sym.get("language", ""),
        "file": sym.get("file_path", ""),
        "file_path": sym.get("file_path", ""),
        "line": sym.get("line_start", 0),
        "line_start": sym.get("line_start", 0),
        "doc": (sym.get("doc") or "")[:240],
        "calls": _names(sym.get("calls") or []),
        "callers": _names(sym.get("callers") or []),
        "complexity": sym.get("complexity", 1),
        "flags": sym.get("flags", [])[:6],
        "is_test": sym.get("is_test", False),
    }


class InsightService:
    """Generates and caches per-symbol insights for a model."""

    def __init__(self, repo: str | Path, cache: Optional[StorytellerCache] = None,
                 cache_dir: Optional[str | Path] = None):
        self.repo = Path(repo).resolve()
        self.cache = (cache or StorytellerCache(self.repo, cache_dir)).load()

    # -- providers ---------------------------------------------------------

    def providers(self, bob_command: str | None = None,
                  llm_url: str | None = None,
                  llm_model: str | None = None) -> list[Any]:
        return [
            BobCliProvider(bob_command, cwd=self.repo),
            LocalLlmProvider(llm_url, llm_model),
            DeterministicProvider(),
        ]

    # -- generation --------------------------------------------------------

    def ensure(
        self,
        model: dict[str, Any],
        bob_command: str | None = None,
        llm_url: str | None = None,
        llm_model: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        from model_builder import manifest_from_model

        manifest = manifest_from_model(model)
        delta = self.cache.compute_delta(manifest)
        symbols = {s["id"]: s for s in model.get("symbols", []) if s["id"] in manifest["symbols"]}

        targets: set[str] = set(delta["added"]) | set(delta["changed"]) | (set(symbols) if force else set())
        providers = self.providers(bob_command, llm_url, llm_model)
        live = [p for p in providers if not isinstance(p, DeterministicProvider)]
        live_available = [p for p in live if p.available()]

        if live_available and not force:
            # Upgrade deterministic entries to live AI text when a provider answers.
            for sid, sym in symbols.items():
                entry = self.cache.get_insight(sid, sym.get("hash", ""), sym.get("deps_hash", ""))
                if entry is None or entry.get("source") == "auto":
                    targets.add(sid)

        to_generate = sorted(targets & set(symbols))
        generated = 0
        used_source = "auto"
        provider_note = "deterministic fallback"

        for start in range(0, len(to_generate), BATCH_SIZE):
            batch_ids = to_generate[start:start + BATCH_SIZE]
            batch = [_batch_item(symbols[sid], symbols) for sid in batch_ids]
            result: Optional[ProviderResult] = None
            for provider in providers:
                if not provider.available():
                    continue
                try:
                    result = provider.generate(batch)
                    used_source = result.source
                    provider_note = f"{result.source}:{result.model}" if result.model else result.source
                    break
                except ProviderUnavailable as exc:
                    provider_note = f"{type(provider).__name__} unavailable ({exc})"
                    continue
                except Exception as exc:  # provider crashed: fall back, never fail the build
                    provider_note = f"{type(provider).__name__} error ({type(exc).__name__})"
                    continue

            fallback = DeterministicProvider()
            produced = result.items if result else {}
            source = result.source if result else "auto"
            model_name = result.model if result else "deterministic"

            for sid in batch_ids:
                sym = symbols[sid]
                item = produced.get(sid) or fallback.generate([_batch_item(sym, symbols)]).items[sid]
                self.cache.put_insight(sid, {
                    "micro": cap_words(item.get("micro", "")),
                    "why": clean_text(item.get("why", ""))[:320],
                    "source": source if sid in produced else "auto",
                    "model": model_name,
                    "key": insight_key(sym.get("hash", ""), sym.get("deps_hash", "")),
                    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                })
                generated += 1
            self.cache.save_insights()  # incremental: a crash never loses a batch

        removed = self.cache.prune_insights(set(manifest["symbols"]))
        self.cache.save(manifest)

        return {
            "delta": delta["counts"],
            "fingerprint_changed": delta["fingerprint_changed"],
            "first_run": delta["first_run"],
            "generated": generated,
            "removed": removed,
            "cached_total": self.cache.insight_count(),
            "sources": self.cache.source_counts(),
            "provider": provider_note,
            "providers_available": [type(p).__name__ for p in providers if p.available()],
        }

    def get(self, symbol_id: str) -> Optional[dict[str, Any]]:
        return self.cache.insights.get(symbol_id)


# ---------------------------------------------------------------------------
# Repo-level narratives (data-derived, cached by input hash)
# ---------------------------------------------------------------------------

def story_digest(model: dict[str, Any]) -> dict[str, Any]:
    stats = model.get("stats", {})
    symbols = {s["id"]: s for s in model.get("symbols", [])}
    modules = [n["id"] for n in (model.get("module_graph", {}) or {}).get("nodes", [])][:12]
    hubs = []
    for entry in (model.get("pivotal") or [])[:6]:
        sym = symbols.get(entry["id"])
        if sym:
            hubs.append({
                "name": sym["qualified"], "file": sym["file_path"],
                "fan_in": entry["fan_in"], "cross_file": entry["cross_file_callers"],
                "complexity": entry["complexity"],
            })
    return {
        "repo": model.get("repo", {}).get("name", ""),
        "stats": {
            "files": stats.get("files"), "symbols": stats.get("symbols"),
            "functions": stats.get("functions"), "methods": stats.get("methods"),
            "classes": stats.get("classes"), "modules": stats.get("modules"),
            "routes": stats.get("routes"), "models": stats.get("models"),
            "services": stats.get("services"), "test_functions": stats.get("test_functions"),
            "production_functions": stats.get("production_functions"),
            "resolved_call_edges": stats.get("resolved_call_edges"),
            "entry_points": stats.get("entry_points"),
        },
        "languages": stats.get("languages", []),
        "modules": modules,
        "hubs": hubs,
        "entries": [
            {"name": e.get("name"), "kind": e.get("kind"), "file": e.get("file_path")}
            for e in (model.get("entry_points") or [])[:8]
        ],
        "flows": [
            {"entry": f.get("entry"), "chain": [n["name"] for n in f.get("chain", [])]}
            for f in (model.get("flows") or [])[:5]
        ],
    }


# Bump this whenever the generated prose changes shape. The hash keys the
# narrative cache, so without a version an old summary outlives the code that
# produced it and the dossier renders text no longer in the source.
# v3: provider-written narrative bundle (exec_summary / story / roadmap).
NARRATIVE_VERSION = 3


def narrative_hash(model: dict[str, Any]) -> str:
    import hashlib
    digest = story_digest(model)
    fingerprint = (model.get("repo", {}).get("fingerprint") or {}).get("hash", "")
    blob = f"v{NARRATIVE_VERSION}|" + json.dumps(digest, sort_keys=True) + "|" + fingerprint
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]


def deterministic_exec_summary(model: dict[str, Any]) -> str:
    """Structured HTML summary: what this is, what carries it, where risk sits.

    Written as prose and short lists rather than a tally, so it does not simply
    repeat the metric cards above it. Every statement is derived from the model.
    """
    d = story_digest(model)
    s = d["stats"]
    languages = language_list(d["languages"]) or "unrecognised"
    name = d["repo"] or "This repository"
    hubs = d["hubs"][:3]
    module_count = int(s.get("modules") or 0)

    parts: list[str] = []

    # Lead: orientation plus where the weight of the code sits.
    centre = ""
    if hubs:
        roots: dict[str, int] = {}
        for hub in hubs:
            head = str(hub.get("file") or "").split("/")[0]
            if head:
                roots[head] = roots.get(head, 0) + 1
        if roots:
            top_root = max(roots, key=lambda k: roots[k])
            held = roots[top_root]
            if held == len(hubs) and held > 1:
                centre = (f" Its centre of gravity is {esc_text(top_root)}, which holds "
                          "every routine that matters most.")
            elif held > 1:
                centre = (f" Its centre of gravity is {esc_text(top_root)}, which holds "
                          f"{_number_word(held)} of the {_number_word(len(hubs))} routines "
                          "that matter most.")
    span = (f' spanning {_count(module_count, "module")}' if module_count
            else " with no detected module boundaries")
    parts.append(
        f'<p class="lead">{esc_text(name)} is a {esc_text(languages)} codebase'
        f'{span}.{centre}</p>'
    )

    if hubs:
        rows = "".join(
            f"<li><code>{esc_text(h.get('name') or '')}</code> - "
            f"{_plural(h.get('fan_in'), 'caller')}"
            + (f", {_number_word(h.get('cross_file'))} of them from other files"
               if h.get("cross_file") else "")
            + (f", complexity {h.get('complexity')}" if h.get("complexity") else "")
            + f" ({esc_text(h.get('file') or '')})</li>"
            for h in hubs
        )
        parts.append('<h4>What carries the logic</h4>')
        parts.append(f"<ul>{rows}</ul>")

    counts = (model.get("clusters", {}) or {}).get("counts", {}) or {}
    cyclic = counts.get("cyclic", 0) or 0
    dynamic = counts.get("dynamic", 0) or 0
    tests = s.get("test_functions") or 0
    production = s.get("production_functions") or 0
    risks = [
        ("No dependency cycles were detected, so the call graph can be read in one pass."
         if not cyclic else
         f"{_count(cyclic, 'symbol')} sit in dependency cycles; the cluster section names them."),
        (f"{_count(dynamic, 'site')} {'uses' if dynamic == 1 else 'use'} dynamic dispatch, "
         "where the target is decided at runtime and static resolution cannot see it."
         if dynamic else "No dynamic dispatch sites were found, so every call target is static."),
        (f"Test surface: {_count(tests, 'test function')} against {_count(production, 'production function')}."
         if production else f"Test surface: {_count(tests, 'test function')}."),
    ]
    parts.append('<h4>Where the risk sits</h4>')
    parts.append("<ul>" + "".join(f"<li>{esc_text(r)}</li>" for r in risks) + "</ul>")

    starters: list[str] = []
    for flow in (model.get("flows") or [])[:2]:
        chain = " -> ".join(str(step.get("name")) for step in flow.get("chain") or [])
        if chain:
            starters.append(f"follow <code>{esc_text(flow.get('entry') or 'entry')}</code>: "
                            f"<span class='mono'>{esc_text(chain)}</span>")
    if not starters:
        for entry in d["entries"][:2]:
            starters.append(f"start at <code>{esc_text(entry.get('name') or '')}</code> "
                            f"({esc_text(entry.get('file_path') or '')})")
    if hubs:
        fan_in = int(hubs[0].get("fan_in") or 0)
        starters.append(
            f"read <code>{esc_text(hubs[0].get('name') or '')}</code> first: "
            f"{_count(fan_in, 'caller')} {'depends' if fan_in == 1 else 'depend'} on it"
        )
    if starters:
        parts.append('<h4>Where to start reading</h4>')
        parts.append("<ol>" + "".join(f"<li>{item}.</li>" for item in starters) + "</ol>")

    return chr(10).join(parts)


_LANGUAGE_NAMES = {
    "typescript": "TypeScript", "javascript": "JavaScript", "tsx": "TSX", "jsx": "JSX",
    "csharp": "C#", "cpp": "C++", "c": "C", "go": "Go", "java": "Java",
    "python": "Python", "ruby": "Ruby", "rust": "Rust", "php": "PHP", "swift": "Swift",
    "kotlin": "Kotlin", "sql": "SQL", "html": "HTML", "css": "CSS", "shell": "Shell",
    "json": "JSON", "yaml": "YAML", "markdown": "Markdown",
}


def _join_words(items: Iterable[str], conjunction: str = "and") -> str:
    """Join with a conjunction: 'a', 'a and b', 'a, b and c'."""
    words = [w for w in items if w]
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + f" {conjunction} " + words[-1]


def language_list(names: Iterable[str]) -> str:
    """Readable, correctly capitalised language names: 'Go, Python and TypeScript'."""
    return _join_words(
        _LANGUAGE_NAMES.get(str(n).lower(), str(n).capitalize()) for n in names
    )


_NUMBER_WORDS = {0: "no", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
                 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def _number_word(value: Any) -> str:
    """Small counts as words, larger counts as grouped digits."""
    number = int(value or 0)
    return _NUMBER_WORDS.get(number, f"{number:,}")


def _count(value: Any, noun: str) -> str:
    """Small numbers read better as words, and singular/plural must agree."""
    number = int(value or 0)
    if number == 0:
        return f"no {noun}s"
    return f"{_number_word(number)} {noun if number == 1 else noun + 's'}"


def _plural(value: Any, singular: str, plural: str = "") -> str:
    """Grouped digits with matching agreement: '1 caller', '3 callers'."""
    number = int(value or 0)
    return f"{number:,} {singular if number == 1 else (plural or singular + 's')}"


def esc_text(value: Any) -> str:
    """Escape for HTML; kept local so insights.py stays importable on its own."""
    import html as _html
    return _html.escape(str(value if value is not None else ""))


def deterministic_story(model: dict[str, Any]) -> list[dict[str, str]]:
    d = story_digest(model)
    s = d["stats"]
    symbols = {x["id"]: x for x in model.get("symbols", [])}
    clusters = model.get("clusters", {}) or {}
    chapters: list[dict[str, str]] = []

    # 1 - orientation. The counts are already on the cover and in the tiles, so
    # this chapter names the layout instead of repeating them.
    chapters.append({
        "title": "1. What this system is",
        "content": (
            (f"The work is split across these modules: {_join_words(d['modules'][:6])}. "
             if d["modules"] else "The code does not break into named modules. ")
            + f"It is written in {language_list(d['languages']) or 'an unrecognised language set'}, "
              "and the entry points below show where execution enters it."
        ),
    })

    # 2 - flows
    flow_lines = []
    for flow in (model.get("flows") or [])[:3]:
        chain = " -> ".join(n["name"] for n in flow.get("chain", []))
        flow_lines.append(f"{flow.get('entry')}: {chain} ({flow.get('file')})")
    chapters.append({
        "title": "2. How execution moves",
        "content": (
            "Resolved call chains from entry points:\n" + "\n".join(flow_lines)
            if flow_lines else
            "No entry-point chains resolved; the call graph is library-style with no "
            "single main entry, so read the highest fan-in routines first."
        ),
    })

    # 3 - hubs. A fan-in of one says nothing, so those routines are dropped
    # whenever there are routines with real reach to talk about instead.
    strong = [h for h in d["hubs"] if int(h.get("fan_in") or 0) >= 2] or d["hubs"]
    hub_lines = [
        f"{h['name']} - {_plural(h['fan_in'], 'caller')}, "
        f"{_number_word(h['cross_file'])} cross-file, complexity {h['complexity']}, {h['file']}"
        for h in strong
    ]
    chapters.append({
        "title": "3. Where the logic concentrates",
        "content": "Highest-impact routines by fan-in and complexity:\n" + "\n".join(hub_lines)
        if hub_lines else "No function hubs were identified in this repository.",
    })

    # 4 - state & integrations
    services = int(s.get("services") or 0)
    route_names = [
        f"{r.get('method', '')} {r.get('path', '')}".strip()
        for r in (model.get("layers", {}) or {}).get("routes", [])[:6]
    ]
    model_names = [m.get("name", "") for m in (model.get("layers", {}) or {}).get("models", [])[:6]]
    chapters.append({
        "title": "4. State and integrations",
        "content": (
            f"Detected {_count(s.get('models'), 'data model')}"
            + (f": {', '.join(n for n in model_names if n)}." if model_names else ".")
            + (f" Route definitions include {', '.join(route_names)}." if route_names else "")
            + f" {_count(services, 'outbound service call')} "
            + ("was found." if services == 1 else "were found.")
        ),
    })

    # 5 - risk & reading order
    scc_count = len(clusters.get("sccs") or [])
    dynamic_ids = clusters.get("dynamic") or []
    dynamic_names = [symbols[i]["name"] for i in dynamic_ids[:6] if i in symbols]
    chapters.append({
        "title": "5. Risk and reading order",
        "content": (
            f"{_count(scc_count, 'circular dependency group')} and "
            f"{_count(len(dynamic_ids), 'dynamic-dispatch symbol')} were detected"
            + (f" (for example {', '.join(dynamic_names)})" if dynamic_names else "")
            + ". Read in this order: entry points, then the hubs in chapter 3, then the "
              "data models. Treat cycles and dynamic nodes as high-risk for refactoring."
        ),
    })
    return chapters


def deterministic_roadmap(model: dict[str, Any]) -> list[str]:
    """Ordered modernization steps, each traceable to evidence in the model."""
    d = story_digest(model)
    s = d["stats"]
    counts = (model.get("clusters", {}) or {}).get("counts", {}) or {}
    symbols = {x["id"]: x for x in model.get("symbols", [])}
    steps: list[str] = []

    cyclic = int(counts.get("cyclic") or 0)
    if cyclic:
        steps.append(
            f"Break the {_count(cyclic, 'symbol')} sitting in dependency cycles (the risk register "
            "names the groups) before any extraction or parallel work: mutually recursive code "
            "cannot be changed safely in isolation."
        )
    dynamic = int(counts.get("dynamic") or 0)
    if dynamic:
        steps.append(
            f"Replace dynamic dispatch at the {_count(dynamic, 'flagged site')} with static factories "
            "or explicit registries, so the call graph can verify those edges instead of guessing."
        )
    hotspots = sorted(
        (sym for sym in symbols.values()
         if sym.get("kind") in ("function", "method") and int(sym.get("complexity") or 0) >= 12),
        key=lambda sym: (-int(sym.get("complexity") or 0), sym["id"]),
    )[:3]
    if hotspots:
        names = ", ".join(str(sym.get("qualified") or sym.get("name")) for sym in hotspots)
        steps.append(
            f"Refactor the complexity hotspots first ({names}): high-branching routines "
            "concentrate defects and resist safe change."
        )
    production = int(s.get("production_functions") or 0)
    tests = int(s.get("test_functions") or 0)
    if production and (tests == 0 or tests / max(production, 1) < 0.15):
        steps.append(
            f"Raise the test surface ({_count(tests, 'test function')} against "
            f"{_count(production, 'production function')}) around the highest fan-in routines "
            "before refactoring them."
        )
    entries = int(s.get("entry_points") or 0)
    if entries:
        steps.append(
            f"Add integration checks around the {_count(entries, 'entry point')}: execution enters "
            "the system there and regressions surface there first."
        )
    unresolved = int(s.get("unresolved_call_names") or 0)
    if unresolved:
        steps.append(
            f"Map the {_count(unresolved, 'unresolved call name')}: calls the model cannot verify, "
            "each one a hidden breakage risk during modernization."
        )
    if not steps:
        steps.append(
            "No structural hazards were detected in this model; keep the current module "
            "boundaries and re-index after large changes."
        )
    return steps[:MAX_ROADMAP_ITEMS]


def _narrative_from_providers(
    self: "InsightService", model: dict[str, Any],
    bob_command: Optional[str], llm_url: Optional[str], llm_model: Optional[str],
) -> tuple[dict[str, Any], str, str]:
    """Ask the live providers for the repository narrative, first available wins."""
    digest = story_digest(model)
    for provider in self.providers(bob_command, llm_url, llm_model):
        if isinstance(provider, DeterministicProvider) or not provider.available():
            continue
        try:
            result = provider.generate_narrative(digest)
        except ProviderUnavailable:
            continue
        except Exception:  # a provider crash degrades, never fails the build
            continue
        return result.items, result.source, result.model
    return {}, "derived", ""


_NARRATIVE_KEYS = ("exec_summary", "story", "roadmap")


def _ensure_narratives(
    self: "InsightService", model: dict[str, Any],
    bob_command: Optional[str] = None, llm_url: Optional[str] = None,
    llm_model: Optional[str] = None,
) -> dict[str, Any]:
    """Repo-level prose for the dossier: AI when a provider answers, derived otherwise.

    The bundle is cached by narrative hash. Deterministic text is upgraded to
    provider text as soon as one becomes available (the same rule the symbol
    insights follow); provider text is never regenerated while it is current.
    """
    input_hash = narrative_hash(model)
    cached = {key: self.cache.get_narrative_entry(key, input_hash) for key in _NARRATIVE_KEYS}
    live = [p for p in self.providers(bob_command, llm_url, llm_model)
            if not isinstance(p, DeterministicProvider)]
    live_available = any(p.available() for p in live)

    complete = all(entry is not None for entry in cached.values())
    needs_generation = not complete or (
        live_available
        and any(str(entry.get("source") or "derived") not in ("bob", "llm") for entry in cached.values())
    )

    if not needs_generation:
        return {
            "exec_summary": (cached["exec_summary"] or {}).get("text") or "",
            "story": json.loads((cached["story"] or {}).get("text") or "[]"),
            "roadmap": json.loads((cached["roadmap"] or {}).get("text") or "[]"),
            "source": (cached["exec_summary"] or {}).get("source") or "derived",
            "story_source": (cached["story"] or {}).get("source") or "derived",
            "roadmap_source": (cached["roadmap"] or {}).get("source") or "derived",
            "model": (cached["exec_summary"] or {}).get("model") or "",
            "generated_at": (cached["exec_summary"] or {}).get("generated_at") or "",
            "input_hash": input_hash,
        }

    payload, source, model_name = self._narrative_from_providers(
        model, bob_command, llm_url, llm_model
    )
    exec_summary = str(payload.get("exec_summary") or "") or deterministic_exec_summary(model)
    story = payload.get("story") or deterministic_story(model)
    roadmap = payload.get("roadmap") or deterministic_roadmap(model)
    exec_source = source if payload.get("exec_summary") else "derived"
    story_source = source if payload.get("story") else "derived"
    roadmap_source = source if payload.get("roadmap") else "derived"
    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    self.cache.set_narrative("exec_summary", exec_summary, input_hash, exec_source, model_name)
    self.cache.set_narrative("story", json.dumps(story, ensure_ascii=False), input_hash, story_source, model_name)
    self.cache.set_narrative("roadmap", json.dumps(roadmap, ensure_ascii=False), input_hash, roadmap_source, model_name)
    self.cache.save()
    return {
        "exec_summary": exec_summary,
        "story": story,
        "roadmap": roadmap,
        "source": exec_source,
        "story_source": story_source,
        "roadmap_source": roadmap_source,
        "model": model_name,
        "generated_at": generated_at,
        "input_hash": input_hash,
    }


InsightService.ensure_narratives = _ensure_narratives  # type: ignore[attr-defined]
InsightService._narrative_from_providers = _narrative_from_providers  # type: ignore[attr-defined]
