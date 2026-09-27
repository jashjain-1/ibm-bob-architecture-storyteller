/**
 * mapPanel.ts
 * -----------
 * Hosts the map webview and bridges its messages to the engine.
 *
 * The webview receives the compact tree payload plus the engine's base URL, so
 * detail lookups and graph data come straight from the engine. Messages exist
 * only for things the webview cannot do itself: indexing, opening files,
 * exporting the dossier and the CSP fallback for context lookups.
 */

import * as path from 'path';
import * as vscode from 'vscode';

import { EngineClient } from '../engine/client';
import { DepthLevel, SymbolContext, TreePayload } from '../engine/types';
import { shellHtml } from '../webview/shell';

export interface MapPanelDelegate {
    index(force?: boolean): Promise<void>;
    openDossier(level: DepthLevel): Promise<void>;
    showUsages(symbol: string): Promise<void>;
    showContext(symbol: string): Promise<void>;
    engineOrigin(): 'configured' | 'workspace';
}

/**
 * The engine client is recycled whenever the engine must restart (settings or
 * workspace folders changed), so the panel must never hold on to an instance:
 * a captured client goes stale and every later lookup fails with "disposed".
 * Resolve it lazily instead, the same way the hover provider does.
 */
export type ClientProvider = () => EngineClient | undefined;

interface InboundMessage {
    command?: string;
    symbol?: string;
    level?: DepthLevel;
    file?: string;
    line?: number;
    force?: boolean;
}

export class MapPanel {
    private static current: MapPanel | undefined;

    private readonly disposables: vscode.Disposable[] = [];

    private constructor(
        private readonly panel: vscode.WebviewPanel,
        private readonly context: vscode.ExtensionContext,
        private readonly client: ClientProvider,
        private readonly delegate: MapPanelDelegate,
        private level: DepthLevel
    ) {
        this.panel.webview.html = this.html();
        this.panel.webview.onDidReceiveMessage(
            (message: InboundMessage) => void this.handle(message),
            undefined,
            this.disposables
        );
        this.panel.onDidDispose(() => this.dispose(), undefined, this.disposables);
    }

    public static async show(
        context: vscode.ExtensionContext,
        client: ClientProvider,
        delegate: MapPanelDelegate,
        level: DepthLevel,
        symbol?: string
    ): Promise<MapPanel> {
        if (MapPanel.current) {
            MapPanel.current.panel.reveal(vscode.ViewColumn.Active);
            MapPanel.current.level = level;
            await MapPanel.current.pushPayload(symbol);
            return MapPanel.current;
        }
        const panel = vscode.window.createWebviewPanel(
            'storyteller.map',
            'Architecture Map',
            vscode.ViewColumn.Active,
            {
                enableScripts: true,
                retainContextWhenHidden: true,
                localResourceRoots: [
                    vscode.Uri.joinPath(context.extensionUri, 'dist'),
                    vscode.Uri.joinPath(context.extensionUri, 'media'),
                ],
            }
        );
        const instance = new MapPanel(panel, context, client, delegate, level);
        MapPanel.current = instance;
        // The webview also asks for a payload once its script is running; this
        // send covers the opposite race, where that request is the lost message.
        void instance.pushPayload(symbol);
        return instance;
    }

    public static get open(): boolean {
        return Boolean(MapPanel.current);
    }

    /** Re-read the model and push it to the webview (used after indexing). */
    public static async refresh(): Promise<void> {
        if (MapPanel.current) {
            await MapPanel.current.pushPayload();
        }
    }

    public static async setLevel(level: DepthLevel): Promise<void> {
        if (MapPanel.current) {
            MapPanel.current.level = level;
            MapPanel.current.panel.webview.postMessage({ type: 'level', level });
        }
    }

    public static async focus(symbol: string): Promise<void> {
        if (MapPanel.current) {
            MapPanel.current.panel.reveal(vscode.ViewColumn.Active);
            MapPanel.current.panel.webview.postMessage({ type: 'focus', message: symbol });
        }
    }

    public dispose(): void {
        MapPanel.current = undefined;
        this.panel.dispose();
        while (this.disposables.length) {
            this.disposables.pop()?.dispose();
        }
    }

    // -- internals ---------------------------------------------------------

    private workspaceRoot(): string {
        return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? '';
    }

    private html(): string {
        const webview = this.panel.webview;
        const nonce = Array.from({ length: 32 }, () =>
            'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'[
                Math.floor(Math.random() * 62)
            ]).join('');
        const styleUri = webview.asWebviewUri(
            vscode.Uri.joinPath(this.context.extensionUri, 'media', 'map.css')
        ).toString();
        const scriptUri = webview.asWebviewUri(
            vscode.Uri.joinPath(this.context.extensionUri, 'dist', 'webview', 'map.js')
        ).toString();
        return shellHtml({
            title: 'Architecture Storyteller',
            payload: {
                payload: undefined,
                apiBase: '',
                level: this.level,
                workspaceRoot: this.workspaceRoot(),
                engine: this.delegate.engineOrigin(),
            },
            scriptUri,
            styleUri,
            cspSource: webview.cspSource,
            nonce,
            // Classic script, not a module: see scripts/finalize_webview.mjs.
            moduleScript: false,
        });
    }

    /** Current engine client, or undefined when it is being restarted. */
    private requireClient(): EngineClient | undefined {
        const client = this.client();
        if (!client) {
            this.panel.webview.postMessage({
                type: 'status',
                message: 'The engine is restarting; try again in a moment.',
                isError: true,
            });
        }
        return client;
    }

    private async pushPayload(symbol?: string): Promise<void> {
        const client = this.requireClient();
        if (!client) {
            return;
        }
        try {
            const [tree, apiBase] = await Promise.all([client.tree(true), client.baseUrl()]);
            this.panel.webview.postMessage({
                type: 'payload',
                payload: { ...tree, apiBase, level: this.level, workspaceRoot: this.workspaceRoot() } as TreePayload,
                apiBase,
            });
            if (symbol) {
                this.panel.webview.postMessage({ type: 'focus', message: symbol });
            }
        } catch (error) {
            this.panel.webview.postMessage({
                type: 'status',
                message: `Engine unavailable: ${String((error as Error).message ?? error)}`,
                isError: true,
            });
        }
    }

    private async handle(message: InboundMessage): Promise<void> {
        switch (message.command) {
            case 'ready':
                await this.pushPayload();
                break;
            case 'refresh':
                this.client()?.invalidate();
                await this.pushPayload();
                break;
            case 'index':
                await this.delegate.index(Boolean(message.force));
                break;
            case 'dossier':
                await this.delegate.openDossier((message.level ?? this.level) as DepthLevel);
                break;
            case 'usages':
                if (message.symbol) {
                    await this.delegate.showUsages(message.symbol);
                }
                break;
            case 'context': {
                if (!message.symbol) {
                    break;
                }
                const client = this.client();
                if (!client) {
                    this.panel.webview.postMessage({
                        type: 'context',
                        symbolId: message.symbol,
                        error: 'The engine is restarting; try again in a moment.',
                    });
                    break;
                }
                try {
                    const context = await client.context(message.symbol, 60);
                    this.panel.webview.postMessage({ type: 'context', symbolId: message.symbol, context });
                } catch (error) {
                    this.panel.webview.postMessage({
                        type: 'context',
                        symbolId: message.symbol,
                        error: String((error as Error).message ?? error),
                    });
                }
                break;
            }
            case 'level': {
                if (message.level) {
                    this.level = message.level;
                    // Workspace target throws when no folder is open, which this
                    // extension otherwise supports: fall back to user settings.
                    const target = vscode.workspace.workspaceFolders?.length
                        ? vscode.ConfigurationTarget.Workspace
                        : vscode.ConfigurationTarget.Global;
                    await vscode.workspace.getConfiguration('storyteller').update(
                        'defaultDepth', message.level, target
                    );
                }
                break;
            }
            case 'openFile': {
                if (!message.file) {
                    break;
                }
                const root = this.workspaceRoot();
                const absolute = path.isAbsolute(message.file) ? message.file : path.join(root, message.file);
                const document = await vscode.workspace.openTextDocument(vscode.Uri.file(absolute));
                const line = Math.max(0, (message.line ?? 1) - 1);
                await vscode.window.showTextDocument(document, {
                    preview: true,
                    selection: new vscode.Range(
                        new vscode.Position(line, 0),
                        new vscode.Position(line, 0)
                    ),
                });
                break;
            }
            case 'openContext':
                if (message.symbol) {
                    await this.delegate.showContext(message.symbol);
                }
                break;
            default:
                break;
        }
    }
}

export type { SymbolContext };
