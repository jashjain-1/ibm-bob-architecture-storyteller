"""
Unit and Integration Tests for tools/py-ast-core
Verifies:
  1. extract_repo_ast_impl (AST extraction, symbols, calls, imports, entry points, edges)
  2. detect_dynamic_invocations_impl (all 6 dynamic patterns across languages)
"""

import asyncio
import os
import sys
from pathlib import Path

# Add tools/py-ast-core to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from ast_extractor import extract_repo_ast_impl
from dynamic_detector import detect_dynamic_invocations_impl


@pytest.fixture
def sample_repo(tmp_path):
    """Creates a miniature multi-language repository for AST testing."""
    py_file = tmp_path / "main.py"
    py_file.write_text(
        """import sys
from os import path

class DataProcessor:
    def process_record(self, item: str) -> dict:
        return {"data": item}

def helper():
    return True

def main():
    dp = DataProcessor()
    dp.process_record("sample")
    helper()

if __name__ == '__main__':
    main()
""",
        encoding="utf-8",
    )

    go_file = tmp_path / "server.go"
    go_file.write_text(
        """package main

import (
    "fmt"
    "net/http"
)

type Config struct {
    Port int
}

func StartServer(cfg Config) error {
    fmt.Println(cfg.Port)
    return nil
}

func main() {
    StartServer(Config{Port: 8080})
}
""",
        encoding="utf-8",
    )

    ts_file = tmp_path / "client.ts"
    ts_file.write_text(
        """import axios from 'axios';

export interface User {
    id: string;
    name: string;
}

export class Client {
    connect(): void {
        console.log("connected");
    }
}

export function fetchUser(id: string): Promise<User> {
    return axios.get('/user/' + id);
}
""",
        encoding="utf-8",
    )

    return tmp_path


@pytest.fixture
def dynamic_sample_file(tmp_path):
    """Creates a sample file containing all 6 dynamic invocation patterns."""
    sample = tmp_path / "dynamic_sample.py"
    sample.write_text(
        """import os
import importlib

class DynamicService:
    def run_dynamic(self, mode: str):
        # 1. Reflection
        method = getattr(self, mode)
        setattr(self, "state", "ready")
        
        # 2. Dynamic import
        mod = importlib.import_module("json")
        
        # 3. Eval
        result = eval("10 * 20")
        
        # 4. Env conditional
        token = os.getenv("API_TOKEN")
        secret = os.environ["SECRET"]
        
        # 5. String dispatch
        handlers = {"a": lambda: 1}
        handlers[mode]()
        
        # 6. Event emitter
        self.emit("completed", result)
""",
        encoding="utf-8",
    )
    return sample


def test_extract_repo_ast_structure(sample_repo):
    """Validates that extract_repo_ast_impl returns conformant JSON with all keys."""
    res = asyncio.run(extract_repo_ast_impl(str(sample_repo)))
    
    assert "repo_path" in res
    assert "languages_detected" in res
    assert "files_parsed" in res
    assert "symbols" in res
    assert "entry_points" in res
    assert "edges" in res

    assert res["files_parsed"] == 3
    assert set(res["languages_detected"]) == {"python", "go", "typescript"}

    # Check python symbols
    symbol_names = [s["name"] for s in res["symbols"]]
    assert "DataProcessor" in symbol_names
    assert "process_record" in symbol_names
    assert "main" in symbol_names
    assert "StartServer" in symbol_names
    assert "Client" in symbol_names
    assert "fetchUser" in symbol_names

    # Check entry points
    entry_types = [ep["type"] for ep in res["entry_points"]]
    assert "main" in entry_types

    # Check edges
    edge_types = {e["type"] for e in res["edges"]}
    assert "imports" in edge_types
    assert "calls" in edge_types


def test_extract_repo_ast_filter_languages(sample_repo):
    """Validates language filtering parameter."""
    res = asyncio.run(extract_repo_ast_impl(str(sample_repo), languages=["python"]))
    assert res["files_parsed"] == 1
    assert res["languages_detected"] == ["python"]


def test_extract_repo_ast_exclude_patterns(sample_repo):
    """Validates exclude_patterns glob support."""
    res = asyncio.run(extract_repo_ast_impl(str(sample_repo), exclude_patterns=["*.go", "*.ts"]))
    assert res["files_parsed"] == 1
    assert res["languages_detected"] == ["python"]


def test_detect_dynamic_invocations(dynamic_sample_file):
    """Validates detection of dynamic patterns with confidence scores."""
    detections = asyncio.run(detect_dynamic_invocations_impl(str(dynamic_sample_file)))
    
    detected_patterns = {d["pattern_type"] for d in detections}
    assert "reflection" in detected_patterns
    assert "dynamic_import" in detected_patterns
    assert "eval" in detected_patterns
    assert "env_conditional" in detected_patterns
    assert "string_dispatch" in detected_patterns
    assert "event_emitter" in detected_patterns

    # Check item schema
    for d in detections:
        assert "pattern_type" in d
        assert "file_path" in d
        assert "line_number" in d
        assert "symbol_id" in d
        assert "confidence" in d
        assert 0.0 <= d["confidence"] <= 1.0
        assert "description" in d


def test_detect_dynamic_invocations_filtered_pattern(dynamic_sample_file):
    """Validates pattern filtering parameter."""
    detections = asyncio.run(
        detect_dynamic_invocations_impl(str(dynamic_sample_file), patterns=["eval", "reflection"])
    )
    detected_patterns = {d["pattern_type"] for d in detections}
    assert detected_patterns.issubset({"eval", "reflection"})
    assert "dynamic_import" not in detected_patterns


def test_server_fastapi_endpoints(sample_repo, dynamic_sample_file):
    """Validates FastAPI server endpoints match tool-schemas.json specification."""
    import importlib.util
    from fastapi.testclient import TestClient

    server_path = Path(__file__).resolve().parent.parent / "server.py"
    spec = importlib.util.spec_from_file_location("py_ast_core_server", server_path)
    ast_server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ast_server)

    client = TestClient(ast_server.app)

    # 1. Health endpoint
    health_resp = client.get("/health")
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] == "ok"

    # 2. extract_repo_ast endpoint
    ast_resp = client.post(
        "/tools/extract_repo_ast",
        json={"repo_path": str(sample_repo)},
    )
    assert ast_resp.status_code == 200
    data = ast_resp.json()
    assert data["files_parsed"] >= 3
    assert len(data["symbols"]) > 0

    # 3. detect_dynamic_invocations endpoint
    dyn_resp = client.post(
        "/tools/detect_dynamic_invocations",
        json={"file_path": str(dynamic_sample_file)},
    )
    assert dyn_resp.status_code == 200
    dyn_data = dyn_resp.json()
    assert len(dyn_data) >= 5

