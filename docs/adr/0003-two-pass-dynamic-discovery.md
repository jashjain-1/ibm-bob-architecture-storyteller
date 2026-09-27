# ADR-0003: 2-Pass Dynamic Dependency Discovery Pipeline

**Date**: 2026-09-26  
**Status**: accepted  
**Deciders**: Jash (Lead), Harsh  

## Context

Pure static AST analysis consistently fails to detect dynamic behaviors:
- String-based function dispatch and reflection (`getattr()`, `reflect.ValueOf()`)
- Dynamic runtime imports (`importlib.import_module()`, `require(variable)`)
- Environment-conditional routing (`os.getenv("MODE")`)
- Event emitters and decoupled pub/sub message buses

Refactoring based solely on static edges silently breaks these hidden execution paths at runtime. Conversely, dynamic runtime tracing alone is slow, requires comprehensive test suites, and misses unexecuted branches.

## Decision

We mandate a **2-Pass Dynamic Dependency Discovery Pipeline**:
1. **Pass 1 (Static Heuristics)**: `py-ast-core:detect_dynamic_invocations` scans the AST for dynamic call patterns, flagging potential hidden edges with confidence scores.
2. **Pass 2 (Runtime Test Traces)**: `go-runtime-cli:capture_runtime_trace` executes instrumented test suites in the isolated worktree via the Bob Shell, intercepting runtime function dispatches and event emissions.
3. **Reconciliation Loop**: Any unmapped call edge discovered during Pass 1 or 2 is recorded in `DiscoveredDependencies.json`, triggering cluster expansion and co-lock acquisition before code modifications are merged.

## Alternatives Considered

### Alternative 1: Pure Static AST Analysis
- **Pros**: Fast, does not require running tests or setting up runtime environments.
- **Cons**: Misses up to 30% of runtime dependencies in modern event-driven and dynamic Python/TS architectures.
- **Why not**: Causes silent runtime regressions.

### Alternative 2: Full Formal Dynamic Symbolic Execution (Concolic Testing)
- **Pros**: Complete formal path coverage.
- **Cons**: Extremely complex, prohibitive computational overhead, unsuitable for hackathon timeframes.
- **Why not**: Over-engineering that degrades developer responsiveness.

## Consequences

### Positive
- Guaranteed zero hidden breakage during multi-agent refactoring.
- Empirical test trace verification backing all cluster boundary definitions.

### Negative
- Requires target repositories to have runnable unit/integration tests for Pass 2.

### Risks
- Codebases without test suites fall back to Pass 1 static heuristics with explicit warnings in the generated `ONBOARDING.md`.
