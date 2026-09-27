---
name: polyglot-onboarding-and-refactor
description: >-
  Automated whole-repo AST analysis, function clustering, subagent dispatch
  with git-worktree isolation, reactive MCP-based locking with deadlock
  detection, and 2-pass dynamic dependency verification for developer
  onboarding and safe legacy modernization across Go, TypeScript, and Python.
tags: [onboarding, modernization, multi-agent, locking, ast, polyglot, refactoring]
version: 1.1.0
---

# Polyglot Onboarding & Safe Refactor Engine

## Purpose

Enables new developers to instantly comprehend, safely navigate, and modernize
complex polyglot repositories without breaking hidden dependencies or creating
merge collisions.

## Prerequisites & Tools

| MCP Server | Language | Responsibility |
| :--- | :--- | :--- |
| `py-ast-core` | Python | AST extraction, call-graph mapping, dynamic invocation detection |
| `go-runtime-cli` | Go | Function clustering (Tarjan SCC), git worktree management, runtime trace capture |
| `ts-env-worker` | TypeScript | JS/TS environment inspection, type-contract validation |
| `lock-manager` | Any | Symbol-level lock acquisition, release, deadlock cycle detection |

Requires: IBM Bob 2.0 Subagent runtime with Bob Shell access.

## Workflow Steps

### Step 1: Ingest & Static AST Mapping
1. Invoke `py-ast-core:extract_repo_ast` across the target directory.
2. Ingest all declarations, types, functions, and import/export links.
3. Identify all primary entry points (`main()`, route controllers, CLI roots).

### Step 2: Function Clustering & Dependency Graphing
1. Pass the AST payload to `go-runtime-cli:cluster_functions`.
2. Group functions into:
   - **Cluster A (Independent):** Isolated utilities and leaf handlers. Zero internal callers.
   - **Cluster B (Interdependent):** Coupled domain services, shared data models, and circular callers.
   - **Cluster C (Delicate / Dynamic):** Reflection, dynamic imports, serialization boundaries, runtime DI.

### Step 3: Subagent Spawning & Isolated Worktree Provisioning
1. For each identified Cluster B and Cluster C, provision a dedicated git worktree:
   ```
   go-runtime-cli:manage_worktree(action="create", branch_name="agent-cluster-<id>")
   ```
2. Spawn specialized subagents in parallel:
   - Assign Go/CLI-heavy clusters to `go-specialist` subagent.
   - Assign TS/Web/Node clusters to `ts-specialist` subagent.
   - Assign Python/AST clusters to `python-specialist` subagent.
3. Cluster A functions may be processed in the main branch without worktree isolation.

### Step 4: Reactive Lock Coordination
1. Every subagent must call `lock-manager:acquire_lock(symbol_id, file_path, agent_id)` before starting work on any symbol.
2. The lock-manager validates that no conflicting locks are active and checks for deadlock cycles via `lock-manager:detect_deadlock`.
3. If an overlapping symbol is needed by multiple subagents, serialize execution or combine tasks into a single worktree.
4. If a deadlock cycle is detected, the Orchestrator merges the conflicting subagent tasks into a single sequential worktree and releases one side of the cycle.

### Step 5: 2-Pass Dynamic Dependency Discovery
1. **Pass 1 (Static Heuristics):** Subagent analyzes static source for dynamic patterns using `py-ast-core:detect_dynamic_invocations`:
   - Python: `getattr`, `importlib.import_module`, `eval`, `exec`
   - Go: `reflect.ValueOf`, `plugin.Open`, interface dispatch
   - JS/TS: `require(variable)`, `import()`, `eval`, event emitters
   - Environment overrides: `os.Getenv`, `process.env`, `os.environ`
2. **Pass 2 (Runtime Test Tracing):** Subagent triggers instrumented test execution using `go-runtime-cli:capture_runtime_trace`:
   ```
   go-runtime-cli:capture_runtime_trace(
     test_command="go test -v -cover ./...",
     trace_output_path="./traces/cluster-<id>.json"
   )
   ```
   For Python: `test_command="pytest --tb=short"`
   For Node/TS: `test_command="npm test"`
3. If an unmapped dependency is discovered:
   - Register it in `DiscoveredDependencies.json`.
   - Call `lock-manager:acquire_lock` on the newly discovered dependent symbol.
   - Execute second-pass reconciliation before any code change is finalized.

### Step 6: Independent Verification Gate
1. Invoke the `verification-auditor` subagent (must not have participated in implementation).
2. Run cross-language compilation, static analysis (`golangci-lint`, `eslint`, `mypy`/`ruff`), and integration test suites.
3. Verify zero regressions in contract definitions.
4. **On success:**
   - Call `lock-manager:release_lock` for every symbol held by the verified subagent.
   - Call `go-runtime-cli:manage_worktree(action="merge", branch_name="agent-cluster-<id>")`.
   - Call `go-runtime-cli:manage_worktree(action="cleanup", branch_name="agent-cluster-<id>")`.

### Step 7: Artifact Generation
1. Compile the `bob-polyglot` CLI tool in Go.
2. Generate `ONBOARDING.md` using the template in `templates/ONBOARDING_TEMPLATE.md`, containing:
   - Full architecture maps (Mermaid diagrams)
   - Cluster tables with coupling metrics
   - Delicate code registries with risk scores
   - Discovered dynamic dependencies (Pass 2 findings)
   - Actionable modernization playbooks

## Verification Checklist
- [ ] All entry points (`main`, routes, CLI commands) have been discovered
- [ ] Function clusters are correctly categorized (A/B/C)
- [ ] Every Cluster B and C function has been processed in an isolated worktree
- [ ] All symbol locks have been acquired before modification and released after verification
- [ ] No deadlock cycles occurred (or were resolved by merging)
- [ ] Pass 1 static heuristics completed for all Cluster C nodes
- [ ] Pass 2 runtime traces captured and reconciled
- [ ] All worktrees merged and cleaned up
- [ ] `ONBOARDING.md` generated with all sections populated
- [ ] `bob-polyglot` CLI compiles and responds to `inspect`, `locks`, `simulate`, `trace`
