"""
py-ast-core MCP Tool Server
============================
FastAPI-based MCP server exposing two tools:
  1. extract_repo_ast   — Whole-codebase AST extraction via Tree-Sitter
  2. detect_dynamic_invocations — Dynamic pattern detection (reflection, eval, etc.)

Conforms to tool-schemas.json interface contract.
"""

from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Optional

from ast_extractor import extract_repo_ast_impl
from dynamic_detector import detect_dynamic_invocations_impl

app = FastAPI(
    title="py-ast-core MCP Server",
    description="Python AST engine for polyglot repository analysis",
    version="1.0.0",
)


# ── Request / Response Models ────────────────────────────────────────────────

class ExtractRepoAstRequest(BaseModel):
    repo_path: str = Field(..., description="Absolute path to the repository root directory.")
    languages: Optional[list[str]] = Field(
        default=None,
        description="Languages to parse. Auto-detects from file extensions if omitted.",
    )
    include_patterns: Optional[list[str]] = Field(
        default=None,
        description="Glob patterns for files to include.",
    )
    exclude_patterns: Optional[list[str]] = Field(
        default=None,
        description="Glob patterns for files to exclude.",
    )


class DetectDynamicInvocationsRequest(BaseModel):
    file_path: str = Field(..., description="Absolute path to the file to scan.")
    symbol_id: Optional[str] = Field(
        default=None,
        description="Qualified symbol name to scope the scan.",
    )
    patterns: Optional[list[str]] = Field(
        default=None,
        description="Specific dynamic patterns to scan for. Defaults to all.",
    )


# ── Tool Endpoints ───────────────────────────────────────────────────────────

@app.post("/tools/extract_repo_ast")
async def extract_repo_ast(request: ExtractRepoAstRequest):
    """Scans repository files and extracts whole-codebase AST into normalized JSON."""
    return await extract_repo_ast_impl(
        repo_path=request.repo_path,
        languages=request.languages,
        include_patterns=request.include_patterns,
        exclude_patterns=request.exclude_patterns,
    )


@app.post("/tools/detect_dynamic_invocations")
async def detect_dynamic_invocations(request: DetectDynamicInvocationsRequest):
    """Scans AST for dynamic invocation patterns."""
    return await detect_dynamic_invocations_impl(
        file_path=request.file_path,
        symbol_id=request.symbol_id,
        patterns=request.patterns,
    )


@app.get("/health")
async def health():
    return {"status": "ok", "server": "py-ast-core", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
