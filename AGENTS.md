# Architecture Storyteller 2.0 & Ripple-Agent

This repository defines multi-agent guidelines, tool schemas, and operational boundaries for IBM Bob IDE and Antigravity.

## Agent System Overview

Architecture Storyteller 2.0 operates as a multi-tier agentic architecture:
- **Master Orchestrator Agent**: Dispatches specialized subagents, enforces concurrency boundaries, and manages the 40-coin budget funnel (`tools/storyteller-engine/coin_ledger.py`).
- **Sub-agent 1: Change Analyzer (`ripple_agent.py`)**: Analyzes proposed code diffs and maps AST signature changes across Python, TypeScript, JavaScript, and Go.
- **Sub-agent 2: Parallel Downstream Scanners (`ripple_agent.py`)**: Crawls callers, API definitions, and module boundaries in parallel using Tarjan SCC cycle detection.
- **Bob Semantic Impact Synthesizer (`scripts/bob_bridge.py`)**: Evaluates cross-file contract breakage, assigns blast radius tiers (🟢 Safe / 🟡 Moderate / 🔴 High), and generates 1-click surgical compatibility patches.
- **Independent Verification Subagent**: Runs 80 test assertions across AST parsing, cache invalidation, security hardening, and extension locate discovery.

## Tool Registry

| Tool | Responsibility | Language / Runtime |
|---|---|---|
| `py-ast-core` | Polyglot AST extraction & call graph mapping | Python 3.10+ |
| `storyteller-engine` | Localhost HTTP daemon, SHA-256 caching, dossier generator | Python 3.10+ |
| `vscode-extension` | Interactive Webview map, badges, status bar, diff preview | TypeScript / Node.js 18+ |
| `bob_bridge` | Headless IBM Bob CLI invocation with argument sanitization | Python / Bob IDE CLI |
| `coin_ledger` | 40-coin ceiling enforcement & 0-coin policy | Python 3.10+ |

## Rules & Invariants

1. **Zero Drift**: All views (mindmaps, dossiers, badges) read from the identical underlying AST model and content-hash cache.
2. **0-Coin Policy**: Bug fixes and local AST lookups consume 0 coins. Only deep semantic impact generation consumes Bob LLM coins.
3. **Security Boundaries**: Localhost HTTP daemon strictly rejects non-loopback `Host` headers (DNS rebinding guard) and non-local origins (CORS guard).
