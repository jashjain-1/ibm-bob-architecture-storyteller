/**
 * fileDecorationProvider.ts
 * -------------------------
 * Displays dynamic green-to-red dependency health badges on files in the VSCode Explorer.
 *
 * Tiers:
 *  - Green: 0-2 dependents (Isolated / Low Blast Radius)
 *  - Yellow: 3-7 dependents (Moderate Impact)
 *  - Red: 8+ dependents or core architectural hub (High Blast Radius)
 */

import * as path from 'path';
import * as vscode from 'vscode';
import { EngineClient } from '../engine/client';
import { BlastRadiusTier, FileDependencyInfo } from '../engine/types';

export class RippleFileDecorationProvider implements vscode.FileDecorationProvider, vscode.Disposable {
    private readonly _onDidChangeFileDecorations = new vscode.EventEmitter<vscode.Uri | vscode.Uri[] | undefined>();
    public readonly onDidChangeFileDecorations = this._onDidChangeFileDecorations.event;

    private fileDepMap = new Map<string, FileDependencyInfo>();
    private disposed = false;

    constructor(private readonly getClient: () => EngineClient | undefined) {}

    public async refresh(): Promise<void> {
        if (this.disposed) {
            return;
        }
        const client = this.getClient();
        if (!client) {
            return;
        }
        try {
            const deps = await client.dependencies();
            this.fileDepMap.clear();
            for (const [fpath, info] of Object.entries(deps.files)) {
                // Normalize path with forward slashes and lower case for lookup
                const norm = fpath.replace(/\\/g, '/');
                this.fileDepMap.set(norm, info);
            }
            this._onDidChangeFileDecorations.fire(undefined);
        } catch {
            // Engine might be offline or initializing
        }
    }

    public getDependencyInfo(uri: vscode.Uri): FileDependencyInfo | undefined {
        const workspaceFolder = vscode.workspace.getWorkspaceFolder(uri);
        if (!workspaceFolder) {
            return undefined;
        }
        const relPath = path.relative(workspaceFolder.uri.fsPath, uri.fsPath).replace(/\\/g, '/');
        return this.fileDepMap.get(relPath);
    }

    public provideFileDecoration(uri: vscode.Uri): vscode.ProviderResult<vscode.FileDecoration> {
        const info = this.getDependencyInfo(uri);
        if (!info) {
            return undefined;
        }

        switch (info.tier) {
            case 'green':
                return {
                    badge: '●',
                    color: new vscode.ThemeColor('testing.iconPassed'),
                    tooltip: `[Ripple Safe] ${info.dependents_count} dependent file(s). Low blast radius.`,
                    propagate: false,
                };
            case 'yellow':
                return {
                    badge: '●',
                    color: new vscode.ThemeColor('charts.yellow'),
                    tooltip: `[Ripple Moderate] ${info.dependents_count} dependent file(s), ${info.total_inbound_calls} call site(s). Review downstream callers before editing.`,
                    propagate: false,
                };
            case 'red':
                return {
                    badge: '●',
                    color: new vscode.ThemeColor('errorForeground'),
                    tooltip: `[Ripple High Blast Radius] ${info.dependents_count} dependent file(s), ${info.total_inbound_calls} call site(s). Core architectural hub!`,
                    propagate: false,
                };
            default:
                return undefined;
        }
    }

    public dispose(): void {
        this.disposed = true;
        this._onDidChangeFileDecorations.dispose();
    }
}
