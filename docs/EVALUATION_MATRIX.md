# Hackathon Evaluation Matrix & Pitch Script

## IBM Bob Hackathon: "Building with IBM Bob" (Sep 28 – Oct 18, 2026)

### Project Name
**Polyglot Navigator & Safe Refactor Engine**

### One-Line Pitch
> An agentic pipeline that transforms IBM Bob 2.0 into a polyglot code archaeologist — it maps entire undocumented repositories, clusters interdependent functions with mathematical precision, and executes parallel safe refactoring across Go, TypeScript, and Python with zero hidden breakage.

---

## Evaluation Matrix

| Judging Criteria | How This Solution Addresses It | Evidence |
| :--- | :--- | :--- |
| **Agent Mode & Subagents** | Not a single-prompt wrapper. Uses a hierarchical Orchestrator that spawns language-specialized subagents assigned to mathematically clustered function groups (Tarjan's SCC algorithm). | `MASTER_PROMPT.md` Phase 2 |
| **Parallel Tasks** | Subagents run concurrently in physically isolated git worktrees. A dedicated `lock-manager` MCP server prevents symbol-level collisions with deadlock cycle detection. | `docs/LOCK_PROTOCOL.md` |
| **Whole-Repository Understanding** | Parses complete codebase ASTs across Go, Python, and TypeScript. Builds call-graph hierarchies. Clusters entry points, interdependent cycles, and delicate dynamic code. | `tools/py-ast-core/`, `tools/go-runtime-cli/` |
| **Deterministic Reliability** | 2-pass dynamic dependency discovery (static heuristics + runtime test traces). Independent verification-auditor subagent validates before any merge. | `docs/PIPELINE.md` |
| **Real-World Value** | Slashes polyglot developer onboarding from weeks to minutes. Delivers both an interactive CLI and a rich markdown dossier. | `templates/ONBOARDING_TEMPLATE.md` |

---

## Demo Script (5-Minute Walkthrough)

### Minute 0–1: The Problem
> "Imagine joining a team with a 200k-line polyglot repo — Go microservices, a TypeScript frontend, Python ML pipelines. No docs. No architecture diagram. Where do you even start?"

### Minute 1–2: The Solution
> "We built the Polyglot Navigator — an IBM Bob 2.0 skill that uses three language-specialized MCP tool servers and a lock manager to map the entire repo, cluster functions, and spawn parallel subagents."

**Show:** Run the skill in Bob → Watch AST extraction begin → Show cluster output.

### Minute 2–3: Safe Parallel Refactoring
> "Each cluster gets its own git worktree and subagent. The lock manager prevents two agents from touching the same function. If a deadlock is detected, agents are automatically merged."

**Show:** Lock manager granting/denying locks in real-time → Worktree isolation.

### Minute 3–4: Hidden Dependency Discovery
> "Static analysis misses dynamic dispatch — reflection, event buses, env-conditional routing. Our 2-pass pipeline catches these by running tests and tracing runtime calls."

**Show:** Pass 1 flags a reflection pattern → Pass 2 discovers a hidden event listener → System re-locks and re-analyzes.

### Minute 4–5: The Deliverables
> "The developer gets two things: a `bob-polyglot` CLI to query symbols and simulate refactors, and a comprehensive `ONBOARDING.md` with architecture maps, risk warnings, and a modernization playbook."

**Show:** CLI `inspect` command → Generated ONBOARDING.md with Mermaid diagrams.

---

## Key Differentiators vs. Other Submissions

| Dimension | Typical Submission | Our Solution |
| :--- | :--- | :--- |
| **Scope** | Single file or single language | Entire polyglot repository |
| **Agent Usage** | One agent, one prompt | Orchestrator + N specialized subagents |
| **Parallelism** | Sequential execution | Concurrent git worktrees with lock arbitration |
| **Safety** | Hope-based ("it looks right") | 2-pass verification + independent auditor |
| **Output** | Chat response | Interactive CLI + persistent dossier |
| **Dynamic Code** | Ignored | Explicitly detected and traced |
