"""
engine_server.py
~~~~~~~~~~~~~~~~
Long-lived engine process for Architecture Storyteller 2.0.

One `StorytellerEngine` owns the repository model, the insight cache and the
dossier builder. It is exposed two ways:

* as a Python API for `cli.py` (index / dossier / context / usages / delta), and
* as a small HTTP service for the IDE extension, so a hover or a click never has
  to spawn a Python process per interaction.

Endpoints (localhost only by default):

    GET  /health                 engine + cache state
    GET  /stats                  repository statistics
    GET  /model[?full=1]         full model, or the compact tree payload
    GET  /tree                   compact payload for the interactive map
    GET  /context?symbol=<name>  symbol, callers, callees, insight, source
    GET  /usages?symbol=<name>   every resolved call site of a symbol
    GET  /delta                  cache delta since the last index
    POST /index                  rebuild model + insights, return the report
    GET  /dossier?level=1|2|3    dossier HTML (text/html)
    POST /dossier {level, pdf}   dossier HTML, or render the PDF with Chromium

The model is rebuilt only when the working tree actually changed, and insights
are regenerated per symbol content hash, so repeated calls stay cheap.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent
for _extra in (_HERE, _HERE.parent / "py-ast-core"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from cache_store import StorytellerCache  # noqa: E402
from dossier import LEVELS, build_dossier  # noqa: E402
from insights import InsightService  # noqa: E402
from model_builder import (  # noqa: E402
    SOURCE_EXTENSIONS,
    build_model,
    manifest_from_model,
    read_symbol_source,
    tree_payload,
)
from scan_filter import collect_files  # noqa: E402

DEFAULT_LANGUAGES = ["python", "typescript", "javascript", "go"]
RENDER_SCRIPT = _PROJECT_ROOT / "scripts" / "render_pdf.mjs"


class SymbolLookupError(LookupError):
    """Raised when a symbol cannot be resolved uniquely."""


def _brief(symbol: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": symbol.get("id"),
        "name": symbol.get("name"),
        "qualified": symbol.get("qualified"),
        "kind": symbol.get("kind"),
        "file": symbol.get("file_path"),
        "line": symbol.get("line_start"),
        "end": symbol.get("line_end"),
    }


class StorytellerEngine:
    """Owns the model, the cache and the dossier for one repository."""

    def __init__(
        self,
        repo: str | Path,
        cache_dir: str | Path | None = None,
        languages: Optional[list[str]] = None,
        staleness_seconds: float = 1.5,
    ) -> None:
        self.repo = Path(repo).resolve()
        if not self.repo.is_dir():
            raise FileNotFoundError(f"Not a directory: {self.repo}")
        self.languages = list(languages or DEFAULT_LANGUAGES)
        self.cache = StorytellerCache(self.repo, cache_dir=cache_dir)
        self.service = InsightService(self.repo, self.cache)
        self.staleness_seconds = staleness_seconds
        self.last_index: dict[str, Any] = {}
        self.build_seconds = 0.0

        self._model: Optional[dict[str, Any]] = None
        self._lock = threading.RLock()
        # Dossier building touches module-level render state (_TOC) and writes
        # shared output files, so concurrent /dossier requests must not
        # interleave: one build at a time, reentrant because render_pdf calls
        # dossier_html.
        self._dossier_lock = threading.RLock()
        self._built_at = 0.0
        self._checked_at = 0.0
        self._tree_state: tuple = ()

    # -- tree state --------------------------------------------------------

    def _tree_state_now(self) -> tuple[float, tuple]:
        files = collect_files(self.repo, SOURCE_EXTENSIONS, include_tests=True,
                              include_engine_source=True)
        newest = 0.0
        state: list[tuple[str, int, int]] = []
        for path in files:
            try:
                stat = path.stat()
                relative = str(path.relative_to(self.repo)).replace("\\", "/")
            except (OSError, ValueError):
                continue
            newest = max(newest, stat.st_mtime)
            state.append((relative, stat.st_mtime_ns, stat.st_size))
        return newest, tuple(sorted(state))

    def stale(self) -> bool:
        """True when the working tree changed since the model was built."""
        if self._model is None:
            return True
        now = time.time()
        if now - self._checked_at < self.staleness_seconds:
            return False
        self._checked_at = now
        newest, state = self._tree_state_now()
        return newest > self._built_at or state != self._tree_state

    # -- model -------------------------------------------------------------

    def ensure_model(self, force: bool = False) -> dict[str, Any]:
        with self._lock:
            if force or self._model is None or self.stale():
                started = time.time()
                self._model = build_model(self.repo, self.languages)
                self._built_at = time.time()
                self.build_seconds = round(self._built_at - started, 3)
                newest, state = self._tree_state_now()
                self._tree_state = state
                self._checked_at = self._built_at
                self._model["_build_seconds"] = self.build_seconds
            return self._model

    def model(self, full: bool = True) -> dict[str, Any]:
        return self.ensure_model() if full else tree_payload(self.ensure_model())

    def tree(self) -> dict[str, Any]:
        return tree_payload(self.ensure_model())

    def stats(self) -> dict[str, Any]:
        model = self.ensure_model()
        return {
            "repo": model["repo"]["name"],
            "root": model["repo"]["root"],
            "schema": model["schema"],
            "generated_at": model["generated_at"],
            "build_seconds": self.build_seconds,
            "stats": model["stats"],
            "fingerprint": model["repo"].get("fingerprint"),
        }

    # -- indexing ----------------------------------------------------------

    def index(self, force: bool = False, force_insights: bool = False,
              bob_command: Optional[str] = None, llm_url: Optional[str] = None,
              llm_model: Optional[str] = None) -> dict[str, Any]:
        with self._lock:
            model = self.ensure_model(force=force)
            delta = self.cache.compute_delta(manifest_from_model(model))
            report = self.service.ensure(
                model,
                bob_command=bob_command,
                llm_url=llm_url,
                llm_model=llm_model,
                force=force_insights,
            )
            self.last_index = {
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "delta": delta["counts"],
                "fingerprint_changed": delta["fingerprint_changed"],
                "first_run": delta["first_run"],
                "generated": report["generated"],
                "removed": report["removed"],
                "provider": report["provider"],
                "providers_available": report.get("providers_available", []),
                "sources": report["sources"],
                "cached_total": report["cached_total"],
            }
            return {**self.last_index, "stats": model["stats"]}

    def delta(self) -> dict[str, Any]:
        return self.cache.compute_delta(manifest_from_model(self.ensure_model()))

    # -- symbol operations -------------------------------------------------

    def find_symbol(self, needle: str) -> dict[str, Any]:
        if not needle or not str(needle).strip():
            raise SymbolLookupError("symbol is required")
        query = str(needle).strip()
        lowered = query.lower()
        symbols = self.ensure_model().get("symbols") or []

        exact = [s for s in symbols if s.get("id") == query]
        if exact:
            return exact[0]
        qualified = [s for s in symbols if (s.get("qualified") or "").lower() == lowered]
        if len(qualified) == 1:
            return qualified[0]
        by_name = [s for s in symbols if (s.get("name") or "").lower() == lowered]
        if len(by_name) == 1:
            return by_name[0]
        suffix = [s for s in symbols if (s.get("qualified") or "").lower().endswith(lowered)]
        if len(suffix) == 1:
            return suffix[0]

        ambiguous = by_name or suffix
        if ambiguous:
            options = ", ".join(sorted(s["id"] for s in ambiguous)[:8])
            raise SymbolLookupError(f"ambiguous symbol {query!r}; candidates: {options}")
        raise SymbolLookupError(f"symbol not found: {query}")

    def _symbol_maps(self) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        model = self.ensure_model()
        return model, {s["id"]: s for s in model.get("symbols") or []}

    def context(self, needle: str, lines: int = 40) -> dict[str, Any]:
        model, by_id = self._symbol_maps()
        symbol = self.find_symbol(needle)
        flows = [
            flow for flow in (model.get("flows") or [])
            if any(node.get("id") == symbol["id"] for node in flow.get("chain") or [])
        ][:3]
        return {
            "schema": model["schema"],
            "repo": model["repo"]["name"],
            "symbol": {
                **_brief(symbol),
                "complexity": symbol.get("complexity"),
                "flags": symbol.get("flags") or [],
                "doc": symbol.get("doc") or "",
                "language": symbol.get("language") or "",
                "source_kind": symbol.get("source") or "ast",
                "is_test": bool(symbol.get("is_test")),
                "private": bool(symbol.get("private")),
                "exported": bool(symbol.get("exported")),
            },
            "callers": [_brief(by_id[c]) for c in symbol.get("callers") or [] if c in by_id],
            "calls": [_brief(by_id[c]) for c in symbol.get("calls") or [] if c in by_id],
            "children": [_brief(by_id[c]) for c in symbol.get("children") or [] if c in by_id],
            "parent": _brief(by_id[symbol["parent"]]) if symbol.get("parent") in by_id else None,
            "insight": self.service.get(symbol["id"]) or {},
            "flows": [
                {"entry": flow.get("entry"), "kind": flow.get("kind"),
                 "chain": [node.get("name") for node in flow.get("chain") or []]}
                for flow in flows
            ],
            # lines=0 means "no source" (the CLI documents it and the hover
            # asks for it), so the clamp is 0-based, not 1-based.
            "source": read_symbol_source(self.repo, symbol, max_lines=max(0, int(lines))),
        }

    def usages(self, needle: str) -> dict[str, Any]:
        _, by_id = self._symbol_maps()
        symbol = self.find_symbol(needle)
        callers = []
        for caller_id in symbol.get("callers") or []:
            caller = by_id.get(caller_id)
            if not caller:
                continue
            raw_calls = [
                raw for raw in caller.get("raw_calls") or []
                if raw.split("(")[0].strip().split(".")[-1] == symbol.get("name")
            ]
            callers.append({**_brief(caller), "raw_calls": raw_calls[:5]})
        return {
            "symbol": _brief(symbol),
            "call_site_count": len(callers),
            "callers": callers,
        }

    # -- dossier -----------------------------------------------------------

    def dossier_html(self, level: int = 2, bob_command: Optional[str] = None,
                     llm_url: Optional[str] = None, llm_model: Optional[str] = None) -> str:
        with self._dossier_lock:
            model = self.ensure_model()
            level = 3 if int(level) >= 3 else (1 if int(level) <= 1 else 2)
            if bob_command or llm_url:
                # A live provider is configured: let it write the symbol
                # summaries and the narrative before the document is built.
                with self._lock:
                    self.service.ensure(model, bob_command=bob_command,
                                        llm_url=llm_url, llm_model=llm_model)
            narratives = self.service.ensure_narratives(model, bob_command, llm_url, llm_model)
            delta = self.cache.compute_delta(manifest_from_model(model))
            return build_dossier(model, level, self.service, narratives, root=self.repo, delta=delta)

    def render_pdf(self, level: int = 2, output: Optional[str] = None,
                   bob_command: Optional[str] = None, llm_url: Optional[str] = None,
                   llm_model: Optional[str] = None) -> dict[str, Any]:
        with self._dossier_lock:
            html = self.dossier_html(level, bob_command, llm_url, llm_model)
            out_dir = Path(output).parent if output else self.repo / "output"
            out_dir.mkdir(parents=True, exist_ok=True)
            html_path = out_dir / f"dossier-L{level}.html"
            html_path.write_text(html, encoding="utf-8")
            pdf_path = Path(output) if output else out_dir / f"dossier-L{level}.pdf"
            if not RENDER_SCRIPT.is_file():
                raise FileNotFoundError(f"renderer not found: {RENDER_SCRIPT}")
            proc = subprocess.run(
                ["node", str(RENDER_SCRIPT), "--input", str(html_path), "--output", str(pdf_path)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
            )
            if proc.returncode != 0 or not pdf_path.is_file():
                raise RuntimeError((proc.stderr or proc.stdout or "renderer failed").strip()[:400])
            return {
                "level": level,
                "pdf": str(pdf_path),
                "html": str(html_path),
                "bytes": pdf_path.stat().st_size,
                "pages_hint": "every page is numbered in the browser footer; sections appear as PDF bookmarks",
            }

    # -- health ------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        model = self.ensure_model()
        return {
            "ok": True,
            "repo": model["repo"]["name"],
            "root": model["repo"]["root"],
            "schema": model["schema"],
            "build_seconds": self.build_seconds,
            "stats": model["stats"],
            "cache": {
                "insights": self.cache.insight_count(),
                "sources": self.cache.source_counts(),
                "last_index": (self.cache.meta or {}).get("last_index_at", ""),
            },
            "last_index": self.last_index,
            "levels": {str(level): name for level, name in LEVELS.items()},
        }


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    engine: StorytellerEngine
    server_version = "StorytellerEngine/2.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # keep stdout clean by default
        if os.environ.get("STORYTELLER_HTTP_LOG"):
            super().log_message(fmt, *args)

    # -- helpers -----------------------------------------------------------

    def _send(self, payload: Any, status: int = 200, content_type: str = "application/json") -> None:
        if isinstance(payload, str):
            body = payload.encode("utf-8")
        else:
            body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        origin = self.headers.get("Origin") or ""
        if not origin or origin.startswith(("http://127.0.0.1", "http://localhost", "vscode-webview://", "vscode-file://")):
            self.send_header("Access-Control-Allow-Origin", origin or "*")
            self.send_header("Access-Control-Allow-Headers", "content-type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length <= 0 or length > 50 * 1024 * 1024:  # 50MB maximum body
            return {}
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, UnicodeDecodeError):
            return {}

    # -- verbs -------------------------------------------------------------

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send("", 204, "text/plain")

    def do_GET(self) -> None:  # noqa: N802
        self._route("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._route("POST")

    def _route(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        one = lambda key, default="": (query.get(key) or [default])[0]  # noqa: E731
        flag = lambda key: str(one(key, "")).lower() in ("1", "true", "yes")  # noqa: E731

        try:
            if path in ("/", "/health"):
                return self._send(self.engine.health())
            if path == "/stats":
                return self._send(self.engine.stats())
            if path == "/model":
                return self._send(self.engine.model(full=flag("full")))
            if path == "/tree":
                return self._send(self.engine.tree())
            if path == "/context":
                raw_lines = one("lines", "40")
                try:
                    lines = max(0, min(10000, int(raw_lines)))
                except ValueError:
                    lines = 40
                sym_needle = one("symbol")[:1000]
                return self._send(self.engine.context(sym_needle, lines))
            if path == "/usages":
                sym_needle = one("symbol")[:1000]
                return self._send(self.engine.usages(sym_needle))
            if path == "/delta":
                return self._send(self.engine.delta())
            if path == "/index":
                if method != "POST":
                    return self._send({"error": "POST required"}, 405)
                body = self._body()
                llm_url = str(body.get("llm_url") or "").strip() or None
                if llm_url and not (llm_url.startswith("http://") or llm_url.startswith("https://")):
                    return self._send({"error": "Invalid llm_url protocol"}, 400)
                return self._send(self.engine.index(
                    force=bool(body.get("force")),
                    force_insights=bool(body.get("force_insights")),
                    bob_command=body.get("bob_command") or None,
                    llm_url=llm_url,
                    llm_model=body.get("llm_model") or None,
                ))
            if path == "/dossier":
                body = self._body() if method == "POST" else {}
                level = int(body.get("level") or one("level", "2") or 2)
                wants_pdf = bool(body.get("pdf")) or flag("pdf")
                # Provider settings ride along so the exported dossier can be
                # written by Bob / the local LLM, same as the index report.
                bob_command = body.get("bob_command") or None
                llm_url = str(body.get("llm_url") or "").strip() or None
                if llm_url and not (llm_url.startswith("http://") or llm_url.startswith("https://")):
                    return self._send({"error": "Invalid llm_url protocol"}, 400)
                llm_model = body.get("llm_model") or None
                if wants_pdf:
                    return self._send(self.engine.render_pdf(
                        level, body.get("output") or None,
                        bob_command=bob_command, llm_url=llm_url, llm_model=llm_model))
                if str(one("format", "html")).lower() == "json":
                    html = self.engine.dossier_html(level, bob_command, llm_url, llm_model)
                    return self._send({"level": level, "html": html, "bytes": len(html)})
                return self._send(self.engine.dossier_html(level, bob_command, llm_url, llm_model),
                                  200, "text/html")
            return self._send({"error": f"unknown route: {path}"}, 404)
        except SymbolLookupError as exc:
            return self._send({"error": str(exc), "kind": "symbol"}, 404)
        except FileNotFoundError as exc:
            return self._send({"error": str(exc), "kind": "path"}, 400)
        except ValueError as exc:
            return self._send({"error": str(exc), "kind": "request"}, 400)
        except Exception as exc:  # never kill the server for one bad request
            return self._send({"error": f"{type(exc).__name__}: {exc}"}, 500)


# ---------------------------------------------------------------------------
# Parent watchdog
# ---------------------------------------------------------------------------

def _emit(payload: dict[str, Any]) -> None:
    """Log an event to stdout, tolerating a closed pipe.

    The consumer of this stdout is the parent process. Once the parent is gone
    its end of the pipe is closed and writing raises, so every watchdog message
    goes through here: a failed log line must never abort the shutdown.
    """
    try:
        print(json.dumps(payload), flush=True)
    except Exception:
        pass

def _watch_windows(watched_pid: int, on_exit: Callable[[], None]) -> bool:
    """Block on the parent's process handle and fire as soon as it is signalled."""
    import ctypes
    from ctypes import wintypes

    SYNCHRONIZE = 0x00100000
    INFINITE = 0xFFFFFFFF
    ERROR_INVALID_PARAMETER = 87

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # Declare the prototypes: without argtypes ctypes passes INFINITE as a signed
    # int, which raises OverflowError inside the watchdog thread (dying quietly
    # while the engine keeps running) and truncates the 64-bit process HANDLE.
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD

    handle = kernel32.OpenProcess(SYNCHRONIZE, False, watched_pid)
    if not handle:
        # ERROR_INVALID_PARAMETER means there is no such process: already orphaned.
        if ctypes.get_last_error() == ERROR_INVALID_PARAMETER:
            on_exit()
            return True
        return False

    def _wait() -> None:
        # Returns when the parent process becomes signalled, i.e. when it exits.
        try:
            kernel32.WaitForSingleObject(handle, INFINITE)
            on_exit()
        except Exception as exc:  # a dead watchdog must be visible, not silent
            _emit({"event": "parent-watch-error", "error": repr(exc)})

    threading.Thread(target=_wait, name="parent-watchdog", daemon=True).start()
    return True


def _watch_posix(watched_pid: int, on_exit: Callable[[], None], interval: float) -> bool:
    """Poll: a dead parent reparents us, so getppid() stops matching."""
    if os.getppid() != watched_pid:
        # Spawned through something else: this pid is not our parent, so watching
        # it would fire immediately and wrongly.
        return False

    def _poll() -> None:
        try:
            while True:
                if os.getppid() != watched_pid:
                    on_exit()
                    return
                time.sleep(interval)
        except Exception as exc:  # a dead watchdog must be visible, not silent
            _emit({"event": "parent-watch-error", "error": repr(exc)})

    threading.Thread(target=_poll, name="parent-watchdog", daemon=True).start()
    return True


def start_parent_watchdog(on_exit: Callable[[], None],
                          parent_pid: Optional[int] = None,
                          interval: float = 2.0) -> bool:
    """Stop the engine when the process that spawned it goes away.

    The IDE extension runs the engine as a child of its extension host. A normal
    shutdown disposes the client, which kills this process, but a crashed or
    force-killed host runs no dispose path at all: without this watchdog the
    engine keeps a repository indexed and an HTTP port bound forever.

    Returns True when a watchdog was installed. Explicitly requested pids are
    honoured as-is; the default watches this process's own parent.
    """
    try:
        watched = parent_pid if parent_pid else os.getppid()
    except Exception:
        return False
    if not watched or watched <= 0:
        return False
    try:
        if sys.platform == "win32":
            return _watch_windows(watched, on_exit)
        return _watch_posix(watched, on_exit, interval)
    except Exception:
        return False


def serve(engine: StorytellerEngine, port: int = 8003, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    """Start the HTTP engine. Returns the server (already serving) for tests."""
    handler = type("BoundHandler", (_Handler,), {"engine": engine})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    if os.environ.get("STORYTELLER_SERVER_QUIET") != "1":
        actual = server.server_address[1]
        print(json.dumps({"event": "listening", "host": host, "port": actual,
                          "repo": str(engine.repo), "url": f"http://{host}:{actual}/"}), flush=True)
    return server


def run_forever(engine: StorytellerEngine, port: int = 8003, host: str = "127.0.0.1",
                index_on_start: bool = False, watch_parent: bool = False,
                parent_pid: Optional[int] = None) -> None:
    if index_on_start:
        engine.index()
    server = serve(engine, port, host)

    if watch_parent or parent_pid:
        def _on_parent_exit() -> None:
            # Order matters: announce, stop, then leave unconditionally. The
            # announce is guarded because the pipe to the dead parent is gone,
            # and os._exit guarantees we leave even if serving cannot be drained.
            _emit({"event": "parent-gone",
                   "message": "spawning process exited; stopping the engine"})
            try:
                server.shutdown()
            except Exception:
                pass
            os._exit(0)

        if not start_parent_watchdog(_on_parent_exit, parent_pid=parent_pid):
            _emit({"event": "parent-watch-unavailable",
                   "message": "could not watch the parent process"})

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
