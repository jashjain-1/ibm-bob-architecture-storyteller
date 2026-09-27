# ADR-0004: Zero-Collision Directory-Isolated Branching Strategy

**Date**: 2026-09-26  
**Status**: accepted  
**Deciders**: Jash (Lead), Team  

## Context

A team of 4 developers (Jash, Harsh, Anjali, Bhargavi) is developing the 4 core subsystems concurrently under a finite coin budget (40 Bob coins each = 160 coins total). Traditional shared branches lead to frequent merge conflicts, overwriting of in-progress prompts, and wasted Bob coins fixing merge regressions.

## Decision

We establish an immutable **Zero-Collision Directory-Isolated Branching Strategy**:
1. Each team member owns a strictly isolated subdirectory under `tools/`:
   - Jash: `tools/py-ast-core/` on branch `feature/jash-py-ast-core`
   - Harsh: `tools/go-runtime-cli/` on branch `feature/harsh-go-runtime-cli`
   - Anjali: `tools/lock-manager/` on branch `feature/anjali-lock-manager`
   - Bhargavi: `tools/ts-env-worker/` on branch `feature/bhargavi-ts-env-worker`
2. No team member modifies files in another member's directory without an explicit handoff.
3. Integration is orchestrated via a Fan-In Merge into `main` using linear fast-forward and clean three-way merges.
4. An automated bridge (`scripts/bob_bridge.py`) enforces rebase onto `origin/main` before every Bob dispatch and auto-pushes verified code.

## Alternatives Considered

### Alternative 1: Monolithic Single Feature Branch (`develop`)
- **Pros**: Everyone commits to one place.
- **Cons**: Massive git conflicts between 4 concurrent Bob AI sessions; stale branch states.
- **Why not**: Violates coin preservation rules (wasting coins on git conflict resolution).

### Alternative 2: Separate Standalone Repositories (Micro-repos)
- **Pros**: Complete repository-level isolation.
- **Cons**: High overhead for CI, cross-engine integration tests, and hackathon judge evaluation.
- **Why not**: Prevents unified mono-repo demonstration and packaging.

## Consequences

### Positive
- Mathematically zero git merge conflicts across all team member PRs.
- Clear individual accountability for coin consumption and test coverage.
- Clean linear integration into `main`.

### Negative
- Requires maintaining 4 remote tracking branches.
