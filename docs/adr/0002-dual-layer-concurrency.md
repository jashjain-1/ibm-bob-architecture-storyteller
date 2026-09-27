# ADR-0002: Dual-Layer Concurrency Model via Worktrees and Reactive Locks

**Date**: 2026-09-26  
**Status**: accepted  
**Deciders**: Jash (Lead), Anjali, Harsh  

## Context

When multiple autonomous AI subagents refactor an enterprise repository simultaneously, two severe concurrency failure modes occur:
1. **Filesystem Collision**: Agents overwrite each other's in-progress changes on disk, corrupting source files.
2. **Logical Symbol Collision**: Even if operating in separate branches, multiple agents modifying coupled functions or shared data contracts create circular breaking changes and unmergeable git conflicts.

## Decision

We establish a **Dual-Layer Concurrency Model**:
- **Layer 1 (Physical Filesystem Isolation)**: Subagents never modify the main working tree directly. Each cluster agent is provisioned an isolated Git Worktree (`../worktrees/agent-cluster-<id>`).
- **Layer 2 (Logical Symbol-Level Reactive Locks)**: Before reading or mutating any symbol, subagents must acquire an exclusive or shared lock from the centralized `lock-manager`. Conflicting requests wait or trigger atomic co-locking. If a circular wait is detected, the engine executes DFS cycle detection and resolves it by merging agents or releasing the oldest lock.

## Alternatives Considered

### Alternative 1: Sequential Agent Execution
- **Pros**: Trivially eliminates collisions.
- **Cons**: Refactoring large polyglot codebases becomes agonizingly slow; completely fails the hackathon's "Parallel Tasks" evaluation criterion.
- **Why not**: Sacrifices modern multi-core, multi-agent throughput.

### Alternative 2: File-Level OS File Locking (`flock`)
- **Pros**: Standard OS primitives.
- **Cons**: Granularity is too coarse (blocks entire 2,000-line files for a 5-line function edit) and does not understand AST symbols or cross-file type contracts.
- **Why not**: Leads to unnecessary blocking and cannot detect deadlocks between interdependent semantic symbols.

## Consequences

### Positive
- Zero in-place file collisions.
- True concurrent parallel refactoring across independent function clusters (Cluster A and Cluster B).
- Formal deadlock prevention with DFS cycle detection.

### Negative
- Git worktree creation and cleanup overhead.
- Symbol lock lifecycle must be strictly managed with release guarantees.

### Risks
- Orphaned locks if an agent crashes unexpectedly. Mitigated by lock timeouts and `lock_status` introspection with heartbeat release.
