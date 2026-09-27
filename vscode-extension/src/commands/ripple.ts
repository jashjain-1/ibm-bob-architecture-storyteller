/**
 * commands/ripple.ts
 * ------------------
 * Interactive implementations for:
 * 1. storyteller.createDocumentation
 * 2. storyteller.rippleDependency
 * 3. storyteller.whatIfAmended
 * 4. storyteller.applyPreventivePatch
 */

import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { EngineClient } from '../engine/client';
import { RippleFileDecorationProvider } from '../views/fileDecorationProvider';
import { RipplePatchContentProvider } from '../views/patchContentProvider';
import { PreventivePatch, RippleAnalysisPayload } from '../engine/types';

function getActiveSymbolOrText(editor: vscode.TextEditor): {
    symbol: string;
    code: string;
    range: vscode.Range;
    line: number;
} {
    const selection = editor.selection;
    if (!selection.isEmpty) {
        const text = editor.document.getText(selection).trim();
        // If selection is a symbol or small block
        const wordMatch = text.match(/^[A-Za-z_$][\w$]*/);
        const sym = wordMatch ? wordMatch[0] : text.slice(0, 40);
        return {
            symbol: sym,
            code: text,
            range: selection,
            line: selection.start.line + 1,
        };
    }

    const wordRange = editor.document.getWordRangeAtPosition(selection.active, /[A-Za-z_$][\w$]*/);
    if (wordRange) {
        const sym = editor.document.getText(wordRange).trim();
        const line = editor.document.lineAt(selection.active.line);
        return {
            symbol: sym,
            code: line.text,
            range: wordRange,
            line: selection.active.line + 1,
        };
    }

    const line = editor.document.lineAt(selection.active.line);
    return {
        symbol: line.text.trim().slice(0, 30) || 'routine',
        code: line.text,
        range: line.range,
        line: selection.active.line + 1,
    };
}

export function registerRippleCommands(
    context: vscode.ExtensionContext,
    getClient: () => EngineClient | undefined,
    decorationProvider: RippleFileDecorationProvider,
    patchProvider: RipplePatchContentProvider
): void {
    // -----------------------------------------------------------------------
    // 1. Create Documentation
    // -----------------------------------------------------------------------
    context.subscriptions.push(
        vscode.commands.registerCommand('storyteller.createDocumentation', async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor) {
                void vscode.window.showInformationMessage('Open a file to generate documentation.');
                return;
            }

            const client = getClient();
            if (!client) {
                void vscode.window.showErrorMessage('Storyteller Engine is offline.');
                return;
            }

            const target = getActiveSymbolOrText(editor);
            const docUri = editor.document.uri;
            const workspaceFolder = vscode.workspace.getWorkspaceFolder(docUri);
            const relPath = workspaceFolder
                ? path.relative(workspaceFolder.uri.fsPath, docUri.fsPath).replace(/\\/g, '/')
                : docUri.fsPath;

            await vscode.window.withProgress(
                {
                    location: vscode.ProgressLocation.Notification,
                    title: `Generating documentation for \`${target.symbol}\`...`,
                    cancellable: false,
                },
                async () => {
                    try {
                        const result = await client.doc({
                            symbol: target.symbol,
                            file: relPath,
                            code: target.code,
                            language: editor.document.languageId,
                        });

                        // Determine indentation and insertion line based on language & symbol
                        const targetLineIndex = target.range.start.line;
                        const lineObj = editor.document.lineAt(targetLineIndex);
                        const indent = lineObj.text.match(/^\s*/)?.[0] ?? '';

                        let insertLine = targetLineIndex;
                        let docIndent = indent;

                        if (editor.document.languageId === 'python') {
                            // Check if target line or surrounding lines define a function or class
                            let defLineIndex = -1;
                            for (let i = targetLineIndex; i >= Math.max(0, targetLineIndex - 3); i--) {
                                const text = editor.document.lineAt(i).text;
                                if (/^\s*(def|class|async\s+def)\b/.test(text)) {
                                    defLineIndex = i;
                                    break;
                                }
                            }
                            if (defLineIndex === -1) {
                                for (let i = targetLineIndex; i < Math.min(targetLineIndex + 5, editor.document.lineCount); i++) {
                                    const text = editor.document.lineAt(i).text;
                                    if (/^\s*(def|class|async\s+def)\b/.test(text)) {
                                        defLineIndex = i;
                                        break;
                                    }
                                }
                            }

                            if (defLineIndex !== -1) {
                                // Find line containing the colon ':' ending the signature
                                let colonLineIndex = defLineIndex;
                                while (colonLineIndex < Math.min(defLineIndex + 15, editor.document.lineCount)) {
                                    const text = editor.document.lineAt(colonLineIndex).text.trim();
                                    if (text.endsWith(':') || /:\s*(#.*)?$/.test(text)) {
                                        break;
                                    }
                                    colonLineIndex++;
                                }
                                const baseIndent = editor.document.lineAt(defLineIndex).text.match(/^\s*/)?.[0] ?? '';
                                docIndent = baseIndent + '    ';
                                insertLine = colonLineIndex + 1;
                            }
                        }

                        // Indent the docstring to match target line indentation
                        const indentedDoc = result.docstring
                            .split('\n')
                            .map((l) => (l.trim() ? docIndent + l : l))
                            .join('\n') + '\n';

                        const editSuccess = await editor.edit((editBuilder) => {
                            editBuilder.insert(new vscode.Position(insertLine, 0), indentedDoc);
                        });

                        if (editSuccess) {
                            const choice = await vscode.window.showInformationMessage(
                                `Documentation inserted for \`${target.symbol}\`.`,
                                'Save Architecture Note'
                            );
                            if (choice === 'Save Architecture Note' && workspaceFolder) {
                                const docsDir = path.join(workspaceFolder.uri.fsPath, 'docs');
                                if (!fs.existsSync(docsDir)) {
                                    fs.mkdirSync(docsDir, { recursive: true });
                                }
                                const noteFile = path.join(docsDir, 'ARCHITECTURE_NOTES.md');
                                const noteEntry = `\n### \`${target.symbol}\` (${relPath}:${target.line})\n${result.architecture_note}\n\`\`\`${result.language}\n${result.docstring}\n\`\`\`\n`;
                                fs.appendFileSync(noteFile, noteEntry, 'utf-8');
                                void vscode.window.showInformationMessage(`Saved to ${noteFile}`);
                            }
                        }
                    } catch (error) {
                        void vscode.window.showErrorMessage(
                            `Documentation generation failed: ${String((error as Error).message ?? error)}`
                        );
                    }
                }
            );
        })
    );

    // -----------------------------------------------------------------------
    // 2. Dependency (Show disturbed files on edit/delete)
    // -----------------------------------------------------------------------
    context.subscriptions.push(
        vscode.commands.registerCommand('storyteller.rippleDependency', async () => {
            const editor = vscode.window.activeTextEditor;
            const client = getClient();
            if (!client) {
                void vscode.window.showErrorMessage('Storyteller Engine is offline.');
                return;
            }

            let relFile = '';
            let targetSymbol = '';
            if (editor) {
                const target = getActiveSymbolOrText(editor);
                targetSymbol = target.symbol;
                const wf = vscode.workspace.getWorkspaceFolder(editor.document.uri);
                relFile = wf
                    ? path.relative(wf.uri.fsPath, editor.document.uri.fsPath).replace(/\\/g, '/')
                    : '';
            }

            type DepItem = vscode.QuickPickItem & { file?: string; line?: number };
            const items: DepItem[] = [];

            try {
                await vscode.window.withProgress(
                    {
                        location: vscode.ProgressLocation.Notification,
                        title: `Analyzing blast radius and workspace dependencies${relFile ? ` for ${path.basename(relFile)}` : ''}...`,
                        cancellable: false,
                    },
                    async () => {
                        const deps = await client.dependencies();
                        const fileInfo = relFile ? deps.files[relFile] : undefined;

                        if (fileInfo) {
                            items.push({
                                label: `$(shield) Blast Radius: ${fileInfo.tier.toUpperCase()} (${fileInfo.tier_label})`,
                                description: `${fileInfo.dependents_count} dependent file(s), ${fileInfo.total_inbound_calls} call site(s)`,
                                detail: `Target File: ${relFile}`,
                            });

                            // Add callers for this file
                            if (fileInfo.callers && fileInfo.callers.length > 0) {
                                items.push({ label: '--- Inbound Call Sites & Callers ---', kind: vscode.QuickPickItemKind.Separator });
                                for (const caller of fileInfo.callers) {
                                    items.push({
                                        label: `$(references) ${caller.caller_name}`,
                                        description: `${caller.caller_file}:${caller.caller_line}`,
                                        detail: `Calls symbol: \`${caller.target_symbol}\``,
                                        file: caller.caller_file,
                                        line: caller.caller_line,
                                    });
                                }
                            }
                        }

                        // If symbol is active, also lookup exact usages
                        if (targetSymbol) {
                            try {
                                const usages = await client.usages(targetSymbol);
                                if (usages && usages.callers.length > 0) {
                                    items.push({ label: `--- Call Sites of Symbol \`${targetSymbol}\` ---`, kind: vscode.QuickPickItemKind.Separator });
                                    for (const caller of usages.callers) {
                                        items.push({
                                            label: `$(symbol-method) ${caller.qualified}`,
                                            description: `${caller.file}:${caller.line}`,
                                            detail: (caller.raw_calls || []).join('; ') || 'Invocation',
                                            file: caller.file,
                                            line: caller.line,
                                        });
                                    }
                                }
                            } catch {
                                // ignore symbol specific lookup error
                            }
                        }

                        // Add other high-impact files across workspace
                        items.push({ label: '--- Workspace Architectural Hubs & Impact ---', kind: vscode.QuickPickItemKind.Separator });
                        for (const [f, info] of Object.entries(deps.files)) {
                            if (info.dependents_count >= 3 && f !== relFile) {
                                const icon = info.tier === 'red' ? '$(flame)' : '$(alert)';
                                items.push({
                                    label: `${icon} ${f}`,
                                    description: `[${info.tier.toUpperCase()}] ${info.dependents_count} dependent file(s)`,
                                    detail: `${info.total_inbound_calls} total inbound calls`,
                                    file: f,
                                    line: 1,
                                });
                            }
                        }
                    }
                );
            } catch (error) {
                void vscode.window.showErrorMessage(
                    `Failed to analyze workspace dependencies: ${String((error as Error).message ?? error)}`
                );
                return;
            }

            if (items.length === 0) {
                void vscode.window.showInformationMessage('No dependency information available.');
                return;
            }

            const picked = await vscode.window.showQuickPick(items, {
                title: `Dependency Blast Radius - ${relFile || 'Workspace'}`,
                placeHolder: 'Select a caller or dependent file to jump to code',
            });

            if (picked?.file) {
                await vscode.commands.executeCommand('storyteller.openLocation', {
                    file: picked.file,
                    line: picked.line ?? 1,
                });
            }
        })
    );

    // -----------------------------------------------------------------------
    // 3. What If (Amended/Deleted Ripple Analysis & Preventive Patches)
    // -----------------------------------------------------------------------
    context.subscriptions.push(
        vscode.commands.registerCommand('storyteller.whatIfAmended', async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor) {
                void vscode.window.showInformationMessage('Open a file and highlight code to run What-If ripple analysis.');
                return;
            }

            const client = getClient();
            if (!client) {
                void vscode.window.showErrorMessage('Storyteller Engine is offline.');
                return;
            }

            const target = getActiveSymbolOrText(editor);
            const docUri = editor.document.uri;
            const workspaceFolder = vscode.workspace.getWorkspaceFolder(docUri);
            const relPath = workspaceFolder
                ? path.relative(workspaceFolder.uri.fsPath, docUri.fsPath).replace(/\\/g, '/')
                : docUri.fsPath;

            // Scenario picker
            const scenarios: (vscode.QuickPickItem & { id: string })[] = [
                {
                    label: '$(trash) Delete this symbol / block',
                    description: 'Simulate complete deletion of the selected routine or contract',
                    id: 'delete',
                },
                {
                    label: '$(symbol-parameter) Change signature / return type',
                    description: 'Simulate changing parameter signatures, types, or return shapes',
                    id: 'signature',
                },
                {
                    label: '$(zap) Change logic / state transitions',
                    description: 'Simulate amending business logic, caching assumptions, or invariants',
                    id: 'logic',
                },
                {
                    label: '$(edit) Custom amendment...',
                    description: 'Type a specific hypothetical code amendment to test',
                    id: 'custom',
                },
            ];

            const pickedScenario = await vscode.window.showQuickPick(scenarios, {
                title: `What If: Ripple Analysis for \`${target.symbol}\``,
                placeHolder: 'Choose a hypothetical amendment scenario',
            });

            if (!pickedScenario) {
                return;
            }

            let customText = '';
            if (pickedScenario.id === 'custom') {
                const input = await vscode.window.showInputBox({
                    prompt: `Describe the amendment to \`${target.symbol}\``,
                    placeHolder: 'e.g. Change user_status to enum and remove legacy boolean',
                });
                if (!input) {
                    return;
                }
                customText = input;
            }

            let analysis: RippleAnalysisPayload | undefined;
            await vscode.window.withProgress(
                {
                    location: vscode.ProgressLocation.Notification,
                    title: `Ripple-Agent: Synthesizing downstream impact for \`${target.symbol}\`...`,
                    cancellable: false,
                },
                async () => {
                    try {
                        analysis = await client.ripple({
                            symbol: target.symbol,
                            file: relPath,
                            code: target.code,
                            scenario: pickedScenario.id,
                            customAmendment: customText,
                        });
                    } catch (error) {
                        void vscode.window.showErrorMessage(
                            `Ripple-Agent analysis failed: ${String((error as Error).message ?? error)}`
                        );
                    }
                }
            );

            if (!analysis) {
                return;
            }

            // Present results in interactive QuickPick
            type RipplePickItem = vscode.QuickPickItem & {
                action?: 'diff' | 'info';
                patch?: PreventivePatch;
                file?: string;
                line?: number;
            };

            const resultItems: RipplePickItem[] = [
                {
                    label: `$(alert) Semantic Warning`,
                    detail: analysis.semantic_warning,
                    action: 'info',
                },
                {
                    label: `$(organization) Blast Radius: ${analysis.blast_radius_tier.toUpperCase()}`,
                    description: `${analysis.dependents_count} dependent file(s) affected`,
                    detail: analysis.orchestrator_summary,
                    action: 'info',
                },
                {
                    label: '--- Disturbed Files & Preventive Patches ---',
                    kind: vscode.QuickPickItemKind.Separator,
                },
            ];

            for (const patch of analysis.preventive_patches) {
                resultItems.push({
                    label: `$(diff) ${patch.file}`,
                    description: 'Preventive patch available',
                    detail: patch.explanation,
                    action: 'diff',
                    patch,
                    file: patch.file,
                    line: 1,
                });
            }

            for (const finding of analysis.downstream_findings) {
                if (!analysis.preventive_patches.some((p) => p.file === finding.file)) {
                    resultItems.push({
                        label: `$(references) ${finding.file}:${finding.line}`,
                        description: `Caller: ${finding.symbol} [${finding.impact_type}]`,
                        detail: finding.description,
                        action: 'info',
                        file: finding.file,
                        line: finding.line,
                    });
                }
            }

            const selection = await vscode.window.showQuickPick(resultItems, {
                title: `Ripple-Agent Results: \`${target.symbol}\``,
                placeHolder: 'Select a disturbed file to view side-by-side preventive patch diff',
            });

            if (selection?.action === 'diff' && selection.patch) {
                const patch = selection.patch;
                const patchUri = patchProvider.registerPatch(patch);
                const root = workspaceFolder ? workspaceFolder.uri.fsPath : '';
                const origUri = vscode.Uri.file(path.isAbsolute(patch.file) ? patch.file : path.join(root, patch.file));

                await vscode.commands.executeCommand(
                    'vscode.diff',
                    origUri,
                    patchUri,
                    `${path.basename(patch.file)}: Original <-> Preventive Patch`
                );

                const applyChoice = await vscode.window.showInformationMessage(
                    `Preventive patch previewed for ${patch.file}. Apply changes to disk?`,
                    'Apply Preventive Patch',
                    'Cancel'
                );

                if (applyChoice === 'Apply Preventive Patch') {
                    await vscode.commands.executeCommand('storyteller.applyPreventivePatch', patch.file);
                }
            } else if (selection?.file) {
                await vscode.commands.executeCommand('storyteller.openLocation', {
                    file: selection.file,
                    line: selection.line ?? 1,
                });
            }
        })
    );

    // -----------------------------------------------------------------------
    // 4. Apply Preventive Patch
    // -----------------------------------------------------------------------
    context.subscriptions.push(
        vscode.commands.registerCommand('storyteller.applyPreventivePatch', async (filePathArg?: string) => {
            let targetFile = filePathArg;
            if (!targetFile) {
                const patches = patchProvider.getAllPatches();
                if (patches.length === 0) {
                    void vscode.window.showInformationMessage('No preventive patches available to apply.');
                    return;
                }
                const pick = await vscode.window.showQuickPick(
                    patches.map((p) => ({ label: p.file, detail: p.explanation, patch: p })),
                    { title: 'Select patch to apply to disk' }
                );
                if (!pick) {
                    return;
                }
                targetFile = pick.patch.file;
            }

            const patch = patchProvider.getPatch(targetFile);
            if (!patch) {
                void vscode.window.showErrorMessage(`No patch found for ${targetFile}`);
                return;
            }

            const wf = vscode.workspace.workspaceFolders?.[0];
            const root = wf ? wf.uri.fsPath : '';
            const absPath = path.isAbsolute(patch.file) ? patch.file : path.join(root, patch.file);

            try {
                fs.writeFileSync(absPath, patch.patched_content, 'utf-8');
                void vscode.window.showInformationMessage(`Successfully applied preventive patch to ${patch.file}`);
                await decorationProvider.refresh();
            } catch (error) {
                void vscode.window.showErrorMessage(
                    `Failed to apply patch: ${String((error as Error).message ?? error)}`
                );
            }
        })
    );
}
