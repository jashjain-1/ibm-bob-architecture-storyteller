"""Engine + HTTP API tests.

These drive the real server over a real socket, because the extension's hover
and map depend on those routes behaving exactly as documented.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

ENGINE = Path(__file__).resolve().parent.parent
for extra in (ENGINE, ENGINE.parent / "py-ast-core"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from engine_server import StorytellerEngine, SymbolLookupError, serve  # noqa: E402


@pytest.fixture(autouse=True)
def quiet_in_process_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silence the in-process server without leaking the flag to other modules.

    Setting this at import time used to hide the "listening" line from every
    later test in the session, which hung a subprocess-based test that waited
    for it.
    """
    monkeypatch.setenv("STORYTELLER_SERVER_QUIET", "1")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text(
        "from pkg import helpers\n"
        "\n"
        "\n"
        "class TripService:\n"
        '    """Coordinates trip operations."""\n'
        "\n"
        "    def load_trip(self, trip_id):\n"
        '        """Loads one trip by id."""\n'
        "        return helpers.fetch_row(trip_id)\n"
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
        "    return {'id': row_id}\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def engine(repo: Path) -> StorytellerEngine:
    return StorytellerEngine(repo, languages=["python"], staleness_seconds=0.0)


@pytest.fixture()
def base_url(engine: StorytellerEngine):
    server = serve(engine, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get(url: str, raw: bool = False):
    with urlopen(url, timeout=30) as response:
        body = response.read().decode("utf-8")
        return body if raw else json.loads(body)


def test_engine_model_is_rebuilt_when_the_tree_changes(engine: StorytellerEngine, repo: Path):
    first = engine.ensure_model()["stats"]["symbols"]
    (repo / "extra.py").write_text("def brand_new():\n    return 1\n", encoding="utf-8")
    second = engine.ensure_model()["stats"]["symbols"]
    assert second > first, (first, second)


def test_index_reports_only_changed_symbols(engine: StorytellerEngine, repo: Path):
    engine.index()
    (repo / "app.py").write_text(
        (repo / "app.py").read_text(encoding="utf-8") + "\n\ndef later_added():\n    return 2\n",
        encoding="utf-8",
    )
    report = engine.index()
    assert report["delta"]["added"] >= 1
    assert report["delta"]["changed"] == 0
    assert report["generated"] >= 1

    # A no-op re-index generates nothing and keeps the cache warm.
    again = engine.index()
    assert again["delta"]["added"] == 0
    assert again["generated"] == 0


def test_symbol_lookup_by_id_name_and_suffix(engine: StorytellerEngine):
    by_name = engine.find_symbol("load_trip")
    assert by_name["qualified"] == "TripService.load_trip"
    assert engine.find_symbol(by_name["id"])["id"] == by_name["id"]
    assert engine.find_symbol("TripService.load_trip")["id"] == by_name["id"]
    with pytest.raises(SymbolLookupError):
        engine.find_symbol("does_not_exist")


def test_context_and_usages_carry_real_call_sites(engine: StorytellerEngine):
    context = engine.context("fetch_row", lines=5)
    assert context["symbol"]["file"] == "pkg/helpers.py"
    callers = {caller["qualified"] for caller in context["callers"]}
    assert "TripService.load_trip" in callers
    assert "return {'id': row_id}" in context["source"]

    usages = engine.usages("fetch_row")
    assert usages["call_site_count"] >= 1
    assert any("helpers.fetch_row" in (caller.get("raw_calls") or []) for caller in usages["callers"])


def test_http_api_endpoints(base_url: str):
    health = _get(f"{base_url}/health")
    assert health["ok"] is True and health["schema"].endswith("architecture-model@2")
    assert "python" in health["stats"]["languages"]

    stats = _get(f"{base_url}/stats")
    assert stats["stats"]["symbols"] > 3

    compact = _get(f"{base_url}/model")
    full = _get(f"{base_url}/model?full=1")
    assert len(compact.get("symbols", [])) == len(full.get("symbols", []))
    assert compact["schema"] == full["schema"]

    tree = _get(f"{base_url}/tree")
    assert any(symbol["name"] == "load_trip" for symbol in tree["symbols"])

    context = _get(f"{base_url}/context?symbol=load_trip&lines=3")
    assert context["symbol"]["qualified"] == "TripService.load_trip"

    usages = _get(f"{base_url}/usages?symbol=fetch_row")
    assert usages["call_site_count"] >= 1

    delta = _get(f"{base_url}/delta")
    assert "counts" in delta

    index_report = _get(f"{base_url}/delta")
    assert index_report["counts"]["added"] >= 0

    html = _get(f"{base_url}/dossier?level=1", raw=True)
    assert html.startswith("<!DOCTYPE html>") and "Risk register" in html

    json_dossier = _get(f"{base_url}/dossier?level=3&format=json")
    assert json_dossier["level"] == 3 and "Symbol evidence" in json_dossier["html"]


def test_http_api_post_index_and_errors(base_url: str):
    request = Request(f"{base_url}/index", data=b'{"force": false}',
                      headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=60) as response:
        report = json.loads(response.read().decode("utf-8"))
    assert "provider" in report and "cached_total" in report

    with pytest.raises(HTTPError) as missing:
        _get(f"{base_url}/context?symbol=not_a_symbol")
    assert missing.value.code == 404
    payload = json.loads(missing.value.read().decode("utf-8"))
    assert payload["kind"] == "symbol"

    with pytest.raises(HTTPError) as unknown:
        _get(f"{base_url}/nope")
    assert unknown.value.code == 404

    # CORS is open on localhost so the webview can call the engine directly.
    with urlopen(f"{base_url}/health", timeout=30) as response:
        assert response.headers.get("Access-Control-Allow-Origin") == "*"
