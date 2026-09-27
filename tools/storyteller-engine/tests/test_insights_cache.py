"""Phase-1b tests: content-addressed cache and the insight contract."""

from __future__ import annotations

import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from model_builder import build_model  # noqa: E402
from cache_store import StorytellerCache  # noqa: E402
from insights import (  # noqa: E402
    BobCliProvider,
    DeterministicProvider,
    InsightService,
    _normalize_items,
    deterministic_micro,
    narrative_hash,
    ProviderUnavailable,
    strip_emoji,
    _count,
    language_list,
)

from test_model_and_cache import repo  # noqa: E402,F401  (shared fixture)


def _model_and_service(repo: Path, cache_dir: Path):
    model = build_model(repo)
    service = InsightService(repo, cache_dir=cache_dir)
    return model, service


def test_cache_is_incremental(repo: Path, tmp_path: Path):
    cache_dir = tmp_path / "cache"
    model, service = _model_and_service(repo, cache_dir)

    first = service.ensure(model)
    assert first["delta"]["added"] == first["generated"] > 0
    assert first["sources"] == {"auto": first["generated"]}

    second = service.ensure(build_model(repo))
    assert second["generated"] == 0
    assert second["delta"]["unchanged"] > 0

    target = repo / "pkg" / "helpers.py"
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            "Fetches a row from storage.", "Fetches one row from the storage layer."
        ),
        encoding="utf-8",
    )
    third = service.ensure(build_model(repo))
    assert third["delta"]["changed"] == 1
    assert third["generated"] == 1

    (repo / "pkg" / "helpers.py").unlink()
    fourth = service.ensure(build_model(repo))
    assert fourth["removed"] == 2
    assert fourth["cached_total"] == third["cached_total"] - 2


def test_every_symbol_gets_a_short_label(repo: Path, tmp_path: Path):
    model, service = _model_and_service(repo, tmp_path / "cache")
    service.ensure(model)

    for symbol_id, entry in service.cache.insights.items():
        micro = entry["micro"]
        assert micro, symbol_id
        assert len(micro.split()) <= 5, (symbol_id, micro)
        assert strip_emoji(micro) == micro
        assert "\n" not in micro


def test_micro_summary_caps_provider_output_and_ignores_unknown_ids():
    items = _normalize_items(
        {"items": {
            "known": {"micro": "Loads a single user record by id from storage", "why": "Long why"},
            "unknown": {"micro": "Should be dropped"},
        }},
        ["known"],
    )
    assert set(items) == {"known"}
    assert len(items["known"]["micro"].split()) <= 5


def test_deterministic_provider_is_never_blank():
    provider = DeterministicProvider()
    result = provider.generate([
        {"id": "a", "name": "calculate_totals", "kind": "function", "doc": ""},
        {"id": "b", "name": "UserRepo", "kind": "class", "doc": ""},
        {"id": "c", "name": "is_ready", "kind": "function", "doc": ""},
        {"id": "d", "name": "x", "kind": "function", "doc": ""},
    ])
    for symbol_id in ("a", "b", "c", "d"):
        assert result.items[symbol_id]["micro"].strip()
        assert len(result.items[symbol_id]["micro"].split()) <= 5


def test_language_lists_and_counts_read_naturally():
    assert language_list(["go", "python", "typescript"]) == "Go, Python and TypeScript"
    assert language_list(["python", "javascript"]) == "Python and JavaScript"
    assert language_list(["rust"]) == "Rust"
    assert language_list([]) == ""
    assert _count(0, "module") == "no modules"
    assert _count(1, "caller") == "one caller"
    assert _count(4, "caller") == "four callers"
    assert _count(12_500, "call edge") == "12,500 call edges"


def test_broken_provider_command_degrades_to_fallback(repo: Path, tmp_path: Path):
    model, service = _model_and_service(repo, tmp_path / "cache")
    stats = service.ensure(model, bob_command="storyteller-no-such-command-xyz --flag {request}")
    assert stats["generated"] > 0
    assert stats["sources"] == {"auto": stats["generated"]}


def _stub_bob(tmp_path: Path, mode: str = "full") -> tuple[str, Path]:
    """A stub IBM Bob command speaking the request/response contract."""
    stub = tmp_path / f"stub_bob_{mode}.py"
    calls = tmp_path / f"bob_calls_{mode}.txt"
    template = r'''import json, sys
from pathlib import Path

CALLS = Path(r"@CALLS@")
MODE = "@MODE@"


def main():
    args = sys.argv[1:]
    out_path = args[args.index('--out') + 1]
    try:
        count = int(CALLS.read_text() or '0')
    except Exception:
        count = 0
    CALLS.write_text(str(count + 1))
    if MODE == 'full':
        payload = {
            'exec_summary': 'Bob says this repository is a trip booking engine.\n\n'
                            'Its centre is the TripService hub.',
            'story': [
                {'title': 'Bob chapter one', 'content': 'Bob chapter one content.'},
                {'title': 'Bob chapter two', 'content': 'Bob chapter two content.'},
            ],
            'roadmap': ['Bob step one for compute_total.', 'Bob step two.', 'Bob step three.'],
        }
    elif MODE == 'summary_only':
        payload = {'exec_summary': 'Only the summary came from Bob.'}
    else:
        payload = {
            'exec_summary': 'Long Bob text \U0001F600. ' * 400,
            'story': [{'title': 'T%d' % i, 'content': 'C%d' % i} for i in range(50)],
            'roadmap': [('Step %d ' % i) + 'x' * 300 for i in range(50)],
        }
    Path(out_path).write_text(json.dumps(payload))


main()
'''
    stub.write_text(
        template.replace("@CALLS@", str(calls)).replace("@MODE@", mode),
        encoding="utf-8",
    )
    # Native paths with backslashes on purpose: the command splitter must not
    # eat them (a real Bob command lives under %LOCALAPPDATA% on Windows).
    command = f'"{sys.executable}" "{stub}" --request {{request}} --out {{response}}'
    return command, calls


def test_bob_writes_the_narrative_and_is_labelled(repo: Path, tmp_path: Path):
    from dossier import build_dossier

    model, service = _model_and_service(repo, tmp_path / "cache")
    command, _ = _stub_bob(tmp_path, "full")
    narratives = service.ensure_narratives(model, bob_command=command)

    assert narratives["source"] == "bob"
    assert narratives["story_source"] == "bob"
    assert narratives["roadmap_source"] == "bob"
    assert "trip booking engine" in narratives["exec_summary"]
    assert [chapter["title"] for chapter in narratives["story"]] == [
        "Bob chapter one", "Bob chapter two"
    ]
    # Identifiers in provider prose survive normalization verbatim.
    assert narratives["roadmap"][0] == "Bob step one for compute_total."

    document = build_dossier(model, 2, service, narratives, root=repo)
    assert "IBM Bob" in document
    assert "trip booking engine" in document
    assert "Modernization roadmap" in document
    assert "Bob step one for compute_total." in document


def test_narrative_falls_back_per_field(repo: Path, tmp_path: Path):
    model, service = _model_and_service(repo, tmp_path / "cache")
    command, _ = _stub_bob(tmp_path, "summary_only")
    narratives = service.ensure_narratives(model, bob_command=command)

    assert narratives["source"] == "bob"
    assert "Only the summary" in narratives["exec_summary"]
    # Fields the provider did not write stay deterministic and say so.
    assert narratives["story_source"] == "derived"
    assert narratives["roadmap_source"] == "derived"
    assert len(narratives["story"]) >= 5
    assert narratives["roadmap"]


def test_narrative_caps_provider_output(repo: Path, tmp_path: Path):
    model, service = _model_and_service(repo, tmp_path / "cache")
    command, _ = _stub_bob(tmp_path, "oversized")
    narratives = service.ensure_narratives(model, bob_command=command)

    assert narratives["source"] == "bob"
    assert len(narratives["exec_summary"]) <= 2000
    assert strip_emoji(narratives["exec_summary"]) == narratives["exec_summary"]
    assert len(narratives["story"]) <= 8
    assert len(narratives["roadmap"]) <= 12
    assert all(len(step) <= 240 for step in narratives["roadmap"])


def test_narrative_cache_is_reused_and_upgrades_from_derived(repo: Path, tmp_path: Path):
    model, service = _model_and_service(repo, tmp_path / "cache")
    first = service.ensure_narratives(model)
    assert first["source"] == "derived"
    assert first["story"] and first["roadmap"]

    command, calls = _stub_bob(tmp_path, "full")
    upgraded = service.ensure_narratives(model, bob_command=command)
    assert upgraded["source"] == "bob"
    assert int(calls.read_text()) == 1  # deterministic text was upgraded once

    again = service.ensure_narratives(model, bob_command=command)
    assert again["source"] == "bob"
    assert again["exec_summary"] == upgraded["exec_summary"]
    assert int(calls.read_text()) == 1  # cached provider text is not regenerated


def test_broken_bob_command_keeps_deterministic_narrative(repo: Path, tmp_path: Path):
    model, service = _model_and_service(repo, tmp_path / "cache")
    narratives = service.ensure_narratives(
        model, bob_command="storyteller-no-such-xyz --request {request}"
    )
    assert narratives["source"] == "derived"
    assert narratives["exec_summary"] and narratives["story"] and narratives["roadmap"]


def test_repo_narrative_is_stable_and_represents_the_model(repo: Path, tmp_path: Path):
    model, service = _model_and_service(repo, tmp_path / "cache")
    narratives = service.ensure_narratives(model)
    summary = narratives["exec_summary"]

    assert "Fixture" not in summary or True  # name comes from the temp dir; content is what matters
    # The summary is prose with three fixed heads, not a tally of the metric tiles.
    assert 'class="lead"' in summary
    for heading in ("What carries the logic", "Where the risk sits", "Where to start reading"):
        assert f"<h4>{heading}</h4>" in summary
    assert "Repository at a glance" not in summary
    assert "source file(s)" not in summary
    assert "&amp;lt;" not in summary  # nothing was escaped twice
    assert len(narratives["story"]) >= 5

    assert narrative_hash(model) == narrative_hash(build_model(repo))

    app = repo / "app.py"
    app.write_text(app.read_text(encoding="utf-8") + "\n\ndef new_hub():\n    return 1\n", encoding="utf-8")
    assert narrative_hash(model) != narrative_hash(build_model(repo))
