"""
test_security_hardening.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Exhaustive verification of R1 Security Hardening:
1. CORS origin allowlist & 403 rejection of malicious origins
2. Host header validation & DNS rebinding protection (400 Bad Request)
3. Request body size limit (>50MB -> 413 Payload Too Large)
4. Path traversal protection in /dossier and render_pdf
5. RCE remediation in ripple_agent (shell=False, safe arg parsing)
6. Windows cmd.exe batch parameter delimiter injection sanitization
7. 40-Coin budget funnel & 0-coin policy enforcement
8. AST parser resilience against malformed code and extreme exceptions
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

ENGINE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ENGINE_DIR.parent.parent
for extra in (ENGINE_DIR, ENGINE_DIR.parent / "py-ast-core", PROJECT_ROOT / "scripts"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from ast_extractor import _extract_file, _extract_python_native  # noqa: E402
from bob_bridge import invoke_bob, sanitize_cli_arg  # noqa: E402
from coin_ledger import (  # noqa: E402
    CoinBudgetExceededError,
    CoinBudgetManager,
    CoinPolicyViolationError,
)
from engine_server import StorytellerEngine, _is_allowed_origin, _is_valid_host, serve  # noqa: E402
from ripple_agent import _dispatch_bob_orchestrator  # noqa: E402


@pytest.fixture(autouse=True)
def quiet_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORYTELLER_SERVER_QUIET", "1")


@pytest.fixture()
def test_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    return repo


@pytest.fixture()
def running_server(test_repo: Path):
    engine = StorytellerEngine(test_repo, languages=["python"], staleness_seconds=0.0)
    server = serve(engine, port=0, host="127.0.0.1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base_url, engine, test_repo
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# ===========================================================================
# 1. CORS Origin Validation & Host Header Hardening
# ===========================================================================

def test_is_allowed_origin_unit():
    # Strictly allowed origins
    assert _is_allowed_origin("http://localhost") is True
    assert _is_allowed_origin("http://localhost:3000") is True
    assert _is_allowed_origin("http://localhost:8003") is True
    assert _is_allowed_origin("http://127.0.0.1") is True
    assert _is_allowed_origin("http://127.0.0.1:8003") is True
    assert _is_allowed_origin("vscode-webview://my-view-id") is True
    assert _is_allowed_origin("vscode-file://vscode-app/bundle.js") is True
    assert _is_allowed_origin("") is True  # empty allowed for direct non-browser calls

    # Strictly forbidden origins (must NOT match prefix bypasses)
    assert _is_allowed_origin("http://localhost.evil.com") is False
    assert _is_allowed_origin("http://localhost.attacker.com:8003") is False
    assert _is_allowed_origin("http://127.0.0.1.attacker.com") is False
    assert _is_allowed_origin("http://localhost-evil.com") is False
    assert _is_allowed_origin("http://attacker.com") is False
    assert _is_allowed_origin("http://evil.com?http://localhost") is False
    assert _is_allowed_origin("null") is False


def test_cors_allowed_origins_http(running_server):
    base_url, _, _ = running_server

    for origin in ("http://localhost", "http://localhost:3000", "http://127.0.0.1:8080"):
        req = Request(f"{base_url}/health", headers={"Origin": origin})
        with urlopen(req, timeout=10) as resp:
            assert resp.status == 200
            assert resp.headers.get("Access-Control-Allow-Origin") == origin
            assert "content-type" in (resp.headers.get("Access-Control-Allow-Headers") or "").lower()


def test_cors_forbidden_origins_rejected_with_403(running_server):
    base_url, _, _ = running_server

    forbidden_origins = [
        "http://localhost.evil.com",
        "http://localhost.attacker.com:8003",
        "http://127.0.0.1.attacker.com",
        "http://evil.com",
        "null",
    ]

    for origin in forbidden_origins:
        # GET request with malicious origin
        req = Request(f"{base_url}/health", headers={"Origin": origin})
        with pytest.raises(HTTPError) as exc_info:
            urlopen(req, timeout=10)
        assert exc_info.value.code == 403
        assert exc_info.value.headers.get("Access-Control-Allow-Origin") is None

        # OPTIONS preflight with malicious origin
        opt_req = Request(f"{base_url}/health", headers={"Origin": origin}, method="OPTIONS")
        with pytest.raises(HTTPError) as exc_opt:
            urlopen(opt_req, timeout=10)
        assert exc_opt.value.code == 403
        assert exc_opt.value.headers.get("Access-Control-Allow-Origin") is None


def test_host_header_validation_rejects_dns_rebinding(running_server):
    base_url, _, _ = running_server

    # Invalid Host header (simulating DNS rebinding)
    req = Request(f"{base_url}/health", headers={"Host": "rebind.attacker.com:8003"})
    with pytest.raises(HTTPError) as exc_info:
        urlopen(req, timeout=10)
    assert exc_info.value.code == 400


def test_content_length_limit_exceeded_returns_413(running_server):
    base_url, _, _ = running_server

    # Simulated oversized Content-Length header (> 50MB)
    oversized = 55 * 1024 * 1024
    req = Request(
        f"{base_url}/index",
        data=b"{}",
        headers={"Content-Length": str(oversized), "Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(HTTPError) as exc_info:
        urlopen(req, timeout=10)
    assert exc_info.value.code == 413


# ===========================================================================
# 2. Path Traversal Protection
# ===========================================================================

def test_dossier_path_traversal_rejected_http(running_server):
    base_url, _, _ = running_server

    payload = json.dumps({"pdf": True, "output": "../../outside_workspace.pdf"}).encode("utf-8")
    req = Request(
        f"{base_url}/dossier",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(HTTPError) as exc_info:
        urlopen(req, timeout=10)
    assert exc_info.value.code == 400
    err_body = json.loads(exc_info.value.read().decode("utf-8"))
    assert "Path traversal detected" in err_body["error"]


def test_render_pdf_path_traversal_raises_value_error(test_repo: Path):
    engine = StorytellerEngine(test_repo, languages=["python"])
    with pytest.raises(ValueError, match="Path traversal detected"):
        engine.render_pdf(level=1, output="../../escaped_exploit.pdf")


# ===========================================================================
# 3. RCE Remediation in ripple_agent
# ===========================================================================

def test_dispatch_bob_orchestrator_shell_false(test_repo: Path):
    # Verify that shell-chaining characters are NOT executed by a shell
    # A shell=True would run echo pwned and create an exploit marker; shell=False treats & as arg
    marker_file = test_repo / "rce_marker.txt"
    malicious_cmd = f'"{sys.executable}" -c "import sys" & echo pwned > "{marker_file}"'
    res = _dispatch_bob_orchestrator(
        prompt="test prompt",
        repo_root=test_repo,
        bob_command=malicious_cmd,
    )
    # The marker file must NOT exist (shell expansion blocked)
    assert not marker_file.exists()


# ===========================================================================
# 4. Windows Batch Delimiter Sanitization
# ===========================================================================

def test_sanitize_cli_arg_removes_delimiters():
    dirty = "echo first\nwhoami & dir | calc.exe ^ %PATH% < in > out \"quoted\""
    clean = sanitize_cli_arg(dirty)
    assert "\n" not in clean
    assert "\r" not in clean
    assert "&" not in clean
    assert "|" not in clean
    assert "^" not in clean
    assert "%" not in clean
    assert "<" not in clean
    assert ">" not in clean
    assert '"' not in clean
    assert "whoami" in clean
    assert "calc.exe" in clean


# ===========================================================================
# 5. 40-Coin Budget Funnel & 0-Coin Policy
# ===========================================================================

def test_coin_budget_manager_cap_and_policy(tmp_path: Path):
    ledger_file = tmp_path / ".agents" / "coin_budget_ledger.json"
    manager = CoinBudgetManager(workspace_root=tmp_path, ledger_file=ledger_file, max_coins=40)

    assert manager.total_spent == 0
    assert manager.remaining_coins == 40

    # Normal execution is approved
    can_spend, reason = manager.can_spend(prompt="Synthesize architectural boundaries", purpose="feature_dev")
    assert can_spend is True
    assert reason == "Approved"

    # 0-coin policy blocks bug fixing
    bug_prompts = [
        "Fix bug in authentication token validation",
        "Fix syntax error in parser",
        "Bugfix for null pointer exception",
        "Patch error in file writer",
    ]
    for bp in bug_prompts:
        ok, why = manager.can_spend(prompt=bp)
        assert ok is False
        assert "0-coin policy" in why
        with pytest.raises(CoinPolicyViolationError):
            manager.record_transaction(prompt=bp)

    # 0-coin policy blocks automated exploration
    explore_prompts = [
        "Explore codebase to find all API routes",
        "Codebase exploration for models",
        "Automated exploration of repo structure",
    ]
    for ep in explore_prompts:
        ok, why = manager.can_spend(prompt=ep)
        assert ok is False
        assert "0-coin policy" in why
        with pytest.raises(CoinPolicyViolationError):
            manager.record_transaction(prompt=ep)

    # Record 40 valid transactions
    for i in range(40):
        tx = manager.record_transaction(prompt=f"Architecture step {i}", purpose="analysis", coins=1)
        assert tx["coins"] == 1

    assert manager.total_spent == 40
    assert manager.remaining_coins == 0

    # 41st coin must be rejected
    can_spend_41, reason_41 = manager.can_spend(prompt="One more step")
    assert can_spend_41 is False
    assert "Budget exceeded" in reason_41

    with pytest.raises(CoinBudgetExceededError):
        manager.record_transaction(prompt="One more step")

    # Verify persistent ledger file on disk
    assert ledger_file.is_file()
    ledger_data = json.loads(ledger_file.read_text(encoding="utf-8"))
    assert ledger_data["coins_spent"] == 40
    assert ledger_data["coins_remaining"] == 0
    assert len(ledger_data["transactions"]) == 40


def test_bob_bridge_respects_coin_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Set up exhausted ledger
    ledger_file = tmp_path / ".agents" / "coin_budget_ledger.json"
    manager = CoinBudgetManager(workspace_root=tmp_path, ledger_file=ledger_file, max_coins=40)
    for i in range(40):
        manager.record_transaction(prompt=f"Task {i}")

    monkeypatch.setattr("bob_bridge.WORKSPACE_ROOT", tmp_path)
    res = invoke_bob("Executive architecture assessment")
    assert "[COIN_PRESERVATION]" in res.stdout
    assert "Budget exceeded" in res.stdout


# ===========================================================================
# 6. AST Resilience
# ===========================================================================

def test_ast_extractor_handles_syntax_and_corrupt_files(tmp_path: Path):
    # Malformed Python file
    bad_py = tmp_path / "corrupt.py"
    bad_py.write_text("def broken(:\n    ??? invalid python syntax %%%", encoding="utf-8")

    # Native extraction must NOT raise SyntaxError; returns empty lists
    symbols, entry_points, edges = _extract_python_native(bad_py.read_text(encoding="utf-8"), str(bad_py))
    assert symbols == []
    assert entry_points == []
    assert edges == []

    # _extract_file must safely return empty lists for corrupted file
    syms, eps, edgs = _extract_file(str(bad_py), "corrupt.py", "python")
    assert syms == []
    assert eps == []
    assert edgs == []
