# ADR-0001: Polyglot Multi-Engine Hybrid Architecture

**Date**: 2026-09-26  
**Status**: accepted  
**Deciders**: Jash (Lead), Harsh, Anjali, Bhargavi  

## Context

Enterprise codebases are rarely written in a single programming language. Modern backend systems frequently integrate Go microservices, TypeScript/Node frontends/APIs, and Python data/ML pipelines. Single-language static analysis tools fail when analyzing cross-language boundaries, dynamic imports, and complex call graphs. Furthermore, no single runtime excels at all required tasks: Tree-sitter has mature Python bindings, graph graph-partitioning and worktrees require high-performance concurrency in Go, and TypeScript compiler APIs are native to Node.js.

## Decision

We adopt a **4-engine decoupled micro-tool architecture** using Model Context Protocol (MCP) server standards:
1. `py-ast-core` (Python): Polyglot Tree-Sitter AST extraction and dynamic heuristic pattern detection.
2. `go-runtime-cli` (Go): High-throughput Tarjan Strongly Connected Components (SCC) graph clustering, git worktree lifecycle management, and runtime test trace capture.
3. `ts-env-worker` (TypeScript): Compiler API type-contract verification and dynamic module resolution.
4. `lock-manager` (Python/FastAPI): Centralized symbol-level concurrency lock store and wait-for graph cycle detection.

## Alternatives Considered

### Alternative 1: Monolithic Single-Language Implementation (All-Python or All-TypeScript)
- **Pros**: Simpler single runtime build setup.
- **Cons**: TypeScript compiler API cannot be executed natively in Python without fragile subprocess wrappers; Go's Tarjan performance and native worktree management would be sacrificed.
- **Why not**: Compromises fidelity and performance in analyzing each native language ecosystem.

### Alternative 2: External Hosted SaaS Analysis Engine
- **Pros**: Offloads compute.
- **Cons**: Exposes proprietary code, introduces latency, fails air-gapped/enterprise hackathon judging criteria.
- **Why not**: Violates local execution and zero-data-leakage enterprise requirements.

## Consequences

### Positive
- Each engine leverages the best-in-class native runtime for its specific duty.
- Completely isolated service boundaries matching individual team member specializations.
- Standardized MCP REST/JSON-RPC protocols allow any agent (Bob or Antigravity) to orchestrate tools uniformly.

### Negative
- Multi-runtime developer workstation requirements (Python 3.11+, Node 20+, Go 1.21+).

### Risks
- Inter-process network or serialization overhead. Mitigated by lightweight localhost HTTP calls with compact JSON payloads.
