/**
 * extension.ts
 * ------------
 * Entry point for Architecture Storyteller.
 *
 * The extension is a thin client: it starts one engine process per session
 * (`cli.py serve`) and renders what the engine reports. All analysis, caching
 * and dossier building happens in Python, so the map, the hover text and the
 * PDF always describe the same model.
 *
 * Commands
 * --------
 *  storyteller.mindmap             open the tree-first architecture map
 *  storyteller.context             symbol context (callers, insight, source)
 *  storyteller.usages              every resolved call site of a symbol
 *  storyteller.inspectDependencies alias of usages, kept for existing keybindings
 *  storyteller.askBobAI            show the stored AI insight and provider status
 *  storyteller.configureScope      choose the default depth level
 *  storyteller.index               rebuild the model and refresh insights
 *  storyteller.pdf                 export a dossier PDF at the default level
 *  storyteller.exportDossier       preview a dossier, then export PDF or HTML
 *  storyteller.openLocation        internal target for webview file links
 */

import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';

import { EngineClient } from './engine/client';
import {
    enclosingEngineRoot,
    engineMissingMessage,
    engineMissingReason,
    findEngine,
    findPython,
} from './engine/locate';
import { DepthLevel, LEVEL_LABELS, TreePayload } from './engine/types';
import { describeReport, exportDossier, exportPdf, indexWorkspace, pickLevel, previewDossier } from './commands/dossier';
import { showContext, showUsages } from './views/contextPanel';
import { showDocumentPanel } from './views/documentPanel';
import { MapPanel, MapPanelDelegate } from './views/mapPanel';
import { registerArchitectureHoverProvider } from './views/hoverProvider';
import { escapeHtml } from './webview/shell';

let client: EngineClient | undefined;
let output: vscode.OutputChannel | undefined;
let statusItem: vscode.StatusBarItem | undefined;
let warming = false;

function workspaceRoots(): string[] {
    return (vscode.workspace.workspaceFolders ?? []).map((folder) => folder.uri.fsPath);
}

/**
 * Where the engine may be found: the open folders, plus the repository that
 * encloses the active file. The second part makes the extension usable in a
 * window with no folder open, and when the open folder is a project that simply
 * does not carry the engine (the usual demo setup).
 */
function discoveryRoots(): string[] {
    const roots = workspaceRoots();
    const activeFile = vscode.window.activeTextEditor?.document.uri.fsPath;
    if (activeFile) {
        const enclosing = enclosingEngineRoot(activeFile);
        if (enclosing && !roots.includes(enclosing)) {
            roots.push(enclosing);
        }
    }
    return roots;
}

/**
 * The repository the engine should analyse: the open folder when there is one,
 * otherwise the repository the engine was discovered in.
 */
function analyzedRepo(cliPath: string): string {
    return workspaceRoots()[0] ?? path.resolve(path.dirname(cliPath), '..', '..');
}

function settings() {
    const configuration = vscode.workspace.getConfiguration('storyteller');
    return {
        pythonPath: configuration.get<string>('pythonPath', ''),
        enginePath: configuration.get<string>('enginePath', ''),
        defaultLevel: configuration.get<DepthLevel>('defaultDepth', 2),
        bobCommand: configuration.get<string>('bobCommand', ''),
        llmUrl: configuration.get<string>('llmUrl', ''),
        llmModel: configuration.get<string>('llmModel', ''),
    };
}

let currentContext: vscode.ExtensionContext | undefined;

function engineOrigin(): 'configured' | 'workspace' {
    return findEngine(discoveryRoots(), settings().enginePath)?.origin ?? 'workspace';
}

function engineAvailable(): boolean {
    return findEngine(discoveryRoots(), settings().enginePath) !== undefined;
}

/**
 * Point the extension at an existing engine and restart against it.
 *
 * This is the escape hatch for a workspace that does not contain the engine at
 * all, which is otherwise a dead end: the map can still analyse that workspace
 * because the engine takes --repo from the open folder.
 */
async function chooseEngineDirectory(): Promise<void> {
    const picked = await vscode.window.showOpenDialog({
        canSelectFiles: false,
        canSelectFolders: true,
        canSelectMany: false,
        openLabel: 'Use as engine directory',
        title: 'Select the folder that contains the storyteller engine (cli.py)',
    });
    const directory = picked?.[0]?.fsPath;
    if (!directory) {
        return;
    }
    if (!fs.existsSync(path.join(directory, 'cli.py'))) {
        void vscode.window.showErrorMessage(
            `No cli.py in ${directory}. Pick the folder that contains cli.py (usually tools/storyteller-engine).`
        );
        return;
    }
    const target = workspaceRoots().length
        ? vscode.ConfigurationTarget.Workspace
        : vscode.ConfigurationTarget.Global;
    await vscode.workspace.getConfiguration('storyteller').update('enginePath', directory, target);
    client?.dispose();
    client = undefined;
    await refreshStatus();
    void vscode.window.showInformationMessage(
        `Engine directory set to ${directory}. Analysing ${analyzedRepo(path.join(directory, 'cli.py'))}.`
    );
    void warmUp();
}

/**
 * Run `action` with the engine client, reporting the missing-engine error once
 * instead of letting every command fail with its own stack trace.
 */
async function withClient<T>(action: (client: EngineClient) => Promise<T>): Promise<T | undefined> {
    const active = await requireClient();
    return active ? action(active) : undefined;
}

/**
 * Resolve the engine client, explaining exactly what is missing when the
 * workspace has no engine instead of failing silently.
 */
async function requireClient(): Promise<EngineClient | undefined> {
    try {
        return getClient();
    } catch (error) {
        const message = String((error as Error).message ?? error);
        output?.appendLine(`[extension] ${message}`);
        const choice = await vscode.window.showErrorMessage(
            'Architecture Storyteller: engine not found.',
            { detail: engineMissingReason(discoveryRoots(), settings().enginePath) },
            'Set Engine Directory...',
            'Open Repository...',
            'Show Output'
        );
        if (choice === 'Set Engine Directory...') {
            await chooseEngineDirectory();
        } else if (choice === 'Open Repository...') {
            await vscode.commands.executeCommand('workbench.action.files.openFolder');
        } else if (choice === 'Show Output') {
            output?.show();
        }
        return undefined;
    }
}

function getClient(): EngineClient {
    const context = currentContext;
    if (!context) {
        throw new Error('Storyteller extension is not active.');
    }
    if (client) {
        return client;
    }
    const configuration = settings();
    const location = findEngine(discoveryRoots(), configuration.enginePath);
    if (!location) {
        throw new Error(engineMissingMessage(discoveryRoots(), configuration.enginePath));
    }
    const python = findPython(discoveryRoots(), configuration.pythonPath);
    output?.appendLine(
        `[extension] engine=${location.cliPath} (${location.origin}) python=${python} repo=${analyzedRepo(location.cliPath)}`
    );
    client = new EngineClient(
        {
            python,
            cliPath: location.cliPath,
            repo: analyzedRepo(location.cliPath),
            bobCommand: configuration.bobCommand,
            llmUrl: configuration.llmUrl,
            llmModel: configuration.llmModel,
        },
        output ?? vscode.window.createOutputChannel('Architecture Storyteller')
    );
    return client;
}

/**
 * Lazily resolved client for long-lived consumers (map panel, hover).
 *
 * The module-level `client` is recycled whenever the engine restarts, so
 * consumers must not capture an instance: they call this each time and get the
 * current one (or undefined when the engine cannot be found).
 */
function clientProvider(): EngineClient | undefined {
    try {
        return getClient();
    } catch {
        return undefined;
    }
}

// ---------------------------------------------------------------------------
// Symbol argument resolution
// ---------------------------------------------------------------------------

async function quickPickSymbol(payload: TreePayload): Promise<string | undefined> {
    const symbols = new Map(payload.symbols.map((symbol) => [symbol.id, symbol]));
    const items: (vscode.QuickPickItem & { id: string })[] = payload.pivotal
        .slice(0, 40)
        .map((entry) => symbols.get(entry.id))
        .filter((symbol): symbol is NonNullable<typeof symbol> => Boolean(symbol))
        .map((symbol) => ({
            label: symbol.qualified,
            description: `${symbol.kind} - ${symbol.file}:${symbol.line}`,
            detail: `${symbol.callers.length} caller(s), complexity ${symbol.complexity}`,
            id: symbol.id,
        }));
    const choice = await vscode.window.showQuickPick(items, {
        title: 'Symbols ranked by dependency impact',
        placeHolder: 'Pick a routine to inspect',
    });
    return choice?.id;
}

async function resolveSymbol(argument?: unknown): Promise<string | undefined> {
    if (typeof argument === 'string' && argument.trim()) {
        return argument.trim();
    }
    const editor = vscode.window.activeTextEditor;
    if (editor) {
        const selection = editor.selection;
        const selected = selection.isEmpty
            ? editor.document.getWordRangeAtPosition(selection.active, /[A-Za-z_$][\w$]*/)
            : selection;
        if (selected) {
            const text = editor.document.getText(selected).trim();
            if (text && text.length >= 2) {
                return text;
            }
        }
    }
    const active = await requireClient();
    if (!active) {
        return undefined;
    }
    return quickPickSymbol(await active.tree());
}

// ---------------------------------------------------------------------------
// Status bar
// ---------------------------------------------------------------------------

function setStatus(text: string, tooltip: string, command = 'storyteller.index'): void {
    if (!statusItem) {
        return;
    }
    statusItem.text = `$(type-hierarchy-sub) ${text}`;
    statusItem.tooltip = tooltip;
    statusItem.command = command;
    statusItem.show();
}

async function refreshStatus(): Promise<void> {
    if (!engineAvailable()) {
        setStatus('engine not found', engineMissingMessage(discoveryRoots(), settings().enginePath));
        return;
    }
    try {
        const health = await getClient().health();
        const sources = Object.entries(health.cache.sources ?? {})
            .map(([name, count]) => `${count} ${name}`)
            .join(', ');
        setStatus(
            `${health.stats.symbols} symbols`,
            [
                `${health.repo}: ${health.stats.files} files, ${health.stats.symbols} symbols, ` +
                    `${health.stats.resolved_call_edges} resolved call edges.`,
                `Engine build ${health.build_seconds}s. Cached insights: ${health.cache.insights}` +
                    (sources ? ` (${sources})` : '') + '.',
                'Click to re-index.',
            ].join('\n\n')
        );
    } catch (error) {
        setStatus('engine offline', String((error as Error).message ?? error), 'storyteller.index');
    }
}

async function warmUp(): Promise<void> {
    if (warming) {
        return;
    }
    warming = true;
    try {
        setStatus('indexing...', 'Building the architecture model', 'storyteller.index');
        const active = await requireClient();
        if (!active) {
            setStatus('engine not found', engineMissingMessage(discoveryRoots(), settings().enginePath));
            return;
        }
        const report = await active.index(false);
        output?.appendLine(`[extension] ${describeReport(report)}`);
    } catch (error) {
        output?.appendLine(`[extension] warm-up failed: ${String((error as Error).message ?? error)}`);
    } finally {
        warming = false;
        await refreshStatus();
    }
}

// ---------------------------------------------------------------------------
// Activation
// ---------------------------------------------------------------------------

export function activate(context: vscode.ExtensionContext): void {
    currentContext = context;
    output = vscode.window.createOutputChannel('Architecture Storyteller');
    statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 40);
    context.subscriptions.push(output, statusItem);

    const delegate: MapPanelDelegate = {
        engineOrigin,
        index: async (force) => {
            await withClient((active) => indexWorkspace(active, Boolean(force), async () => {
                await MapPanel.refresh();
                await refreshStatus();
            }));
        },
        openDossier: async (level) => {
            await withClient((active) => exportDossier(context, active, level));
        },
        showUsages: async (symbol) => {
            try {
                await withClient((active) => showUsages(context, active, symbol));
            } catch (error) {
                void vscode.window.showErrorMessage(String((error as Error).message ?? error));
            }
        },
        showContext: async (symbol) => {
            try {
                await withClient((active) => showContext(context, active, symbol));
            } catch (error) {
                void vscode.window.showErrorMessage(String((error as Error).message ?? error));
            }
        },
    };

    context.subscriptions.push(
        vscode.commands.registerCommand('storyteller.mindmap', async (argument?: unknown) => {
            const symbol = typeof argument === 'string' ? argument : undefined;
            await withClient(() =>
                MapPanel.show(context, clientProvider, delegate, settings().defaultLevel, symbol)
            );
        }),

        vscode.commands.registerCommand('storyteller.context', async (argument?: unknown) => {
            const symbol = await resolveSymbol(argument);
            if (!symbol) {
                return;
            }
            try {
                await withClient((active) => showContext(context, active, symbol));
            } catch (error) {
                void vscode.window.showErrorMessage(
                    `No context for "${symbol}": ${String((error as Error).message ?? error)}`
                );
            }
        }),

        vscode.commands.registerCommand('storyteller.usages', async (argument?: unknown) => {
            const symbol = await resolveSymbol(argument);
            if (!symbol) {
                return;
            }
            try {
                await withClient((active) => showUsages(context, active, symbol));
            } catch (error) {
                void vscode.window.showErrorMessage(
                    `No call sites for "${symbol}": ${String((error as Error).message ?? error)}`
                );
            }
        }),

        vscode.commands.registerCommand('storyteller.inspectDependencies', async (argument?: unknown) => {
            await vscode.commands.executeCommand('storyteller.usages', argument);
        }),

        vscode.commands.registerCommand('storyteller.askBobAI', async (argument?: unknown) => {
            const symbol = await resolveSymbol(argument);
            if (!symbol) {
                return;
            }
            const active = await requireClient();
            if (!active) {
                return;
            }
            try {
                const payload = await active.context(symbol, 40);
                const health = await active.health();
                const providers = health.last_index?.providers_available ?? [];
                const live = providers.filter((name) => !name.startsWith('Deterministic'));
                const note = live.length > 0
                    ? `Live providers available: ${live.join(', ')}. Summaries come from the first provider that answers.`
                    : 'No live provider is reachable. Summaries are generated deterministically from names, ' +
                      'docstrings and the call graph. Configure storyteller.bobCommand or storyteller.llmUrl to use a model.';
                const body = [
                    `<div class="detail-head"><h2>${escapeHtml(payload.symbol.qualified)}</h2>`,
                    `<div class="where">${escapeHtml(payload.symbol.file)}:${payload.symbol.line}</div></div>`,
                    '<div class="callout">',
                    `<div>${escapeHtml(payload.insight.micro ?? 'No stored summary yet.')}</div>`,
                    payload.insight.why ? `<div>${escapeHtml(payload.insight.why)}</div>` : '',
                    `<span class="src">Summary source: ${escapeHtml(payload.insight.source ?? 'not generated')}</span>`,
                    '</div>',
                    `<p>${escapeHtml(note)}</p>`,
                ].join('\n');
                showDocumentPanel(context, {
                    key: 'insight',
                    title: `Insight - ${payload.symbol.name}`,
                    bodyHtml: body,
                });
            } catch (error) {
                void vscode.window.showErrorMessage(String((error as Error).message ?? error));
            }
        }),

        vscode.commands.registerCommand('storyteller.setEngineDirectory', async () => {
            await chooseEngineDirectory();
        }),

        vscode.commands.registerCommand('storyteller.configureScope', async () => {
            const level = await pickLevel(settings().defaultLevel);
            if (!level) {
                return;
            }
            // Workspace target throws when no folder is open, which this
            // extension otherwise supports: fall back to user settings.
            const target = workspaceRoots().length
                ? vscode.ConfigurationTarget.Workspace
                : vscode.ConfigurationTarget.Global;
            await vscode.workspace.getConfiguration('storyteller').update('defaultDepth', level, target);
            await MapPanel.setLevel(level);
            void vscode.window.showInformationMessage(`Default depth set to L${level} ${LEVEL_LABELS[level]}.`);
        }),

        vscode.commands.registerCommand('storyteller.index', async () => {
            await withClient((active) => indexWorkspace(active, false, async () => {
                await MapPanel.refresh();
                await refreshStatus();
            }));
        }),

        vscode.commands.registerCommand('storyteller.pdf', async () => {
            await withClient((active) => exportPdf(active, settings().defaultLevel));
        }),

        vscode.commands.registerCommand('storyteller.exportDossier', async () => {
            const level = await pickLevel(settings().defaultLevel);
            if (!level) {
                return;
            }
            await withClient((active) => exportDossier(context, active, level));
        }),

        vscode.commands.registerCommand('storyteller.previewDossier', async () => {
            const level = await pickLevel(settings().defaultLevel);
            if (level) {
                await withClient((active) => previewDossier(context, active, level));
            }
        }),

        vscode.commands.registerCommand('storyteller.openLocation', async (argument?: { file?: string; line?: number }) => {
            if (!argument?.file) {
                return;
            }
            const root = workspaceRoots()[0] ?? '';
            const absolute = path.isAbsolute(argument.file) ? argument.file : path.join(root, argument.file);
            const document = await vscode.workspace.openTextDocument(vscode.Uri.file(absolute));
            const line = Math.max(0, (argument.line ?? 1) - 1);
            await vscode.window.showTextDocument(document, {
                preview: true,
                selection: new vscode.Range(new vscode.Position(line, 0), new vscode.Position(line, 0)),
            });
        })
    );

    registerArchitectureHoverProvider(context, clientProvider);

    context.subscriptions.push(
        vscode.workspace.onDidChangeConfiguration((event) => {
            // Only settings baked into the engine process require a restart.
            // Depth and hover are read per call, and restarting here would
            // throw away the indexed model every time the level changes.
            const engineSettings = [
                'storyteller.pythonPath',
                'storyteller.enginePath',
                'storyteller.bobCommand',
                'storyteller.llmUrl',
                'storyteller.llmModel',
            ];
            if (engineSettings.some((key) => event.affectsConfiguration(key))) {
                client?.dispose();
                client = undefined;
                void refreshStatus();
            }
        }),

        // Opening a folder after the window started (or closing the last one)
        // changes where the engine can be found, so start again from scratch.
        vscode.workspace.onDidChangeWorkspaceFolders(() => {
            client?.dispose();
            client = undefined;
            if (engineAvailable()) {
                void warmUp();
            } else {
                void refreshStatus();
            }
        })
    );

    setStatus('starting...', 'Starting the architecture engine');
    void warmUp();
}

export function deactivate(): void {
    client?.dispose();
    client = undefined;
    statusItem?.dispose();
    statusItem = undefined;
}
