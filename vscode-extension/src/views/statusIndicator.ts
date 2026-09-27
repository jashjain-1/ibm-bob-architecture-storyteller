/**
 * statusIndicator.ts
 * ------------------
 * Updates a status bar item reflecting the dependency blast-radius tier of the currently active file.
 */

import * as vscode from 'vscode';
import { RippleFileDecorationProvider } from './fileDecorationProvider';

export class RippleStatusIndicator implements vscode.Disposable {
    private readonly item: vscode.StatusBarItem;
    private readonly disposables: vscode.Disposable[] = [];

    constructor(private readonly decorationProvider: RippleFileDecorationProvider) {
        this.item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 39);
        this.item.command = 'storyteller.rippleDependency';
        this.disposables.push(
            this.item,
            vscode.window.onDidChangeActiveTextEditor(() => this.update()),
            vscode.workspace.onDidSaveTextDocument(() => this.update())
        );
        this.update();
    }

    public update(): void {
        const editor = vscode.window.activeTextEditor;
        if (!editor || editor.document.isUntitled) {
            this.item.hide();
            return;
        }

        const info = this.decorationProvider.getDependencyInfo(editor.document.uri);
        if (!info) {
            this.item.hide();
            return;
        }

        let icon = '$(circle-filled)';
        let tierLabel = 'Low Risk';
        if (info.tier === 'red') {
            icon = '$(flame)';
            tierLabel = 'High Blast Radius';
        } else if (info.tier === 'yellow') {
            icon = '$(alert)';
            tierLabel = 'Moderate Impact';
        } else {
            icon = '$(check)';
            tierLabel = 'Safe';
        }

        this.item.text = `${icon} Ripple: ${tierLabel} (${info.dependents_count} dep${info.dependents_count === 1 ? '' : 's'})`;
        this.item.tooltip = new vscode.MarkdownString(
            `**Ripple Blast Radius: ${info.tier_label}**\n\n` +
            `- **Dependents:** ${info.dependents_count} external file(s)\n` +
            `- **Total Call Sites:** ${info.total_inbound_calls}\n\n` +
            `*Click to inspect downstream disturbed files and callers.*`
        );
        this.item.show();
    }

    public dispose(): void {
        for (const d of this.disposables) {
            d.dispose();
        }
    }
}
