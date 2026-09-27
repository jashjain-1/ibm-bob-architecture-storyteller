/**
 * types.ts
 * --------
 * Payload types shared by the engine client, the panels and the webview UI.
 *
 * These mirror `architecture-model@2` (see tools/storyteller-engine/
 * model_builder.py). Nothing here invents data: if a field is missing the UI
 * omits it rather than guessing.
 */

export type DepthLevel = 1 | 2 | 3;

export interface RepoFingerprint {
    head?: string;
    branch?: string;
    dirty?: boolean;
    hash?: string;
}

export interface RepoInfo {
    root: string;
    name: string;
    fingerprint?: RepoFingerprint;
}

export interface ModelStats {
    files: number;
    production_files: number;
    symbols: number;
    functions: number;
    methods: number;
    classes: number;
    production_functions: number;
    test_functions: number;
    resolved_call_edges: number;
    unresolved_call_names: number;
    entry_points: number;
    modules: number;
    routes: number;
    models: number;
    services: number;
    languages: string[];
    files_with_history?: number;
    clusters?: Record<string, number>;
}

export interface FileEntry {
    path: string;
    language: string;
    module: string;
    loc: number;
    is_test: boolean;
    is_production: boolean;
    symbols: number;
    git?: { last_commit?: string; last_date?: string; last_subject?: string; commits?: number };
}

export interface TreeSymbol {
    id: string;
    name: string;
    qualified: string;
    kind: string;
    file: string;
    line: number;
    end: number;
    parent?: string | null;
    children: string[];
    complexity: number;
    flags: string[];
    calls: string[];
    callers: string[];
    doc: string;
    is_test: boolean;
    private: boolean;
    exported: boolean;
    language: string;
    hash: string;
}

export interface EntryPoint {
    symbol_id: string;
    type: string;
    kind: string;
    file_path: string;
    line: number;
    name: string;
    resolved: boolean;
    language: string;
}

export interface PivotalEntry {
    id: string;
    score: number;
    fan_in: number;
    fan_out: number;
    cross_file_callers: number;
    complexity: number;
}

export interface FlowNode {
    id: string;
    name: string;
    qualified: string;
    file: string;
    line: number;
    language: string;
}

export interface FlowEntry {
    entry: string;
    entry_id: string;
    kind: string;
    file: string;
    chain: FlowNode[];
}

export interface ModuleNode {
    id: string;
    label: string;
    symbols: number;
    files: number;
    languages: string[];
    has_cycle: boolean;
    dynamic: number;
}

export interface ModuleEdge {
    from: string;
    to: string;
    type: string;
    weight: number;
}

export interface TreePayload {
    schema: string;
    generated_at: string;
    repo: RepoInfo;
    meta: { engine: string; files_scanned: number; languages: string[]; duration_ms: number; detect_layers: boolean };
    stats: ModelStats;
    files: FileEntry[];
    symbols: TreeSymbol[];
    entry_points: EntryPoint[];
    clusters: { independent: string[]; cyclic: string[]; dynamic: string[]; sccs: string[][]; counts: Record<string, number> };
    pivotal: PivotalEntry[];
    flows: FlowEntry[];
    module_graph: { nodes: ModuleNode[]; edges: ModuleEdge[] };
}

export interface InsightEntry {
    micro?: string;
    why?: string;
    source?: string;
    model?: string;
    generated_at?: string;
}

export interface SymbolBrief {
    id: string;
    name: string;
    qualified: string;
    kind: string;
    file: string;
    line: number;
    end?: number;
}

export interface SymbolContext {
    schema: string;
    repo: string;
    symbol: SymbolBrief & {
        complexity: number;
        flags: string[];
        doc: string;
        language: string;
        source_kind: string;
        is_test: boolean;
        private: boolean;
        exported: boolean;
    };
    parent: SymbolBrief | null;
    callers: SymbolBrief[];
    calls: SymbolBrief[];
    children: SymbolBrief[];
    insight: InsightEntry;
    flows: { entry: string; kind: string; chain: string[] }[];
    source: string;
}

export interface UsagesPayload {
    symbol: SymbolBrief;
    call_site_count: number;
    callers: (SymbolBrief & { raw_calls: string[] })[];
}

export interface IndexReport {
    at: string;
    delta: { added: number; changed: number; removed: number; unchanged: number };
    fingerprint_changed: boolean;
    first_run: boolean;
    generated: number;
    removed: number;
    provider: string;
    providers_available: string[];
    sources: Record<string, number>;
    cached_total: number;
    stats: ModelStats;
}

export interface HealthPayload {
    ok: boolean;
    repo: string;
    root: string;
    schema: string;
    build_seconds: number;
    stats: ModelStats;
    cache: { insights: number; sources: Record<string, number>; last_index: string };
    last_index?: Partial<IndexReport>;
    levels: Record<string, string>;
}

export interface DossierResult {
    level: DepthLevel;
    pdf: string;
    html: string;
    bytes: number;
}

export interface StorytellerSettings {
    pythonPath: string;
    enginePath: string;
    enableHover: boolean;
    defaultLevel: DepthLevel;
    bobCommand: string;
    llmUrl: string;
    llmModel: string;
}

export const LEVEL_LABELS: Record<DepthLevel, string> = {
    1: 'Executive',
    2: 'Engineering',
    3: 'Forensic',
};

export const LEVEL_HINTS: Record<DepthLevel, string> = {
    1: 'Orientation: modules, entry points, risks, top routines.',
    2: 'Architecture: flows, routes, models, module graph, ranked routines.',
    3: 'Evidence: per-symbol call sites, history, cycles, full appendix.',
};
