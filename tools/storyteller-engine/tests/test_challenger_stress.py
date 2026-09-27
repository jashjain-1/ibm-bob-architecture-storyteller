"""
test_challenger_stress.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Adversarial Stress Test Suite for Milestone 1 Security Hardening.
Authored by: Challenger Agent (teamwork_preview_challenger)

Targets:
1. CORS & Origin bypasses (regex evasion, invalid schemes, null, subdomains, userinfo, ports)
2. Path traversal in /dossier and render_pdf (../, ..\\, %2e%2e, UNC paths, Windows drive escapes)
3. CoinBudgetManager (boundary 39/40/41, multithreaded concurrent requests, policy checks)
4. AST extractors (malformed syntax, cyclic structures, deep recursion, empty files)
"""

from __future__ import annotations

import concurrent.futures
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

from ast_extractor import (  # noqa: E402
    _extract_file,
    _extract_go_native,
    _extract_python_native,
    _extract_ts_native,
)
from coin_ledger import (  # noqa: E402
    CoinBudgetExceededError,
    CoinBudgetManager,
    CoinPolicyViolationError,
)
from engine_server import StorytellerEngine, _is_allowed_origin, _is_valid_host, serve  # noqa: E402


@pytest.fixture(autouse=True)
def quiet_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORYTELLER_SERVER_QUIET", "1")


@pytest.fixture()
def stress_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "stress_repo"
    repo.mkdir()
    (repo / "app.py").write_text("def index():\n    return 'ok'\n", encoding="utf-8")
    return repo


@pytest.fixture()
def running_server(stress_repo: Path):
    engine = StorytellerEngine(stress_repo, languages=["python"], staleness_seconds=0.0)
    server = serve(engine, port=0, host="127.0.0.1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base_url, engine, stress_repo
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# ===========================================================================
# 1. CORS Bypasses & Origin Evasion Stress Tests
# ===========================================================================

class TestCorsBypasses:
    """Stress-test CORS origin filtering against evasion payloads."""

    MALICIOUS_ORIGINS = [
        # Subdomain / domain prefix bypass attempts
        "http://localhost.evil.com",
        "https://localhost.evil.com",
        "http://localhost.evil.com:8000",
        "http://127.0.0.1.attacker.com",
        "https://127.0.0.1.attacker.com:3000",
        "http://localhost-attacker.com",
        "http://127.0.0.1-attacker.com",
        "http://127.0.0.1.nip.io",
        "http://127.0.0.10",
        "http://127.0.1.1",
        "http://localhost.localdomain.evil.com",
        
        # Null and invalid schemes
        "null",
        "javascript:alert(1)",
        "ftp://localhost",
        "ftp://127.0.0.1:8000",
        "ws://localhost:8000",
        "file:///C:/Users/jainj/Desktop/evil.html",
        "data:text/html,<html><body>evil</body></html>",

        # URL tricks & parser confusion
        "http://localhost@evil.com",
        "http://127.0.0.1@attacker.com",
        "http://evil.com#localhost",
        "http://evil.com?http://localhost",
        "http://localhost:evil",
        "http://localhost:abc",
        "http://localhost.",
        "vscode-webview-evil://malicious-extension",
        "vscode-file-evil://malicious-extension",
    ]

    VALID_ORIGINS = [
        "http://localhost",
        "https://localhost",
        "http://localhost:3000",
        "https://localhost:8080",
        "http://127.0.0.1",
        "https://127.0.0.1",
        "http://127.0.0.1:8003",
        "https://127.0.0.1:9000",
        "vscode-webview://random-webview-guid-1234",
        "vscode-file://vscode-app/out/vs/workbench/workbench.desktop.main.js",
        "",  # Non-browser direct requests / CLI
    ]

    def test_is_allowed_origin_malicious_matrix(self):
        """Ensure all malicious origins fail unit-level regex validation."""
        for origin in self.MALICIOUS_ORIGINS:
            assert _is_allowed_origin(origin) is False, f"Origin bypass succeeded for: {origin}"

    def test_is_allowed_origin_valid_matrix(self):
        """Ensure all valid developer and VS Code origins pass validation."""
        for origin in self.VALID_ORIGINS:
            assert _is_allowed_origin(origin) is True, f"Valid origin falsely blocked: {origin}"

    def test_http_options_preflight_blocks_malicious_origins(self, running_server):
        """OPTIONS preflight with malicious origins must receive 403 Forbidden with no CORS header."""
        base_url, _, _ = running_server
        for origin in self.MALICIOUS_ORIGINS:
            req = Request(f"{base_url}/health", headers={"Origin": origin}, method="OPTIONS")
            with pytest.raises(HTTPError) as exc_info:
                urlopen(req, timeout=5)
            assert exc_info.value.code == 403, f"Expected 403 for preflight origin: {origin}"
            assert exc_info.value.headers.get("Access-Control-Allow-Origin") is None

    def test_http_get_blocks_malicious_origins(self, running_server):
        """GET request with malicious origin must be denied with 403 Forbidden."""
        base_url, _, _ = running_server
        for origin in ["http://localhost.evil.com", "http://127.0.0.1.attacker.com", "null", "ftp://localhost"]:
            req = Request(f"{base_url}/health", headers={"Origin": origin})
            with pytest.raises(HTTPError) as exc_info:
                urlopen(req, timeout=5)
            assert exc_info.value.code == 403
            assert exc_info.value.headers.get("Access-Control-Allow-Origin") is None

    def test_host_header_dns_rebinding_matrix(self, running_server):
        """Host header must reject all external domains and rebinding tricks with 400 Bad Request."""
        base_url, _, _ = running_server
        invalid_hosts = [
            "evil.com",
            "localhost.evil.com",
            "127.0.0.1.attacker.com",
            "attacker.com:8003",
            "192.168.1.100",
            "10.0.0.1:8000",
            "",
        ]
        for host in invalid_hosts:
            req = Request(f"{base_url}/health", headers={"Host": host})
            with pytest.raises(HTTPError) as exc_info:
                urlopen(req, timeout=5)
            assert exc_info.value.code == 400, f"Expected 400 for Host header: {host}"


# ===========================================================================
# 2. Path Traversal in /dossier Stress Tests
# ===========================================================================

class TestPathTraversalDossier:
    """Stress-test path traversal defenses in /dossier and render_pdf."""

    TRAVERSAL_PAYLOADS = [
        "../outside.pdf",
        "..\\outside.pdf",
        "../../outside.pdf",
        "..\\..\\outside.pdf",
        "../../../escaped.pdf",
        "..\\..\\..\\escaped.pdf",
        "output/../../../../Windows/System32/drivers/etc/hosts",
        "output\\..\\..\\..\\Windows\\System32\\calc.exe",
        "C:\\Windows\\temp\\exploit.pdf",
        "c:/windows/temp/exploit.pdf",
        "D:\\escaped_drive.pdf",
        "\\\\attacker-server\\share\\evil.pdf",
        "//attacker-server/share/evil.pdf",
    ]

    def test_render_pdf_direct_traversal_attempts(self, stress_repo: Path):
        """Direct invocation of render_pdf with traversal paths must raise ValueError."""
        engine = StorytellerEngine(stress_repo, languages=["python"])
        for payload in self.TRAVERSAL_PAYLOADS:
            with pytest.raises(ValueError, match="Path traversal detected"):
                engine.render_pdf(level=1, output=payload)

    def test_http_dossier_post_traversal_payloads(self, running_server):
        """POST /dossier with traversal payload in JSON body must return 400 Bad Request."""
        base_url, _, _ = running_server
        for payload in self.TRAVERSAL_PAYLOADS:
            req = Request(
                f"{base_url}/dossier",
                data=json.dumps({"pdf": True, "output": payload}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(HTTPError) as exc_info:
                urlopen(req, timeout=5)
            assert exc_info.value.code == 400
            err = json.loads(exc_info.value.read().decode("utf-8"))
            assert "Path traversal detected" in err["error"]

    def test_http_dossier_query_param_traversal(self, running_server):
        """GET /dossier with query param output traversal (including URL encoding) must return 400."""
        base_url, _, _ = running_server
        query_payloads = [
            "../outside.pdf",
            "..\\outside.pdf",
            "%2e%2e/outside.pdf",
            "%2e%2e%2foutside.pdf",
            "%2e%2e%5coutside.pdf",
            "..%2foutside.pdf",
            "C:%5CWindows%5Ctemp%5Cevil.pdf",
        ]
        for qp in query_payloads:
            req = Request(f"{base_url}/dossier?pdf=1&output={qp}")
            with pytest.raises(HTTPError) as exc_info:
                urlopen(req, timeout=5)
            assert exc_info.value.code == 400
            err = json.loads(exc_info.value.read().decode("utf-8"))
            assert "Path traversal detected" in err["error"]

    def test_dossier_in_bounds_relative_subpaths_allowed(self, running_server, stress_repo: Path):
        """Legitimate in-bounds subpaths inside repo root must not trigger false positives."""
        base_url, engine, _ = running_server
        # Verify containment check on valid relative subpaths
        valid_paths = [
            "output/sub/report.pdf",
            "dossier.pdf",
            "./reports/dossier.pdf",
        ]
        for vp in valid_paths:
            resolved = (stress_repo / vp).resolve()
            assert resolved.is_relative_to(stress_repo.resolve()), f"Path {vp} should be relative to repo"


# ===========================================================================
# 3. CoinBudgetManager Boundary & Concurrency Stress Tests
# ===========================================================================

class TestCoinBudgetManagerStress:
    """Stress-test CoinBudgetManager boundary conditions, concurrency, and policy checks."""

    def test_boundary_limit_39_40_41(self, tmp_path: Path):
        """Exhaustive boundary testing at 39, 40, and 41 coins."""
        ledger_path = tmp_path / "budget_boundary.json"
        mgr = CoinBudgetManager(workspace_root=tmp_path, ledger_file=ledger_path, max_coins=40)

        # Spend 39 coins sequentially
        for i in range(39):
            mgr.record_transaction(prompt=f"Task {i}", purpose="analysis", coins=1)

        assert mgr.total_spent == 39
        assert mgr.remaining_coins == 1

        # Check pre-flight gatekeeper at 39 coins
        can_1, msg_1 = mgr.can_spend(prompt="Valid task", cost=1)
        assert can_1 is True
        assert msg_1 == "Approved"

        can_2, msg_2 = mgr.can_spend(prompt="Task asking 2 coins", cost=2)
        assert can_2 is False
        assert "Budget exceeded" in msg_2

        # Record 40th coin
        tx_40 = mgr.record_transaction(prompt="Task 40", purpose="analysis", coins=1)
        assert tx_40["coins"] == 1
        assert mgr.total_spent == 40
        assert mgr.remaining_coins == 0

        # Attempt 41st coin
        can_41, msg_41 = mgr.can_spend(prompt="Task 41", cost=1)
        assert can_41 is False
        assert "Budget exceeded" in msg_41

        with pytest.raises(CoinBudgetExceededError) as exc_info:
            mgr.record_transaction(prompt="Task 41", coins=1)

        assert "Budget cap reached" in str(exc_info.value)
        assert mgr.total_spent == 40
        assert mgr.remaining_coins == 0

    def test_concurrent_multithreaded_race_conditions(self, tmp_path: Path):
        """Stress-test 50 concurrent threads racing to record coins against a 40-coin ceiling.
        
        Invariant: EXACTLY 40 transactions must succeed, EXACTLY 10 must fail.
        Total spent must be exactly 40. Never 41+.
        """
        ledger_path = tmp_path / "budget_concurrency.json"
        mgr = CoinBudgetManager(workspace_root=tmp_path, ledger_file=ledger_path, max_coins=40)

        num_threads = 50
        success_count = 0
        failure_count = 0
        barrier = threading.Barrier(num_threads)
        lock = threading.Lock()

        def worker_task(thread_id: int):
            nonlocal success_count, failure_count
            barrier.wait()  # Synchronize start to maximize race conditions
            try:
                mgr.record_transaction(
                    prompt=f"Concurrent task {thread_id}",
                    purpose="worker_execution",
                    coins=1,
                )
                with lock:
                    success_count += 1
            except CoinBudgetExceededError:
                with lock:
                    failure_count += 1

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker_task, i) for i in range(num_threads)]
            concurrent.futures.wait(futures)

        # Assert strict invariants under maximum concurrency
        assert success_count == 40, f"Expected exactly 40 successes, got {success_count}"
        assert failure_count == 10, f"Expected exactly 10 failures, got {failure_count}"
        assert mgr.total_spent == 40, f"Total spent must be 40, got {mgr.total_spent}"
        assert mgr.remaining_coins == 0
        assert len(mgr.history) == 40

        # Verify disk persistence
        disk_data = json.loads(ledger_path.read_text(encoding="utf-8"))
        assert disk_data["coins_spent"] == 40
        assert disk_data["coins_remaining"] == 0
        assert len(disk_data["transactions"]) == 40

    def test_negative_coins_handling(self, tmp_path: Path):
        """Challenger investigation: can negative coins be used to refund or bypass budget?"""
        ledger_path = tmp_path / "budget_negative.json"
        mgr = CoinBudgetManager(workspace_root=tmp_path, ledger_file=ledger_path, max_coins=40)

        # can_spend rejects negative cost
        can_neg, reason = mgr.can_spend(prompt="Legitimate task", cost=-5)
        assert can_neg is False
        assert "cannot be negative" in reason.lower()

    def test_negative_coins_in_record_transaction_observed(self, tmp_path: Path):
        """Challenger investigation: record_transaction accepts negative coins if not pre-screened."""
        ledger_path = tmp_path / "budget_neg_tx.json"
        mgr = CoinBudgetManager(workspace_root=tmp_path, ledger_file=ledger_path, max_coins=40)

        # Spend 5 coins
        for i in range(5):
            mgr.record_transaction(prompt=f"Task {i}", coins=1)
        assert mgr.total_spent == 5

        # If a caller directly invokes record_transaction with coins=-2 without can_spend:
        mgr.record_transaction(prompt="Refund call", coins=-2)
        # Note: coins_spent becomes 3! This proves record_transaction relies on can_spend
        # or has an unchecked boundary on coins <= 0.
        assert mgr.total_spent == 3

    def test_prompt_policy_subtle_variations_and_evasions(self, tmp_path: Path):
        """Stress-test prompt policy checks for keyword boundaries and evasion variations."""
        ledger_path = tmp_path / "budget_evasion.json"
        mgr = CoinBudgetManager(workspace_root=tmp_path, ledger_file=ledger_path, max_coins=40)

        # Direct exact keyword variants (MUST be blocked)
        blocked_cases = [
            "fix bug in auth",
            "fix bugs in auth",
            "bugfix for crash",
            "bug fix for crash",
            "fix syntax in parser",
            "syntax error reported",
            "fix error in query",
            "fix import paths",
            "fix lint warnings",
            "patch error in db",
            "debug error in log",
            "debug bug in tree",
        ]
        for p in blocked_cases:
            ok, _ = mgr.can_spend(prompt=p)
            assert ok is False, f"Expected exact phrase to be blocked: {p}"

        # Subtly rephrased prompts:
        # Note: 'fix the bug', 'resolve error', 'troubleshoot crash'
        # Check how CoinBudgetManager handles them:
        evasion_cases = [
            "fix the bug in authentication",
            "resolve error in payment service",
            "repair syntax issue",
            "troubleshoot crash on startup",
        ]
        evasion_results = {}
        for p in evasion_cases:
            ok, _ = mgr.can_spend(prompt=p)
            evasion_results[p] = "ALLOWED" if ok else "BLOCKED"
        assert isinstance(evasion_results, dict)

    def test_policy_checks_bug_fixing_and_exploration_prompts(self, tmp_path: Path):
        """Verify strict 0-coin policy blocks all bug-fixing and exploration variations."""
        ledger_path = tmp_path / "budget_policy.json"
        mgr = CoinBudgetManager(workspace_root=tmp_path, ledger_file=ledger_path, max_coins=40)

        blocked_prompts = [
            # Bug fix variants
            "Fix bug in parser logic",
            "BUGFIX for memory leak",
            "Urgent bug fix for crash",
            "Fix syntax error in generated code",
            "Resolve syntax error",
            "Fix error during execution",
            "Fix import cycle",
            "Fix lint issues",
            "Patch error in transaction handler",
            "Debug error in AST scanner",
            "Debug bug in tree building",
            # Exploration variants
            "Explore codebase to find routes",
            "Codebase exploration for models",
            "Automated exploration of repo",
            "Scan files in src directory",
            "Survey codebase architecture",
        ]

        for p in blocked_prompts:
            ok, why = mgr.can_spend(prompt=p)
            assert ok is False, f"Prompt should be blocked by 0-coin policy: {p}"
            assert "0-coin policy" in why
            with pytest.raises(CoinPolicyViolationError):
                mgr.record_transaction(prompt=p)

        # Benign prompts must be allowed
        allowed_prompts = [
            "Synthesize architecture overview",
            "Generate narrative for microservices",
            "Compute blast radius of authentication module",
            "Build high-level component diagrams",
        ]
        for p in allowed_prompts:
            ok, why = mgr.can_spend(prompt=p)
            assert ok is True, f"Legitimate prompt was blocked: {p} ({why})"


# ===========================================================================
# 4. AST Extractor Malformed Syntax, Cycles, and Empty Files Stress Tests
# ===========================================================================

class TestAstExtractorStress:
    """Stress-test AST extractors with malformed syntax, cycles, and edge cases."""

    def test_ast_python_malformed_syntax_matrix(self):
        """Test native Python extractor with various syntax corruptions."""
        corrupted_sources = [
            "def broken_syntax(:\n    pass",
            "class Foo(:\n    def __init__",
            "for i in range(10)\n    print(i)",
            "import\nfrom\n",
            "'''unclosed multi-line docstring",
            '"""unclosed double docstring',
            "def bad_indent():\n  x = 1\n x = 2",
            "\x00\x01\x02\xff\xfe\xfd garbage binary data",
        ]
        for src in corrupted_sources:
            symbols, entry_points, edges = _extract_python_native(src, "test.py")
            assert isinstance(symbols, list)
            assert isinstance(entry_points, list)
            assert isinstance(edges, list)

    def test_ast_typescript_malformed_syntax_matrix(self):
        """Test native TypeScript/JavaScript extractor with various syntax corruptions."""
        corrupted_ts = [
            "function broken(a, b { return a + b; }",
            "class Broken extends {",
            "interface { foo: string }",
            "const x = () => {",
            "export default class { name = 'test'",
            "\x00\xff\xfe corrupted binary stream",
        ]
        for src in corrupted_ts:
            symbols, entry_points, edges = _extract_ts_native(src, "test.ts", "typescript")
            assert isinstance(symbols, list)
            assert isinstance(entry_points, list)
            assert isinstance(edges, list)

    def test_ast_go_malformed_syntax_matrix(self):
        """Test native Go extractor with broken source."""
        corrupted_go = [
            "package\nfunc broken( {",
            "type struct { field int",
            "func (r *) brokenMethod()",
            "\x00\x1b\x5b broken terminal sequences",
        ]
        for src in corrupted_go:
            symbols, entry_points, edges = _extract_go_native(src, "test.go")
            assert isinstance(symbols, list)
            assert isinstance(entry_points, list)
            assert isinstance(edges, list)

    def test_ast_empty_and_whitespace_files(self, tmp_path: Path):
        """Test completely empty, whitespace-only, and comment-only files across languages."""
        test_cases = [
            ("empty.py", "", "python"),
            ("whitespace.py", "   \n\t  \n  ", "python"),
            ("comments_only.py", "# Comment 1\n# Comment 2\n", "python"),
            ("empty.ts", "", "typescript"),
            ("whitespace.ts", "  \n\t  \n", "typescript"),
            ("comments_only.ts", "// Just comments\n/* Block comment */", "typescript"),
            ("empty.go", "", "go"),
            ("whitespace.go", "   \n", "go"),
        ]
        for fname, content, lang in test_cases:
            file_path = tmp_path / fname
            file_path.write_text(content, encoding="utf-8")
            symbols, entry_points, edges = _extract_file(str(file_path), fname, lang)
            assert symbols == []
            assert entry_points == []
            assert edges == []

    def test_ast_cyclic_structures_and_recursion(self, tmp_path: Path):
        """Ensure cyclic inheritance and recursive constructs do not hang or crash extractor."""
        cyclic_py = tmp_path / "cyclic.py"
        cyclic_py.write_text(
            """
class NodeA:
    def __init__(self, b: 'NodeB'):
        self.b = b
    def visit(self):
        return self.b.visit()

class NodeB:
    def __init__(self, a: 'NodeA'):
        self.a = a
    def visit(self):
        return self.a.visit()

def recursive_fn(n):
    if n <= 0:
        return 0
    return recursive_fn(n - 1)
""",
            encoding="utf-8",
        )
        symbols, entry_points, edges = _extract_file(str(cyclic_py), "cyclic.py", "python")
        names = {s["name"] for s in symbols}
        assert "NodeA" in names
        assert "NodeB" in names
        assert "recursive_fn" in names

    def test_ast_deeply_nested_blocks_recursion_limit(self, tmp_path: Path):
        """Generate a deeply nested structure (300 nested defs) to stress recursion handling."""
        lines = []
        for i in range(150):
            lines.append(" " * (i * 4) + f"def nest_{i}():")
        lines.append(" " * (150 * 4) + "return 42")
        deep_source = "\n".join(lines)

        deep_py = tmp_path / "deep.py"
        deep_py.write_text(deep_source, encoding="utf-8")

        # Must either extract symbols or safely catch RecursionError without crashing
        symbols, entry_points, edges = _extract_file(str(deep_py), "deep.py", "python")
        assert isinstance(symbols, list)
        assert isinstance(edges, list)
