/**
 * dossier.ts
 * ----------
 * Dossier preview, PDF export and index commands.
 *
 * The dossier is one HTML document rendered by the installed Chromium, so the
 * preview in the editor and the exported PDF are the same artefact.
 */

import * as vscode from 'vscode';

import { EngineClient } from '../engine/client';
import { DepthLevel, IndexReport, LEVEL_HINTS, LEVEL_LABELS } from '../engine/types';
import { showDocumentPanel } from '../views/documentPanel';

export async function pickLevel(current: DepthLevel): Promise<DepthLevel | undefined> {
    const items: (vscode.QuickPickItem & { level: DepthLevel })[] = ([3, 2, 1] as DepthLevel[]).map((level) => ({
        label: `L${level} ${LEVEL_LABELS[level]}${level === current ? ' (current)' : ''}`,
        description: LEVEL_HINTS[level],
        level,
    }));
    const choice = await vscode.window.showQuickPick(items, {
        title: 'Dossier detail level',
        placeHolder: 'Level 2 Engineering is the usual choice',
    });
    return choice?.level;
}

export async function previewDossier(
    context: vscode.ExtensionContext,
    client: EngineClient,
    level: DepthLevel
): Promise<void> {
    await vscode.window.withProgress(
        {
            location: vscode.ProgressLocation.Notification,
            title: `Generating Architecture Dossier L${level} (${LEVEL_LABELS[level]})...`,
            cancellable: false,
        },
        async () => {
            try {
                const html = await client.dossierHtml(level);
                showDocumentPanel(context, {
                    key: 'dossier',
                    title: `Dossier L${level} ${LEVEL_LABELS[level]}`,
                    bodyHtml: html,
                });
            } catch (error) {
                void vscode.window.showErrorMessage(
                    `Failed to generate dossier preview: ${String((error as Error).message ?? error)}`
                );
            }
        }
    );
}

export async function exportDossier(
    context: vscode.ExtensionContext,
    client: EngineClient,
    level: DepthLevel
): Promise<void> {
    await previewDossier(context, client, level);
    const choice = await vscode.window.showInformationMessage(
        `Dossier L${level} ${LEVEL_LABELS[level]} is open in the preview.`,
        'Export PDF',
        'Save HTML...'
    );
    if (choice === 'Export PDF') {
        await exportPdf(client, level);
    } else if (choice === 'Save HTML...') {
        const target = await vscode.window.showSaveDialog({
            filters: { HTML: ['html'] },
            saveLabel: 'Save dossier HTML',
        });
        if (target) {
            try {
                const html = await client.dossierHtml(level);
                await vscode.workspace.fs.writeFile(target, Buffer.from(html, 'utf8'));
                void vscode.window.showInformationMessage(`Dossier written to ${target.fsPath}`);
            } catch (error) {
                void vscode.window.showErrorMessage(
                    `Failed to save HTML dossier: ${String((error as Error).message ?? error)}`
                );
            }
        }
    }
}

export async function exportPdf(client: EngineClient, level: DepthLevel): Promise<void> {
    await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: `Rendering dossier L${level} to PDF` },
        async () => {
            try {
                const result = await client.dossierPdf(level);
                const choice = await vscode.window.showInformationMessage(
                    `PDF written (${Math.round(result.bytes / 1024)} KB): ${result.pdf}`,
                    'Open PDF',
                    'Reveal'
                );
                const uri = vscode.Uri.file(result.pdf);
                if (choice === 'Open PDF') {
                    await vscode.commands.executeCommand('vscode.open', uri);
                } else if (choice === 'Reveal') {
                    await vscode.commands.executeCommand('revealFileInOS', uri);
                }
            } catch (error) {
                void vscode.window.showErrorMessage(
                    `Dossier export failed: ${String((error as Error).message ?? error)}`
                );
            }
        }
    );
}

export function describeReport(report: IndexReport): string {
    const delta = report.delta;
    const sources = Object.entries(report.sources ?? {})
        .map(([name, count]) => `${count} ${name}`)
        .join(', ');
    return [
        `${report.stats.symbols} symbols in ${report.stats.files} files.`,
        `Delta: +${delta.added} added, ~${delta.changed} changed, -${delta.removed} removed, ${delta.unchanged} unchanged.`,
        `Insights: ${report.generated} generated this run (${report.provider}); cache holds ${report.cached_total}` +
            (sources ? ` (${sources})` : '') + '.',
        report.fingerprint_changed ? 'Working tree changed since the previous index.' : 'Working tree unchanged since the previous index.',
    ].join(' ');
}

export async function indexWorkspace(
    client: EngineClient,
    force: boolean,
    onDone?: (report: IndexReport) => void | Promise<void>
): Promise<void> {
    await vscode.window.withProgress(
        {
            location: vscode.ProgressLocation.Notification,
            title: force ? 'Rebuilding architecture model' : 'Indexing architecture',
            cancellable: false,
        },
        async () => {
            try {
                const report = await client.index(force);
                await onDone?.(report);
                void vscode.window.showInformationMessage(describeReport(report));
            } catch (error) {
                void vscode.window.showErrorMessage(
                    `Indexing failed: ${String((error as Error).message ?? error)}`
                );
            }
        }
    );
}
