# ADR-0005: Supervisor-Worker-Reviewer-Challenger (SWRC) Multi-Agent Governance

**Date**: 2026-09-26  
**Status**: accepted  
**Deciders**: Jash (Lead), Antigravity  

## Context

Autonomous multi-agent systems without formal governance suffer from "verification blindness" (agents rubber-stamping broken code), infinite ping-pong review loops, and unbounded recursive subagent spawning that exhausts token and Bob coin budgets.

## Decision

We implement the **Supervisor-Worker-Reviewer-Challenger (SWRC) Quadrilateral Topology**:
- **Supervisor (Lead Orchestrator)**: Compiles the dynamic task Directed Acyclic Graph (DAG), governs token/coin budgets, and arbitrates disputes.
- **Worker (Creator Agent)**: Operates in an isolated worktree, authoring code patches against a strict contract.
- **Reviewer (Gatekeeper Agent)**: Performs deterministic AST verification, type checks, and lint compliance.
- **Challenger (Red-Team Agent)**: Actively probes for edge cases, race conditions, and unhandled exceptions using counterexample tests.

**Governance Limits**:
1. Max revisions $K_{max} = 3$: If worker fails to satisfy the challenger in 3 turns, the supervisor halts the loop and decomposes the problem.
2. Max recursion depth $D_{max} \le 3$: Leaf workers are strictly prohibited from spawning child subagents.
3. 0-Coin Patching Rule: Bug healing, import fixes, and lint resolutions are performed directly by Antigravity on disk for 0 Bob coins.

## Alternatives Considered

### Alternative 1: Single-Agent Generative Loop
- **Pros**: Minimal token overhead.
- **Cons**: High hallucination rate, self-confirmation bias, unnoticed subtle contract regressions.
- **Why not**: Inadmissible for enterprise-grade safe refactoring.

### Alternative 2: Generator-Evaluator Pair (2-Agent)
- **Pros**: Better than 1 agent.
- **Cons**: Evaluator quickly falls into sycophancy or gets stuck in infinite un-arbitrated debate.
- **Why not**: Lacks an adversarial red-teamer (Challenger) and an authoritative tie-breaker (Supervisor).

## Consequences

### Positive
- Strict quality gates backed by deterministic unit tests and adversarial checks.
- Guarantees finite coin consumption with hard circuit breakers.
- Zero silent failure propagation.

### Negative
- Requires structured multi-role prompting and token budget monitoring.
