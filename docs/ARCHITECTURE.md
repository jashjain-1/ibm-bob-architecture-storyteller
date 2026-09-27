# System Architecture

## High-Level Component Topology

```mermaid
graph TD
    subgraph "IBM Bob 2.0 Agentic Runtime"
        Orchestrator["Master Orchestrator Agent"]
        LockMgr["Lock Manager MCP Server"]
        SubagentGo["Subagent A<br/>(Go / Delicate Code)"]
        SubagentTS["Subagent B<br/>(TypeScript / Node)"]
        SubagentPy["Subagent C<br/>(Python / Integration)"]
        Verifier["Verification &<br/>Categorization Subagent"]
    end

    subgraph "Hybrid MCP Tool Suite"
        GoTool["Go Engine: go-runtime-cli<br/>Clustering · Worktrees · Traces"]
        PyTool["Python Engine: py-ast-core<br/>AST Parser · Call Graph · Dynamic Detect"]
        TSTool["TypeScript Engine: ts-env-worker<br/>Type Checker · Module Resolver"]
    end

    subgraph "Execution Isolation Layer"
        WT1["Git Worktree A<br/>(Branch: cluster-go)"]
        WT2["Git Worktree B<br/>(Branch: cluster-ts)"]
        WT3["Git Worktree C<br/>(Branch: cluster-py)"]
        Pass2["2-Pass Dynamic Discovery<br/>(Static AST + Runtime Traces)"]
    end

    subgraph "Final Deliverables"
        CLI["Interactive Go CLI<br/>(bob-polyglot)"]
        Doc["Onboarding Dossier<br/>(ONBOARDING.md)"]
    end

    Orchestrator --> LockMgr
    Orchestrator --> GoTool
    Orchestrator --> PyTool
    Orchestrator --> TSTool

    Orchestrator -- "Spawns Parallel" --> SubagentGo
    Orchestrator -- "Spawns Parallel" --> SubagentTS
    Orchestrator -- "Spawns Parallel" --> SubagentPy

    SubagentGo --> WT1
    SubagentTS --> WT2
    SubagentPy --> WT3

    SubagentGo -.-> LockMgr
    SubagentTS -.-> LockMgr
    SubagentPy -.-> LockMgr

    WT1 --> Pass2
    WT2 --> Pass2
    WT3 --> Pass2
    Pass2 --> Verifier
    Verifier --> CLI
    Verifier --> Doc
```

---

## Hybrid Engine Division of Labor

```mermaid
graph LR
    subgraph "Language Routing"
        Input["Source File"]
        Input -->|".go"| GoEngine["Go Engine<br/>(go-runtime-cli)"]
        Input -->|".py"| PyEngine["Python Engine<br/>(py-ast-core)"]
        Input -->|".ts / .js / .tsx"| TSEngine["TS Engine<br/>(ts-env-worker)"]
    end

    subgraph "Go Engine Responsibilities"
        GoEngine --> G1["Tarjan SCC Clustering"]
        GoEngine --> G2["Git Worktree Management"]
        GoEngine --> G3["Runtime Trace Capture"]
        GoEngine --> G4["CLI Binary Compilation"]
    end

    subgraph "Python Engine Responsibilities"
        PyEngine --> P1["Tree-Sitter AST Extraction"]
        PyEngine --> P2["Call Graph Construction"]
        PyEngine --> P3["Dynamic Pattern Detection"]
        PyEngine --> P4["Cross-Language Glue"]
    end

    subgraph "TS Engine Responsibilities"
        TSEngine --> T1["Type Contract Validation"]
        TSEngine --> T2["Dynamic Module Resolution"]
        TSEngine --> T3["tsconfig Path Alias Mapping"]
    end
```

---

## Data Flow Through the 5-Phase Pipeline

```mermaid
graph TD
    R["Repository Root"] --> P1["Phase 1:<br/>AST Extraction & Clustering"]
    P1 -->|"AST Graph JSON"| P2["Phase 2:<br/>Worktree Isolation & Lock Acquisition"]
    P2 -->|"Isolated Branches"| P3["Phase 3:<br/>2-Pass Dependency Discovery"]
    P3 -->|"DiscoveredDependencies.json"| P4["Phase 4:<br/>Verification & Categorization Gate"]
    P4 -->|"Verified & Merged"| P5["Phase 5:<br/>Deliverable Generation"]
    P5 --> CLI["bob-polyglot CLI"]
    P5 --> DOC["ONBOARDING.md"]
```

---

## Cluster Classification

| Cluster | Name | Description | Worktree Required | Lock Required |
| :---: | :--- | :--- | :---: | :---: |
| **A** | Independent Leaves | Zero outbound internal dependencies. Isolated utilities. | No | No |
| **B** | Interdependent | Mutually calling, shared state/schemas, circular references. | Yes | Yes |
| **C** | Delicate / Dynamic | Reflection, dynamic dispatch, eval, runtime DI, env routing. | Yes | Yes (elevated) |
