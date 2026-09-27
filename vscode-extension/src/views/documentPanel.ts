/**
 * documentPanel.ts
 * ----------------
 * Reusable read-only webview panel for HTML documents (symbol context, usages
 * and the dossier preview). Scripts are disabled; interactions use command URIs.
 */

import * as vscode from 'vscode';

import { documentShell } from '../webview/shell';

const panels = new Map<string, vscode.WebviewPanel>();

export interface DocumentPanelOptions {
    key: string;
    title: string;
    bodyHtml: string;
}

export function showDocumentPanel(
    context: vscode.ExtensionContext,
    options: DocumentPanelOptions
): vscode.WebviewPanel {
    const styleUri = vscode.Uri.joinPath(context.extensionUri, 'media', 'map.css');
    let panel = panels.get(options.key);
    if (!panel) {
        panel = vscode.window.createWebviewPanel(
            `storyteller.${options.key}`,
            options.title,
            vscode.ViewColumn.Beside,
            {
                enableScripts: false,
                enableCommandUris: true,
                retainContextWhenHidden: false,
                localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, 'media')],
            }
        );
        panel.onDidDispose(() => panels.delete(options.key));
        panels.set(options.key, panel);
    }
    panel.title = options.title;

    const trimmed = options.bodyHtml.trim();
    if (trimmed.startsWith('<!DOCTYPE') || trimmed.startsWith('<html')) {
        panel.webview.html = options.bodyHtml;
    } else {
        panel.webview.html = documentShell({
            title: options.title,
            bodyHtml: options.bodyHtml,
            styleUri: panel.webview.asWebviewUri(styleUri).toString(),
            cspSource: panel.webview.cspSource,
        });
    }
    panel.reveal(vscode.ViewColumn.Beside, true);
    return panel;
}

export function disposeDocumentPanels(): void {
    for (const panel of panels.values()) {
        panel.dispose();
    }
    panels.clear();
}
