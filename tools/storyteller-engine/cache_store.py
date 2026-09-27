"""
cache_store.py
~~~~~~~~~~~~~~
Content-addressed cache for the Architecture Storyteller engine.

Layout (default `<repo>/.storyteller/`, overridable):

    manifest.json     symbol content hashes from the last successful index
    insights.json     per-symbol micro summary + rationale, keyed by symbol id
    narratives.json   repo-level prose keyed by an input hash
    meta.json         last index time, fingerprint, engine version

The cache is what makes live AI practical: every insight is keyed by
`hash(symbol code) + hash(dependencies) + prompt version`, so a re-index only
asks the provider about symbols that were added or changed, deletes entries for
removed symbols, and serves everything else from disk. Nothing is ever invented
to fill a gap - an entry records whether it came from a provider or the
deterministic fallback.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

CACHE_DIRNAME = ".storyteller"
CACHE_VERSION = 2

# Bump when the provider prompt contract changes so cached AI text is regenerated.
PROMPT_VERSION = "insights-v1"


def _sha(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:20]


def insight_key(content_hash: str, deps_hash: str) -> str:
    return _sha(f"{PROMPT_VERSION}|{content_hash}|{deps_hash}")


def load_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class StorytellerCache:
    """Reads/writes the `.storyteller` cache for one repository."""

    def __init__(self, repo: str | Path, cache_dir: str | Path | None = None):
        self.repo = Path(repo).resolve()
        self.dir = Path(cache_dir).resolve() if cache_dir else self.repo / CACHE_DIRNAME
        self.manifest: dict[str, Any] = {}
        self.insights: dict[str, dict[str, Any]] = {}
        self.narratives: dict[str, dict[str, Any]] = {}
        self.meta: dict[str, Any] = {}
        self._dirty_insights = False
        self._dirty_narratives = False

    # -- paths -------------------------------------------------------------

    @property
    def manifest_path(self) -> Path:
        return self.dir / "manifest.json"

    @property
    def insights_path(self) -> Path:
        return self.dir / "insights.json"

    @property
    def narratives_path(self) -> Path:
        return self.dir / "narratives.json"

    @property
    def meta_path(self) -> Path:
        return self.dir / "meta.json"

    # -- loading -----------------------------------------------------------

    def load(self) -> "StorytellerCache":
        self.manifest = load_json(self.manifest_path, {})
        self.insights = load_json(self.insights_path, {})
        self.narratives = load_json(self.narratives_path, {})
        self.meta = load_json(self.meta_path, {})
        if self.meta.get("cache_version") != CACHE_VERSION:
            # Format changed: keep nothing stale.
            self.manifest = {}
            self.insights = {}
            self.narratives = {}
        return self

    def exists(self) -> bool:
        return self.manifest_path.is_file()

    # -- delta -------------------------------------------------------------

    def compute_delta(self, new_manifest: dict[str, Any]) -> dict[str, Any]:
        old_symbols = (self.manifest or {}).get("symbols") or {}
        new_symbols = (new_manifest or {}).get("symbols") or {}

        added, changed, unchanged = [], [], []
        for sid, entry in new_symbols.items():
            previous = old_symbols.get(sid)
            if previous is None:
                added.append(sid)
            elif (previous.get("hash") != entry.get("hash")
                    or previous.get("deps_hash") != entry.get("deps_hash")):
                changed.append(sid)
            else:
                unchanged.append(sid)
        removed = [sid for sid in old_symbols if sid not in new_symbols]

        old_fp = (self.manifest or {}).get("fingerprint")
        new_fp = (new_manifest or {}).get("fingerprint")
        return {
            "added": sorted(added),
            "changed": sorted(changed),
            "removed": sorted(removed),
            "unchanged": sorted(unchanged),
            "fingerprint_changed": bool(self.manifest) and old_fp != new_fp,
            "first_run": not bool(self.manifest),
            "counts": {
                "added": len(added), "changed": len(changed),
                "removed": len(removed), "unchanged": len(unchanged),
            },
        }

    # -- insights ----------------------------------------------------------

    def get_insight(self, symbol_id: str, content_hash: str, deps_hash: str) -> Optional[dict[str, Any]]:
        entry = self.insights.get(symbol_id)
        if not entry:
            return None
        if entry.get("key") != insight_key(content_hash, deps_hash):
            return None
        return entry

    def put_insight(self, symbol_id: str, entry: dict[str, Any]) -> None:
        self.insights[symbol_id] = entry
        self._dirty_insights = True

    def prune_insights(self, valid_ids: set[str]) -> int:
        stale = [sid for sid in self.insights if sid not in valid_ids]
        for sid in stale:
            del self.insights[sid]
        if stale:
            self._dirty_insights = True
        return len(stale)

    def insight_count(self) -> int:
        return len(self.insights)

    def source_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.insights.values():
            src = str(entry.get("source") or "unknown")
            counts[src] = counts.get(src, 0) + 1
        return counts

    # -- narratives --------------------------------------------------------

    def get_narrative_entry(self, key: str, input_hash: str) -> Optional[dict[str, Any]]:
        """Full stored entry (text + source/model/stamp) when the hash matches."""
        entry = self.narratives.get(key)
        if not entry or entry.get("input_hash") != input_hash:
            return None
        return entry

    def get_narrative(self, key: str, input_hash: str) -> Optional[str]:
        entry = self.get_narrative_entry(key, input_hash)
        return entry.get("text") if entry else None

    def set_narrative(self, key: str, text: str, input_hash: str, source: str,
                      model: str = "") -> None:
        self.narratives[key] = {
            "text": text,
            "input_hash": input_hash,
            "source": source,
            "model": model,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self._dirty_narratives = True

    # -- persistence -------------------------------------------------------

    def save(self, manifest: dict[str, Any] | None = None) -> None:
        if manifest is not None:
            self.manifest = manifest
            self.meta = {
                "cache_version": CACHE_VERSION,
                "prompt_version": PROMPT_VERSION,
                "last_index_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "fingerprint": manifest.get("fingerprint", ""),
            }
        if manifest is not None or self.meta:
            save_json_atomic(self.meta_path, self.meta)
        if manifest is not None:
            save_json_atomic(self.manifest_path, self.manifest)
        if self._dirty_insights:
            save_json_atomic(self.insights_path, self.insights)
            self._dirty_insights = False
        if self._dirty_narratives:
            save_json_atomic(self.narratives_path, self.narratives)
            self._dirty_narratives = False

    def save_insights(self) -> None:
        if self._dirty_insights:
            save_json_atomic(self.insights_path, self.insights)
            self._dirty_insights = False
