"""
test_ripple_agent.py
~~~~~~~~~~~~~~~~~~~~
Tests for Ripple-Agent personas, blast radius tiers, downstream scanners, and doc generator.
"""

import sys
from pathlib import Path
import pytest

ENGINE = Path(__file__).resolve().parent.parent
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from ripple_agent import (
    compute_workspace_dependencies,
    analyze_change,
    scan_downstream,
    synthesize_ripple_and_patches,
    generate_documentation,
)


@pytest.fixture
def mock_model():
    return {
        "repo": {"name": "test_repo", "root": "/workspace"},
        "schema": "architecture-model@2",
        "files": [
            {"path": "core/auth.py", "is_production": True, "loc": 100},
            {"path": "services/user_service.py", "is_production": True, "loc": 150},
            {"path": "api/routes.py", "is_production": True, "loc": 80},
            {"path": "tests/test_auth.py", "is_production": False, "is_test": True, "loc": 60},
        ],
        "symbols": [
            {
                "id": "sym:core/auth.py:verify_token",
                "name": "verify_token",
                "kind": "function",
                "file_path": "core/auth.py",
                "line_start": 10,
                "complexity": 3,
                "callers": [
                    "sym:services/user_service.py:get_current_user",
                    "sym:api/routes.py:login_endpoint",
                    "sym:tests/test_auth.py:test_verify_token",
                ],
                "calls": [],
                "raw_calls": [],
            },
            {
                "id": "sym:services/user_service.py:get_current_user",
                "name": "get_current_user",
                "kind": "function",
                "file_path": "services/user_service.py",
                "line_start": 25,
                "complexity": 2,
                "callers": ["sym:api/routes.py:login_endpoint"],
                "calls": ["sym:core/auth.py:verify_token"],
                "raw_calls": ["verify_token(token)"],
            },
            {
                "id": "sym:api/routes.py:login_endpoint",
                "name": "login_endpoint",
                "kind": "function",
                "file_path": "api/routes.py",
                "line_start": 40,
                "complexity": 4,
                "callers": [],
                "calls": ["sym:core/auth.py:verify_token", "sym:services/user_service.py:get_current_user"],
                "raw_calls": ["verify_token()", "get_current_user()"],
            },
            {
                "id": "sym:tests/test_auth.py:test_verify_token",
                "name": "test_verify_token",
                "kind": "function",
                "file_path": "tests/test_auth.py",
                "is_test": True,
                "line_start": 5,
                "complexity": 1,
                "callers": [],
                "calls": ["sym:core/auth.py:verify_token"],
                "raw_calls": ["verify_token('dummy')"],
            },
        ],
        "entry_points": [
            {
                "symbol_id": "sym:api/routes.py:login_endpoint",
                "name": "login_endpoint",
                "file_path": "api/routes.py",
                "line": 40,
            }
        ],
    }


def test_compute_workspace_dependencies(mock_model):
    deps = compute_workspace_dependencies(mock_model)
    assert "files" in deps
    files = deps["files"]
    assert "core/auth.py" in files
    auth_info = files["core/auth.py"]
    # 3 external dependent files: user_service.py, routes.py, test_auth.py
    assert auth_info["dependents_count"] == 3
    # 3 dependents = yellow tier
    assert auth_info["tier"] == "yellow"

    # api/routes.py has 0 inbound callers
    routes_info = files["api/routes.py"]
    assert routes_info["dependents_count"] == 0
    assert routes_info["tier"] == "green"


def test_change_analyzer():
    symbol = {"name": "update_user_status", "kind": "function", "file_path": "models/user.py", "line_start": 30}
    analysis = analyze_change(symbol, "def update_user_status(): pass", "signature")
    assert analysis["change_type"] == "SIGNATURE_AMENDMENT"
    assert "update_user_status" in analysis["symbol_name"]
    assert len(analysis["contract_invariants"]) > 0


def test_downstream_scanner(mock_model):
    symbol = mock_model["symbols"][0]  # verify_token
    analysis = analyze_change(symbol, "def verify_token(): pass", "delete")
    findings = scan_downstream(mock_model, symbol, analysis)
    assert len(findings) >= 3
    files_affected = [f["file"] for f in findings]
    assert "services/user_service.py" in files_affected
    assert "api/routes.py" in files_affected
    assert "tests/test_auth.py" in files_affected


def test_synthesize_ripple_and_patches(mock_model, tmp_path):
    symbol = mock_model["symbols"][0]
    result = synthesize_ripple_and_patches(
        repo_root=tmp_path,
        model=mock_model,
        symbol=symbol,
        code_snippet="def verify_token(token: str) -> bool: pass",
        scenario="change signature",
        bob_command=None,
    )
    assert result["symbol_name"] == "verify_token"
    assert "Warning" in result["semantic_warning"]
    assert result["blast_radius_tier"] in ("green", "yellow", "red")
    assert len(result["downstream_findings"]) >= 3


def test_generate_documentation(tmp_path):
    symbol = {"name": "calculate_hash", "kind": "function", "complexity": 3, "callers": ["a", "b"]}
    doc_py = generate_documentation(tmp_path, symbol, "def calculate_hash(): pass", "utils/crypto.py", "python")
    assert "calculate_hash" in doc_py["docstring"].lower()
    assert '"""' in doc_py["docstring"]

    doc_ts = generate_documentation(tmp_path, symbol, "export function calculateHash() {}", "utils/crypto.ts", "typescript")
    assert "/**" in doc_ts["docstring"]
    assert "*/" in doc_ts["docstring"]

    doc_go = generate_documentation(tmp_path, symbol, "func CalculateHash() {}", "crypto/hash.go", "go")
    assert "//" in doc_go["docstring"]


def test_polyglot_preventive_patch_comment_syntax(mock_model, tmp_path):
    # Setup test caller files on disk
    py_caller = tmp_path / "services" / "user_service.py"
    py_caller.parent.mkdir(parents=True, exist_ok=True)
    py_caller.write_text("def get_current_user():\n    return verify_token()\n", encoding="utf-8")

    ts_caller = tmp_path / "api" / "routes.ts"
    ts_caller.parent.mkdir(parents=True, exist_ok=True)
    ts_caller.write_text("export function loginEndpoint() {\n    return verify_token();\n}\n", encoding="utf-8")

    # Update mock model symbol callers
    model_poly = dict(mock_model)
    model_poly["symbols"] = list(mock_model["symbols"])
    model_poly["symbols"].append({
        "id": "sym:api/routes.ts:loginEndpoint",
        "name": "loginEndpoint",
        "kind": "function",
        "file_path": "api/routes.ts",
        "line_start": 1,
        "complexity": 1,
        "callers": [],
        "calls": ["sym:core/auth.py:verify_token"],
        "raw_calls": ["verify_token()"],
    })
    model_poly["symbols"][0]["callers"].append("sym:api/routes.ts:loginEndpoint")

    symbol = model_poly["symbols"][0]
    result = synthesize_ripple_and_patches(
        repo_root=tmp_path,
        model=model_poly,
        symbol=symbol,
        code_snippet="def verify_token(token: str) -> bool: pass",
        scenario="change signature",
        bob_command=None,
    )

    patches = {p["file"]: p for p in result["preventive_patches"]}
    if "api/routes.ts" in patches:
        assert "// TODO(ripple-agent):" in patches["api/routes.ts"]["patched_content"]
    if "services/user_service.py" in patches:
        assert "# TODO(ripple-agent):" in patches["services/user_service.py"]["patched_content"]

