"""Dossier rendering tests.

These assert the document contract rather than exact HTML: levels only add
sections, nothing renders emoji, AI text is labelled with its source, and a
nearly empty model still produces a valid document instead of raising.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent
for extra in (ENGINE, ENGINE.parent / "py-ast-core"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from cache_store import StorytellerCache  # noqa: E402
from dossier import build_dossier  # noqa: E402
from insights import InsightService  # noqa: E402
from model_builder import build_model  # noqa: E402

EMOJI = re.compile(r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\uFE0F]")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text(
        "from pkg import helpers\n"
        "\n"
        "\n"
        'class TripService:\n'
        '    """Coordinates trip operations."""\n'
        "\n"
        "    def load_trip(self, trip_id):\n"
        '        """Loads one trip by id."""\n'
        "        return helpers.fetch_row(trip_id)\n"
        "\n"
        "    def save_trip(self, trip_id, payload):\n"
        "        return helpers.write_row(trip_id, payload)\n"
        "\n"
        "\n"
        "def audit(event):\n"
        "    return _emit(event)\n"
        "\n"
        "\n"
        "def _emit(event):\n"
        "    return audit(event)\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "helpers.py").write_text(
        "def fetch_row(row_id):\n"
        '    """Fetches a row from storage."""\n'
        "    return {'id': row_id}\n"
        "\n"
        "\n"
        "def write_row(row_id, payload):\n"
        "    return payload\n",
        encoding="utf-8",
    )
    (tmp_path / "ui.ts").write_text(
        "/** Renders the trip card. */\n"
        "export class TripCard {\n"
        "  render(trip: Trip) {\n"
        "    return formatName(trip.name);\n"
        "  }\n"
        "}\n"
        "\n"
        "export function formatName(name: string) {\n"
        "  return name.trim();\n"
        "}\n",
        encoding="utf-8",
    )
    return tmp_path


def test_levels_only_add_content_and_never_render_emoji(repo: Path):
    model = build_model(repo)
    documents = {level: build_dossier(model, level, root=repo) for level in (1, 2, 3)}

    sizes = [len(documents[level]) for level in (1, 2, 3)]
    assert sizes[0] < sizes[1] < sizes[2], sizes

    # Level 1 is a strict subset of the deeper documents.
    for level in (1, 2):
        assert "Symbol evidence" not in documents[level]
    assert "Symbol evidence" in documents[3]
    assert "Module dependencies" not in documents[1]
    assert "Module dependencies" in documents[2]

    for level, document in documents.items():
        assert document.startswith("<!DOCTYPE html>")
        assert document.rstrip().endswith("</html>")
        assert ">None<" not in document, f"level {level} rendered a None value"
        assert not EMOJI.search(document), f"level {level} contains emoji"
        assert "Risk register" in document
        assert "Model confidence and provenance" in document


def test_level_argument_is_clamped(repo: Path):
    model = build_model(repo)
    assert build_dossier(model, 9, root=repo) == build_dossier(model, 3, root=repo)
    assert build_dossier(model, 0, root=repo) == build_dossier(model, 1, root=repo)


def test_insight_text_is_labelled_with_its_source(repo: Path):
    model = build_model(repo)
    cache = StorytellerCache(repo)
    service = InsightService(repo, cache)
    report = service.ensure(model)
    assert report["generated"] > 0

    document = build_dossier(model, 3, service, root=repo)
    assert "deterministic fallback" in document
    assert "Symbol summaries" in document

    micro = [entry["micro"] for entry in cache.insights.values()]
    assert micro, "insights were stored"
    assert all(len(m.split()) <= 5 for m in micro)


def test_narratives_are_injected_and_cached(repo: Path):
    model = build_model(repo)
    cache = StorytellerCache(repo)
    service = InsightService(repo, cache)
    service.ensure(model)
    narratives = service.ensure_narratives(model)

    document = build_dossier(model, 1, service, narratives, root=repo)
    assert "Executive summary" in document
    assert "How this system reads" in document
    assert "Source: derived from model" in document

    # A second pass reuses the cached narrative for an identical model.
    again = service.ensure_narratives(build_model(repo))
    assert again["exec_summary"] == narratives["exec_summary"]


def test_empty_model_still_produces_a_document():
    model = {
        "schema": "storyteller/architecture-model@2",
        "generated_at": "2026-01-01T00:00:00Z",
        "repo": {"root": ".", "name": "empty-repo", "fingerprint": {}},
        "meta": {"engine": "native"},
        "files": [],
        "symbols": [],
        "entry_points": [],
        "layers": {"routes": [], "models": [], "services": [], "sources": {}},
        "clusters": {"independent": [], "cyclic": [], "dynamic": [], "sccs": [], "counts": {}},
        "pivotal": [],
        "flows": [],
        "module_graph": {"nodes": [], "edges": []},
        "stats": {"files": 0, "symbols": 0, "languages": []},
    }
    document = build_dossier(model, 3)
    assert "empty-repo" in document
    assert "no structural risks" in document.lower() or "Risk register" in document
    assert document.rstrip().endswith("</html>")
