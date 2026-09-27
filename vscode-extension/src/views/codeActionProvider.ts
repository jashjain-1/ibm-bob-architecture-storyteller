/**
 * codeActionProvider.ts
 * ---------------------
 * Lightbulb CodeActionProvider offering Ripple-Agent actions:
 * 1. Create Documentation
 * 2. Dependency (Show disturbed files on edit/delete)
 * 3. What If (Amended/Deleted Ripple Analysis)
 */

import * as vscode from 'vscode';

export class RippleCodeActionProvider implements vscode.CodeActionProvider {
    public static readonly providedCodeActionKinds = [
        vscode.CodeActionKind.RefactorRewrite,
        vscode.CodeActionKind.QuickFix,
    ];

    public provideCodeActions(
        document: vscode.TextDocument,
        range: vscode.Range | vscode.Selection,
        context: vscode.CodeActionContext
    ): vscode.ProviderResult<(vscode.CodeAction | vscode.Command)[]> {
        const actions: vscode.CodeAction[] = [];

        // 1. Create Documentation
        const docAction = new vscode.CodeAction(
            'Create Documentation (Language-tailored Docstring)',
            vscode.CodeActionKind.RefactorRewrite
        );
        docAction.command = {
            command: 'storyteller.createDocumentation',
            title: 'Create Documentation',
            arguments: [],
        };
        actions.push(docAction);

        // 2. Dependency (Show disturbed files on edit/delete)
        const depAction = new vscode.CodeAction(
            'Dependency (Show files disturbed if edited/deleted)',
            vscode.CodeActionKind.RefactorRewrite
        );
        depAction.command = {
            command: 'storyteller.rippleDependency',
            title: 'Show Dependency',
            arguments: [],
        };
        actions.push(depAction);

        // 3. What If (Amended/Deleted Ripple Analysis)
        const whatIfAction = new vscode.CodeAction(
            'What If: Ripple Impact & Preventive Patches',
            vscode.CodeActionKind.RefactorRewrite
        );
        whatIfAction.command = {
            command: 'storyteller.whatIfAmended',
            title: 'What If Amended',
            arguments: [],
        };
        actions.push(whatIfAction);

        return actions;
    }
}
