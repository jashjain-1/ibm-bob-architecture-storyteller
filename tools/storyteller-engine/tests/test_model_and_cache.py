"""Phase-1 tests: unified model, cache delta, insights contract."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from model_builder import build_model, manifest_from_model, tree_payload  # noqa: E402
from cache_store import StorytellerCache  # noqa: E402
from insights import (  # noqa: E402
    DeterministicProvider,
    InsightService,
    _normalize_items,
    deterministic_micro,
    narrative_hash,
    strip_emoji,
)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text(
        '"""Fixture application."""\n'
        "\n"
        "from pkg import helpers\n"
        "\n"
        "\n"
        "class UserService:\n"
        '    """Coordinates user operations."""\n'
        "\n"
        "    def load_user(self, user_id):\n"
        '        """Loads a single user record by id."""\n'
        "        return helpers.fetch_row(user_id)\n"
        "\n"
        "    def save_user(self, user_id, payload):\n"
        "        return helpers.write_row(user_id, payload)\n"
        "\n"
        "\n"
        "def audit(event):\n"
        "    return _emit(event)\n"
        "\n"
        "\n"
        "def _emit(event):\n"
        "    return audit(event)\n"
        "\n"
        "\n"
        "def dynamic_dispatch(name):\n"
        "    return globals()[name]()\n",
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
        "/** Renders the user card. */\n"
        "export class UserCard {\n"
        "  render(user: User) {\n"
        "    return formatName(user.name);\n"
        "  }\n"
        "}\n"
        "\n"
        "export function formatName(name: string) {\n"
        "  return name.trim();\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "runner.go").write_text(
        "package main\n"
        "\n"
        "func main() {\n"
        "    start()\n"
        "}\n"
        "\n"
        "func start() {\n"
        "    println(\"up\")\n"
        "}\n",
        encoding="utf-8",
    )
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text(
        "def test_load():\n    assert True\n", encoding="utf-8"
    )
    return tmp_path


def test_model_is_single_source_of_truth(repo: Path):
    model = build_model(repo)
    stats = model["stats"]

    assert stats["symbols"] > 8
    assert "python" in stats["languages"] and "typescript" in stats["languages"]
    assert stats["test_functions"] == 1
    assert model["schema"].endswith("architecture-model@2")

    ids = {s["id"] for s in model["symbols"]}
    assert any(i.endswith("::UserService.load_user") for i in ids)
    assert any("ui.ts::UserCard.render" in i for i in ids), "TS class methods must be captured"


def test_call_resolution_is_scoped_and_closed(repo: Path):
    model = build_model(repo)
    by_id = {s["id"]: s for s in model["symbols"]}

    load_user = next(s for s in model["symbols"] if s["name"] == "load_user")
    callee_ids = load_user["calls"]
    assert callee_ids == ["pkg/helpers.py::fetch_row"], callee_ids
    assert by_id[callee_ids[0]]["name"] == "fetch_row"

    # every resolved target exists: the graph never invents edges
    dangling = [c for s in model["symbols"] for c in s["calls"] if c not in by_id]
    assert dangling == []

    # callers are symmetric
    fetch = by_id["pkg/helpers.py::fetch_row"]
    assert "app.py::UserService.load_user" in fetch["callers"]


def test_clusters_detect_cycles_and_dynamic(repo: Path):
    model = build_model(repo)
    cyclic = set(model["clusters"]["cyclic"])
    dynamic = set(model["clusters"]["dynamic"])

    assert "app.py::audit" in cyclic or "app.py::_emit" in cyclic
    assert any(i.endswith("dynamic_dispatch") for i in dynamic)
    assert model["clusters"]["counts"]["cyclic"] >= 2


def test_tree_payload_is_bounded(repo: Path):
    model = build_model(repo)
    payload = tree_payload(model, max_calls=2)
    assert payload["schema"] == model["schema"]
    for sym in payload["symbols"]:
        assert len(sym["calls"]) <= 2 and len(sym["callers"]) <= 2
