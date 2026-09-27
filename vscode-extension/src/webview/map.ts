/**
 * map.ts
 * ------
 * Webview UI for the architecture map.
 *
 * Tree first: module -> folder -> file -> symbol, collapsible, with a detail
 * pane fed straight from the engine over localhost HTTP (falling back to a
 * message round-trip through the extension host when direct fetch is blocked).
 *
 * The depth level changes how much the tree shows:
 *   L1  modules and files (orientation)
 *   L2  adds symbols: functions, methods, classes
 *   L3  adds counts, flags and call neighbourhoods in the detail pane
 *
 * The dependency graph is an optional overlay, not the primary view.
 *
 * Only type-only imports are used, so the compiled file has no runtime imports
 * and can be loaded as a plain webview script.
 */

import type {
    DepthLevel,
    ModuleEdge,
    ModuleNode,
    SymbolBrief,
    SymbolContext,
    TreePayload,
    TreeSymbol,
} from '../engine/types';

interface Bootstrap {
    payload: TreePayload;
    apiBase: string;
    level: DepthLevel;
    workspaceRoot: string;
    engine: 'configured' | 'workspace';
}

interface HostApi {
    postMessage(message: unknown): void;
    getState(): unknown;
    setState(state: unknown): void;
}

interface TreeNode {
    kind: 'module' | 'folder' | 'file' | 'symbol';
    id: string;
    label: string;
    detail?: string;
    symbol?: TreeSymbol;
    count?: number;
    children: TreeNode[];
}

type GraphSpec =
    | { kind: 'modules'; nodes: ModuleNode[]; edges: ModuleEdge[] }
    | { kind: 'neighbourhood'; context: SymbolContext };

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------

const bootstrap = (window as unknown as { __STORYTELLER__?: Bootstrap }).__STORYTELLER__;
const host = (window as unknown as { acquireVsCodeApi?: () => HostApi }).acquireVsCodeApi?.();

const state = {
    payload: bootstrap?.payload,
    level: (bootstrap?.level ?? 2) as DepthLevel,
    query: '',
    expanded: new Set<string>(),
    selected: '' as string,
    context: undefined as SymbolContext | undefined,
    contextError: '',
    graph: undefined as GraphSpec | undefined,
};

// The panel sends the real engine URL with the first payload, so this starts
// empty and is filled in by the host: direct fetches keep the detail pane fast.
let apiBase = bootstrap?.apiBase ?? '';
let busy = false;

// ---------------------------------------------------------------------------
// DOM helpers
// ---------------------------------------------------------------------------

function el<K extends keyof HTMLElementTagNameMap>(
    tag: K,
    className?: string,
    text?: string
): HTMLElementTagNameMap[K] {
    const node = document.createElement(tag);
    if (className) {
        node.className = className;
    }
    if (text !== undefined) {
        node.textContent = text;
    }
    return node;
}

function clear(node: HTMLElement): void {
    while (node.firstChild) {
        node.removeChild(node.firstChild);
    }
}

function post(message: unknown): void {
    host?.postMessage(message);
}

function byId<T extends HTMLElement>(id: string): T {
    return document.getElementById(id) as T;
}

// ---------------------------------------------------------------------------
// Tree construction
// ---------------------------------------------------------------------------

const SYMBOL_KINDS = new Set(['function', 'method', 'class', 'interface', 'type', 'struct']);

function symbolsByFile(payload: TreePayload): Map<string, TreeSymbol[]> {
    const map = new Map<string, TreeSymbol[]>();
    for (const symbol of payload.symbols) {
        if (!SYMBOL_KINDS.has(symbol.kind)) {
            continue;
        }
        const list = map.get(symbol.file);
        if (list) {
            list.push(symbol);
        } else {
            map.set(symbol.file, [symbol]);
        }
    }
    return map;
}

function pivotalRank(payload: TreePayload): Map<string, number> {
    const rank = new Map<string, number>();
    payload.pivotal.forEach((entry, index) => rank.set(entry.id, index));
    return rank;
}

function buildTree(payload: TreePayload, level: DepthLevel, query: string): TreeNode[] {
    const byFile = symbolsByFile(payload);
    const rank = pivotalRank(payload);
    const needle = query.trim().toLowerCase();

    const modules = new Map<string, TreeNode>();
    for (const file of payload.files) {
        const moduleId = file.module || 'root';
        let moduleNode = modules.get(moduleId);
        if (!moduleNode) {
            moduleNode = { kind: 'module', id: `module:${moduleId}`, label: moduleId, count: 0, children: [] };
            modules.set(moduleId, moduleNode);
        }
        moduleNode.count = (moduleNode.count ?? 0) + file.symbols;

        // A file inside module `tools/engine` must not repeat that path as a
        // nested folder: folders are the segments between module and file.
        const modulePrefix = moduleId === 'root' ? '' : `${moduleId}/`;
        const relative = file.path.startsWith(modulePrefix)
            ? file.path.slice(modulePrefix.length)
            : file.path;
        const folders = relative.split('/');
        folders.pop();
        let parent = moduleNode;
        let prefix = '';
        for (const segment of folders) {
            prefix = prefix ? `${prefix}/${segment}` : segment;
            const folderId = `folder:${prefix}`;
            let folderNode = parent.children.find((child) => child.id === folderId);
            if (!folderNode) {
                folderNode = { kind: 'folder', id: folderId, label: segment, children: [] };
                parent.children.push(folderNode);
            }
            parent = folderNode;
        }

        const fileSymbols = (byFile.get(file.path) ?? [])
            .filter((symbol) => level === 3 || (!symbol.is_test && !symbol.private))
            .sort((a, b) => (rank.get(a.id) ?? 1e6) - (rank.get(b.id) ?? 1e6) || a.line - b.line);

        const fileNode: TreeNode = {
            kind: 'file',
            id: `file:${file.path}`,
            label: file.path.split('/').pop() ?? file.path,
            detail: file.path,
            count: file.symbols,
            children: [],
        };
        if (level >= 2) {
            fileNode.children = fileSymbols.map((symbol) => ({
                kind: 'symbol' as const,
                id: symbol.id,
                label: symbol.name,
                detail: `${symbol.kind}${symbol.is_test ? ' test' : ''}`,
                symbol,
                children: [],
            }));
        }
        parent.children.push(fileNode);
    }

    const collapse = (node: TreeNode): TreeNode | undefined => {
        if (needle) {
            const haystack = `${node.label} ${node.detail ?? ''}`.toLowerCase();
            const selfHit = haystack.includes(needle);
            const kids = node.children.map(collapse).filter((child): child is TreeNode => Boolean(child));
            if (!selfHit && kids.length === 0) {
                return undefined;
            }
            const copy: TreeNode = { ...node, children: kids };
            if (selfHit && kids.length === 0) {
                copy.children = node.children;
            }
            return copy;
        }
        return node;
    };

    const filtered = Array.from(modules.values())
        .map(collapse)
        .filter((node): node is TreeNode => Boolean(node));

    const sortNode = (node: TreeNode): void => {
        node.children.sort((a, b) => {
            if (a.kind !== b.kind) {
                const order = { module: 0, folder: 1, file: 2, symbol: 3 } as Record<string, number>;
                return order[a.kind] - order[b.kind];
            }
            if (node.kind === 'module') {
                return (b.count ?? 0) - (a.count ?? 0) || a.label.localeCompare(b.label);
            }
            if (a.kind === 'symbol') {
                const left = (a.symbol && rank.get(a.symbol.id)) ?? 1e6;
                const right = (b.symbol && rank.get(b.symbol.id)) ?? 1e6;
                return left - right || a.label.localeCompare(b.label);
            }
            return a.label.localeCompare(b.label);
        });
        node.children.forEach(sortNode);
    };
    const root: TreeNode = { kind: 'folder', id: 'departments', label: '', children: filtered };
    sortNode(root);
    return root.children;
}

// ---------------------------------------------------------------------------
// Tree rendering
// ---------------------------------------------------------------------------

function renderTree(): void {
    const pane = byId<HTMLElement>('tree-pane');
    clear(pane);
    if (!state.payload) {
        pane.appendChild(el('div', 'empty', 'Waiting for the engine to index this workspace.'));
        return;
    }
    const tree = buildTree(state.payload, state.level, state.query);
    if (tree.length === 0) {
        pane.appendChild(el('div', 'empty', state.query ? `No match for "${state.query}".` : 'No source files found.'));
        return;
    }
    // Open the biggest module on first paint so the tree is never a blank list.
    if (state.expanded.size === 0 && !state.query) {
        state.expanded.add(tree[0].id);
    }
    for (const node of tree) {
        renderNode(pane, node, 0);
    }
}

function renderNode(parent: HTMLElement, node: TreeNode, depth: number): void {
    const row = el('div', 'row');
    row.style.paddingLeft = `${8 + depth * 12}px`;
    row.dataset.id = node.id;

    const hasChildren = node.children.length > 0;
    const expanded = state.expanded.has(node.id) || (Boolean(state.query) && hasChildren);
    const chevron = el('span', 'chev', hasChildren ? (expanded ? 'v' : '>') : '');
    row.appendChild(chevron);

    if (node.kind === 'symbol' && node.symbol) {
        row.appendChild(el('span', 'rank', String(node.symbol.line)));
        row.appendChild(el('span', 'label subject', node.label));
        row.appendChild(el('span', 'kind', node.symbol.kind));
        if (node.symbol.is_test) {
            row.appendChild(el('span', 'tag warn', 'test'));
        }
        if (state.level === 3) {
            if (node.symbol.callers.length > 0) {
                row.appendChild(el('span', 'count', `${node.symbol.callers.length} callers`));
            }
            for (const flag of node.symbol.flags.slice(0, 2)) {
                row.appendChild(el('span', `tag ${flag.startsWith('dynamic:') ? 'danger' : 'warn'}`, flag));
            }
        }
        row.classList.add('clickable');
        if (state.selected === node.id) {
            row.classList.add('selected');
        }
        row.addEventListener('click', () => void selectSymbol(node.id, node.label));
        parent.appendChild(row);
        return;
    }

    const label = node.kind === 'file' ? el('span', 'label subject', node.label) : el('span', 'label', node.label);
    row.appendChild(label);
    if (node.kind === 'file' && node.detail) {
        row.appendChild(el('span', 'path', node.detail));
    }
    if (node.count !== undefined) {
        row.appendChild(el('span', 'count', `${node.count} symbols`));
    }
    if (hasChildren) {
        row.classList.add('clickable');
        row.addEventListener('click', (event) => {
            event.stopPropagation();
            if (state.expanded.has(node.id)) {
                state.expanded.delete(node.id);
            } else {
                state.expanded.add(node.id);
            }
            renderTree();
        });
    }
    parent.appendChild(row);

    if (hasChildren && expanded) {
        for (const child of node.children) {
            renderNode(parent, child, depth + 1);
        }
    }
}

// ---------------------------------------------------------------------------
// Detail pane
// ---------------------------------------------------------------------------

async function selectSymbol(symbolId: string, label: string): Promise<void> {
    state.selected = symbolId;
    state.context = undefined;
    state.contextError = '';
    renderTree();
    renderDetail();
    try {
        const context = await requestContext(symbolId);
        if (state.selected === symbolId) {
            state.context = context;
            renderDetail();
        }
    } catch (error) {
        if (state.selected === symbolId) {
            state.contextError = String((error as Error).message ?? error);
            renderDetail();
        }
    }
}

function requestContext(symbolId: string): Promise<SymbolContext> {
    const url = `${apiBase}/context?symbol=${encodeURIComponent(symbolId)}&lines=60`;
    return fetch(url)
        .then((response) => {
            if (!response.ok) {
                throw new Error(`engine responded ${response.status}`);
            }
            return response.json() as Promise<SymbolContext>;
        })
        .catch(() => new Promise<SymbolContext>((resolve, reject) => {
            // Direct fetch can be blocked by CSP: ask the extension host instead.
            const timer = window.setTimeout(() => {
                window.removeEventListener('message', listener);
                reject(new Error('engine request timed out'));
            }, 15000);
            const listener = (event: MessageEvent): void => {
                const data = event.data as { type?: string; symbolId?: string; context?: SymbolContext; error?: string };
                if (data?.type !== 'context' || data.symbolId !== symbolId) {
                    return;
                }
                window.clearTimeout(timer);
                window.removeEventListener('message', listener);
                if (data.context) {
                    resolve(data.context);
                } else {
                    reject(new Error(data.error ?? 'engine unavailable'));
                }
            };
            window.addEventListener('message', listener);
            post({ command: 'context', symbol: symbolId });
        }));
}

function briefLine(brief: SymbolBrief, extra?: string): HTMLLIElement {
    const item = el('li', 'clickable');
    item.appendChild(el('span', 'subject', brief.qualified || brief.name));
    item.appendChild(document.createTextNode(`  ${brief.file}:${brief.line}`));
    if (extra) {
        item.appendChild(el('span', 'muted', `  ${extra}`));
    }
    item.addEventListener('click', () => post({ command: 'openFile', file: brief.file, line: brief.line }));
    return item;
}

function renderDetail(): void {
    const pane = byId<HTMLElement>('detail-pane');
    clear(pane);

    if (!state.selected) {
        const hint = el('div', 'empty');
        hint.appendChild(el('div', undefined, 'Select a symbol to see its call sites, insight and source.'));
        hint.appendChild(el('div', 'muted',
            `${state.payload?.stats.symbols ?? 0} symbols, ${state.payload?.stats.resolved_call_edges ?? 0} resolved call edges.`));
        pane.appendChild(hint);
        return;
    }
    if (state.contextError) {
        pane.appendChild(el('div', 'empty', `Could not load context: ${state.contextError}`));
        return;
    }
    if (!state.context) {
        pane.appendChild(el('div', 'empty', 'Loading context...'));
        return;
    }

    const context = state.context;
    const symbol = context.symbol;

    const head = el('div', 'detail-head');
    head.appendChild(el('h2', undefined, symbol.qualified));
    const where = el('span', 'where', `${symbol.file}:${symbol.line}-${symbol.end ?? symbol.line}`);
    where.addEventListener('click', () => post({ command: 'openFile', file: symbol.file, line: symbol.line }));
    head.appendChild(where);
    pane.appendChild(head);

    const metrics = el('div', 'metrics');
    const addMetric = (label: string, value: string): void => {
        const item = el('span');
        item.appendChild(el('b', undefined, value));
        item.appendChild(document.createTextNode(` ${label}`));
        metrics.appendChild(item);
    };
    addMetric('complexity', String(symbol.complexity));
    addMetric('callers', String(context.callers.length));
    addMetric('resolved calls', String(context.calls.length));
    addMetric('kind', symbol.kind);
    addMetric('language', symbol.language || 'unknown');
    if (symbol.is_test) {
        addMetric('layer', 'test');
    } else {
        addMetric('layer', 'production');
    }
    pane.appendChild(metrics);

    if (symbol.flags.length > 0) {
        const flags = el('div', 'metrics');
        for (const flag of symbol.flags) {
            flags.appendChild(el('span', `tag ${flag.startsWith('dynamic:') ? 'danger' : 'warn'}`, flag));
        }
        pane.appendChild(flags);
    }

    if (context.insight.micro || context.insight.why) {
        const callout = el('div', 'callout');
        if (context.insight.micro) {
            callout.appendChild(el('div', 'subject', context.insight.micro));
        }
        if (context.insight.why) {
            callout.appendChild(el('div', undefined, context.insight.why));
        }
        const source = context.insight.source ?? 'auto';
        const label = source === 'bob'
            ? `IBM Bob${context.insight.model ? ` (${context.insight.model})` : ''}`
            : source === 'llm'
                ? `local LLM${context.insight.model ? ` (${context.insight.model})` : ''}`
                : 'deterministic fallback';
        callout.appendChild(el('span', 'src', `Summary source: ${label}`));
        pane.appendChild(callout);
    } else if (symbol.doc) {
        const callout = el('div', 'callout');
        callout.appendChild(el('div', symbol.doc.split('\n')[0].trim()));
        callout.appendChild(el('span', 'src', 'Summary source: docstring'));
        pane.appendChild(callout);
    }

    const actions = el('div', 'metrics');
    const usagesButton = el('button', 'action', 'Show all call sites');
    usagesButton.addEventListener('click', () => post({ command: 'usages', symbol: symbol.id }));
    const dossierButton = el('button', 'action', `Dossier (L${state.level})`);
    dossierButton.addEventListener('click', () => post({ command: 'dossier', level: state.level }));
    actions.appendChild(usagesButton);
    actions.appendChild(dossierButton);
    pane.appendChild(actions);

    if (context.callers.length > 0) {
        pane.appendChild(el('h4', undefined, `Called from (${context.callers.length})`));
        const list = el('ul', 'links');
        for (const caller of context.callers.slice(0, 25)) {
            list.appendChild(briefLine(caller));
        }
        pane.appendChild(list);
    }
    if (context.calls.length > 0) {
        pane.appendChild(el('h4', undefined, `Calls (${context.calls.length})`));
        const list = el('ul', 'links');
        for (const callee of context.calls.slice(0, 25)) {
            list.appendChild(briefLine(callee));
        }
        pane.appendChild(list);
    }
    if (context.children.length > 0) {
        pane.appendChild(el('h4', undefined, `Members (${context.children.length})`));
        const list = el('ul', 'links');
        for (const child of context.children.slice(0, 25)) {
            list.appendChild(briefLine(child, child.kind));
        }
        pane.appendChild(list);
    }
    if (context.flows.length > 0) {
        pane.appendChild(el('h4', undefined, 'Appears in flows'));
        const list = el('ul', 'links');
        for (const flow of context.flows) {
            const item = el('li', 'subject', flow.chain.join(' -> '));
            list.appendChild(item);
        }
        pane.appendChild(list);
    }
    if (context.source) {
        pane.appendChild(el('h4', undefined, 'Source'));
        pane.appendChild(el('pre', 'source', context.source));
    }
}

// ---------------------------------------------------------------------------
// Graph overlay
// ---------------------------------------------------------------------------

function layoutModules(nodes: ModuleNode[], edges: ModuleEdge[]): Map<string, { x: number; y: number }> {
    const width = 900;
    const height = 560;
    const positions = new Map<string, { x: number; y: number; vx: number; vy: number }>();
    const centre = { x: width / 2, y: height / 2 };
    nodes.forEach((node, index) => {
        const angle = (2 * Math.PI * index) / Math.max(nodes.length, 1);
        const radius = 180 + (index % 3) * 40;
        positions.set(node.id, {
            x: centre.x + radius * Math.cos(angle),
            y: centre.y + radius * Math.sin(angle),
            vx: 0,
            vy: 0,
        });
    });

    for (let step = 0; step < 160; step += 1) {
        for (let i = 0; i < nodes.length; i += 1) {
            const a = positions.get(nodes[i].id);
            if (!a) {
                continue;
            }
            for (let j = i + 1; j < nodes.length; j += 1) {
                const b = positions.get(nodes[j].id);
                if (!b) {
                    continue;
                }
                let dx = a.x - b.x;
                let dy = a.y - b.y;
                let distance = Math.sqrt(dx * dx + dy * dy) || 1;
                const force = 3600 / (distance * distance);
                dx = (dx / distance) * force;
                dy = (dy / distance) * force;
                a.vx += dx;
                a.vy += dy;
                b.vx -= dx;
                b.vy -= dy;
            }
        }
        for (const edge of edges) {
            const a = positions.get(edge.from);
            const b = positions.get(edge.to);
            if (!a || !b) {
                continue;
            }
            const dx = b.x - a.x;
            const dy = b.y - a.y;
            const distance = Math.sqrt(dx * dx + dy * dy) || 1;
            const desired = 150;
            const pull = (distance - desired) * 0.004;
            a.vx += (dx / distance) * pull * 10;
            a.vy += (dy / distance) * pull * 10;
            b.vx -= (dx / distance) * pull * 10;
            b.vy -= (dy / distance) * pull * 10;
        }
        for (const node of nodes) {
            const point = positions.get(node.id);
            if (!point) {
                continue;
            }
            point.vx += (centre.x - point.x) * 0.0025;
            point.vy += (centre.y - point.y) * 0.0025;
            point.x += point.vx * 0.85;
            point.y += point.vy * 0.85;
            point.vx *= 0.6;
            point.vy *= 0.6;
        }
    }

    const result = new Map<string, { x: number; y: number }>();
    for (const [id, point] of positions) {
        result.set(id, { x: point.x, y: point.y });
    }
    return result;
}

function svgElement(name: string): SVGElement {
    return document.createElementNS('http://www.w3.org/2000/svg', name);
}

function renderGraph(): void {
    const overlay = byId<HTMLElement>('graph-overlay');
    const canvas = byId<HTMLElement>('graph-canvas');
    clear(canvas);
    if (!state.graph) {
        overlay.hidden = true;
        return;
    }
    overlay.hidden = false;

    if (state.graph.kind === 'modules') {
        const { nodes, edges } = state.graph;
        byId<HTMLElement>('graph-title').textContent =
            `Module dependencies (${nodes.length} modules, ${edges.length} edges). Red ring: dependency cycle.`;
        const positions = layoutModules(nodes, edges);
        const svg = svgElement('svg');
        svg.setAttribute('viewBox', '0 0 900 560');
        const drawn = new Set<string>();
        for (const edge of edges) {
            const key = `${edge.from}->${edge.to}`;
            if (drawn.has(key)) {
                continue;
            }
            drawn.add(key);
            const a = positions.get(edge.from);
            const b = positions.get(edge.to);
            if (!a || !b) {
                continue;
            }
            const line = svgElement('line');
            line.setAttribute('class', 'edge');
            line.setAttribute('x1', String(a.x));
            line.setAttribute('y1', String(a.y));
            line.setAttribute('x2', String(b.x));
            line.setAttribute('y2', String(b.y));
            line.setAttribute('stroke-width', String(Math.min(3, 0.6 + edge.weight * 0.2)));
            svg.appendChild(line);
        }
        for (const node of nodes) {
            const point = positions.get(node.id);
            if (!point) {
                continue;
            }
            const radius = 8 + Math.min(16, Math.sqrt(node.symbols) * 1.6);
            const circle = svgElement('circle');
            circle.setAttribute('class', 'node');
            circle.setAttribute('cx', String(point.x));
            circle.setAttribute('cy', String(point.y));
            circle.setAttribute('r', String(radius));
            circle.setAttribute('fill', node.has_cycle ? 'var(--badge)' : 'var(--panel)');
            circle.setAttribute('stroke', node.has_cycle ? 'var(--danger)' : 'var(--accent)');
            circle.setAttribute('stroke-width', node.has_cycle ? '2' : '1');
            const title = svgElement('title');
            title.textContent =
                `${node.label}: ${node.symbols} symbols in ${node.files} file(s)` +
                (node.has_cycle ? ', participates in a dependency cycle' : '') +
                (node.dynamic ? `, ${node.dynamic} dynamic` : '');
            circle.appendChild(title);
            circle.addEventListener('click', () => {
                state.expanded.add(`module:${node.id}`);
                renderTree();
            });
            svg.appendChild(circle);

            const label = svgElement('text');
            label.setAttribute('class', 'node-label');
            label.setAttribute('x', String(point.x));
            label.setAttribute('y', String(point.y + radius + 11));
            label.setAttribute('text-anchor', 'middle');
            label.setAttribute('fill', 'var(--ink)');
            label.textContent = node.id.split('/').pop() ?? node.id;
            svg.appendChild(label);
        }
        canvas.appendChild(svg);
        return;
    }

    const context = state.graph.context;
    byId<HTMLElement>('graph-title').textContent =
        `Call neighbourhood of ${context.symbol.qualified} (${context.callers.length} caller(s), ${context.calls.length} call(s))`;
    const svg = svgElement('svg');
    svg.setAttribute('viewBox', '0 0 900 560');
    const centre = { x: 450, y: 280 };

    const place = (count: number, x: number): { x: number; y: number }[] => {
        const step = Math.min(52, 420 / Math.max(count, 1));
        return Array.from({ length: count }, (_, index) => ({ x, y: 90 + index * step }));
    };

    const callers = context.callers.slice(0, 14);
    const callees = context.calls.slice(0, 14);
    // Long qualified names are truncated so they cannot run off the canvas.
    const shorten = (text: string): string => (text.length > 30 ? `${text.slice(0, 29)}.` : text);
    const callerPoints = place(callers.length, 300);
    const calleePoints = place(callees.length, 620);

    callerPoints.forEach((point, index) => {
        const brief = callers[index];
        const line = svgElement('line');
        line.setAttribute('class', 'edge');
        line.setAttribute('x1', String(point.x));
        line.setAttribute('y1', String(point.y));
        line.setAttribute('x2', String(centre.x));
        line.setAttribute('y2', String(centre.y));
        svg.appendChild(line);

        const circle = svgElement('circle');
        circle.setAttribute('class', 'node');
        circle.setAttribute('cx', String(point.x));
        circle.setAttribute('cy', String(point.y));
        circle.setAttribute('r', '6');
        circle.setAttribute('fill', 'var(--panel)');
        circle.setAttribute('stroke', 'var(--accent)');
        circle.addEventListener('click', () => void selectSymbol(brief.id, brief.name));
        svg.appendChild(circle);

        const label = svgElement('text');
        label.setAttribute('class', 'node-label');
        label.setAttribute('x', String(point.x - 12));
        label.setAttribute('y', String(point.y + 3));
        label.setAttribute('text-anchor', 'end');
        label.setAttribute('fill', 'var(--ink)');
        label.textContent = shorten(brief.qualified);
        svg.appendChild(label);
    });

    calleePoints.forEach((point, index) => {
        const brief = callees[index];
        const line = svgElement('line');
        line.setAttribute('class', 'edge');
        line.setAttribute('x1', String(centre.x));
        line.setAttribute('y1', String(centre.y));
        line.setAttribute('x2', String(point.x));
        line.setAttribute('y2', String(point.y));
        svg.appendChild(line);

        const circle = svgElement('circle');
        circle.setAttribute('class', 'node');
        circle.setAttribute('cx', String(point.x));
        circle.setAttribute('cy', String(point.y));
        circle.setAttribute('r', '6');
        circle.setAttribute('fill', 'var(--panel)');
        circle.setAttribute('stroke', 'var(--accent)');
        circle.addEventListener('click', () => void selectSymbol(brief.id, brief.name));
        svg.appendChild(circle);

        const label = svgElement('text');
        label.setAttribute('class', 'node-label');
        label.setAttribute('x', String(point.x + 12));
        label.setAttribute('y', String(point.y + 3));
        label.setAttribute('fill', 'var(--ink)');
        label.textContent = shorten(brief.qualified);
        svg.appendChild(label);
    });

    const centreCircle = svgElement('circle');
    centreCircle.setAttribute('cx', String(centre.x));
    centreCircle.setAttribute('cy', String(centre.y));
    centreCircle.setAttribute('r', '12');
    centreCircle.setAttribute('fill', 'var(--badge)');
    centreCircle.setAttribute('stroke', 'var(--accent)');
    svg.appendChild(centreCircle);

    const centreLabel = svgElement('text');
    centreLabel.setAttribute('class', 'node-label');
    centreLabel.setAttribute('x', String(centre.x));
    centreLabel.setAttribute('y', String(centre.y + 28));
    centreLabel.setAttribute('text-anchor', 'middle');
    centreLabel.setAttribute('fill', 'var(--ink)');
    centreLabel.textContent = context.symbol.qualified;
    svg.appendChild(centreLabel);

    canvas.appendChild(svg);
}

// ---------------------------------------------------------------------------
// Toolbar + status
// ---------------------------------------------------------------------------

function renderToolbar(): void {
    const toolbar = byId<HTMLElement>('toolbar');
    clear(toolbar);
    const stats = state.payload?.stats;

    toolbar.appendChild(el('span', 'repo', state.payload?.repo.name ?? 'repository'));
    toolbar.appendChild(el('span', 'meta',
        stats
            ? `${stats.files} files, ${stats.symbols} symbols, ${stats.modules} modules` +
              `, ${stats.resolved_call_edges} call edges`
            : 'waiting for the engine'));

    toolbar.appendChild(el('span', 'spacer'));

    const search = el('input');
    search.type = 'search';
    search.placeholder = 'Filter by name or path';
    search.value = state.query;
    search.addEventListener('input', () => {
        state.query = search.value;
        renderTree();
    });
    toolbar.appendChild(search);

    const levels = el('div', 'levels');
    ([1, 2, 3] as DepthLevel[]).forEach((level) => {
        const button = el('button', undefined, `L${level}`);
        button.type = 'button';
        button.title = level === 1
            ? 'Modules and files'
            : level === 2
                ? 'Adds symbols'
                : 'Adds counts, flags and call neighbourhoods';
        button.setAttribute('aria-pressed', String(state.level === level));
        button.addEventListener('click', () => {
            state.level = level;
            if (state.query) {
                state.expanded.clear();
            }
            post({ command: 'level', level });
            renderToolbar();
            renderTree();
        });
        levels.appendChild(button);
    });
    toolbar.appendChild(levels);

    const graphButton = el('button', 'action', state.graph ? 'Hide graph' : 'Dependency graph');
    graphButton.type = 'button';
    graphButton.addEventListener('click', () => {
        if (state.graph) {
            state.graph = undefined;
        } else if (state.context) {
            state.graph = { kind: 'neighbourhood', context: state.context };
        } else if (state.payload) {
            state.graph = {
                kind: 'modules',
                nodes: state.payload.module_graph.nodes,
                edges: state.payload.module_graph.edges,
            };
        }
        renderToolbar();
        renderGraph();
    });
    toolbar.appendChild(graphButton);

    const refresh = el('button', 'action', busy ? 'Indexing...' : 'Re-index');
    refresh.type = 'button';
    refresh.disabled = busy;
    refresh.addEventListener('click', () => {
        busy = true;
        renderToolbar();
        post({ command: 'index' });
    });
    toolbar.appendChild(refresh);

    const dossier = el('button', 'action', `Dossier L${state.level}`);
    dossier.type = 'button';
    dossier.addEventListener('click', () => post({ command: 'dossier', level: state.level }));
    toolbar.appendChild(dossier);
}

function renderStatus(extra?: string): void {
    const status = byId<HTMLElement>('status');
    clear(status);
    const payload = state.payload;
    const stats = payload?.stats;
    if (payload) {
        status.appendChild(el('span', undefined,
            `engine ${payload.meta.engine} | model ${payload.schema} | generated ${payload.generated_at}`));
        status.appendChild(el('span', undefined,
            `clusters: ${stats?.clusters?.cyclic ?? 0} cyclic, ${stats?.clusters?.dynamic ?? 0} dynamic`));
        status.appendChild(el('span', undefined,
            `entry points ${stats?.entry_points ?? 0} | routes ${stats?.routes ?? 0} | models ${stats?.models ?? 0}`));
    }
    if (bootstrap) {
        status.appendChild(el('span', undefined, `engine source: ${bootstrap.engine}`));
    }
    if (extra) {
        status.appendChild(el('span', undefined, extra));
    }
}

function renderBanner(message?: string, isError = false): void {
    const banner = byId<HTMLElement>('banner');
    if (!message) {
        banner.hidden = true;
        banner.textContent = '';
        return;
    }
    banner.hidden = false;
    banner.className = `banner${isError ? ' error' : ''}`;
    banner.textContent = message;
}

// ---------------------------------------------------------------------------
// Host messages
// ---------------------------------------------------------------------------

window.addEventListener('message', (event: MessageEvent) => {
    const data = event.data as {
        type?: string;
        payload?: TreePayload;
        level?: DepthLevel;
        message?: string;
        isError?: boolean;
    };
    if (!data || !data.type) {
        return;
    }
    if (data.type === 'payload' && data.payload) {
        window.clearInterval(readyTimer);
        state.payload = data.payload;
        const incoming = data as { apiBase?: string };
        if (incoming.apiBase) {
            apiBase = incoming.apiBase;
        }
        state.expanded.clear();
        busy = false;
        renderBanner();
        renderToolbar();
        renderTree();
        renderDetail();
        renderStatus();
    } else if (data.type === 'level' && data.level) {
        state.level = data.level;
        renderToolbar();
        renderTree();
    } else if (data.type === 'status') {
        busy = Boolean(data.message && /index/i.test(data.message));
        renderToolbar();
        renderBanner(data.message, Boolean(data.isError));
    } else if (data.type === 'focus' && data.message) {
        state.selected = data.message;
        state.query = '';
        void selectSymbol(data.message, data.message);
    }
});

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------

byId<HTMLElement>('graph-close').addEventListener('click', () => {
    state.graph = undefined;
    renderToolbar();
    renderGraph();
});

renderToolbar();
renderTree();
renderDetail();
renderStatus();
renderGraph();
post({ command: 'ready' });

// One dropped message must not leave an empty panel behind: keep asking for a
// payload, and say so plainly if the host never answers.
let readyAttempts = 0;
const readyTimer = window.setInterval(() => {
    if (state.payload) {
        window.clearInterval(readyTimer);
        return;
    }
    readyAttempts += 1;
    if (readyAttempts > 5) {
        window.clearInterval(readyTimer);
        const pane = byId<HTMLElement>('tree-pane');
        clear(pane);
        pane.appendChild(el('div', 'empty',
            'No answer from the extension host. Run "Architecture Storyteller: Re-index Workspace", ' +
            'or reload the window.'));
        renderStatus('waiting for the host');
        return;
    }
    post({ command: 'ready' });
}, 1500);
