/**
 * hoverProvider.ts
 * ----------------
 * Hover summaries served by the running engine.
 *
 * The old provider spawned a Python process per hovered word and dressed the
 * answer in canned classifications. This one asks the engine (one HTTP request,
 * cached) and shows only facts the model contains: kind, location, complexity,
 * call-site counts, capability flags, the stored summary with its source, and
 * the file's last recorded change.
 */

import * as vscode from 'vscode';

import { EngineClient } from '../engine/client';
import { SymbolContext } from '../engine/types';

const IGNORED_KEYWORDS = new Set([
    'if', 'else', 'elif', 'while', 'for', 'in', 'of', 'do', 'switch', 'case', 'break',
    'continue', 'return', 'yield', 'try', 'catch', 'finally', 'except', 'raise', 'throw',
    'import', 'from', 'as', 'export', 'default', 'package', 'const', 'let', 'var',
    'def', 'class', 'func', 'type', 'interface', 'struct', 'enum', 'true', 'false',
    'null', 'undefined', 'nil', 'none', 'self', 'this', 'super', 'new', 'delete',
    'async', 'await', 'public', 'private', 'protected', 'static', 'readonly',
]);

const SUPPORTED_LANGUAGES = [
    'python', 'typescript', 'javascript', 'typescriptreact', 'javascriptreact', 'go',
];

function sourceLabel(context: SymbolContext): string {
    const source = context.insight.source ?? 'auto';
    if (source === 'bob') {
        return context.insight.model ? `IBM Bob (${context.insight.model})` : 'IBM Bob';
    }
    if (source === 'llm') {
        return context.insight.model ? `local LLM (${context.insight.model})` : 'local LLM';
    }
    return 'deterministic fallback';
}

function commandLink(command: string, argument: string, label: string, tooltip: string): string {
    const encoded = encodeURIComponent(JSON.stringify([argument]));
    return `[${label}](command:${command}?${encoded} "${tooltip}")`;
}

function markdownFor(context: SymbolContext, file: string): vscode.MarkdownString {
    const symbol = context.symbol;
    const markdown = new vscode.MarkdownString(undefined, true);
    markdown.isTrusted = { enabledCommands: ['storyteller.usages', 'storyteller.mindmap', 'storyteller.context'] };
    markdown.supportHtml = false;

    markdown.appendMarkdown(`**${symbol.qualified}** — ${symbol.kind}\n\n`);
    markdown.appendMarkdown(`\`${symbol.file}:${symbol.line}\`\n\n`);

    const insight = context.insight;
    if (insight.micro || insight.why) {
        if (insight.micro) {
            markdown.appendMarkdown(`> ${insight.micro}\n\n`);
        }
        if (insight.why) {
            markdown.appendMarkdown(`${insight.why}\n\n`);
        }
        markdown.appendMarkdown(`*Summary source: ${sourceLabel(context)}*\n\n`);
    } else if (symbol.doc) {
        markdown.appendMarkdown(`> ${symbol.doc.split('\n')[0].trim()}\n\n`);
        markdown.appendMarkdown('*Summary source: docstring*\n\n');
    }

    const facts: string[] = [
        `complexity ${symbol.complexity}`,
        `${context.callers.length} caller(s)`,
        `${context.calls.length} resolved call(s)`,
    ];
    if (symbol.is_test) {
        facts.push('test');
    }
    markdown.appendMarkdown(`\`${facts.join('\` · \`')}\`\n\n`);

    if (symbol.flags.length > 0) {
        markdown.appendMarkdown(`Capabilities: ${symbol.flags.map((flag) => `\`${flag}\``).join(', ')}\n\n`);
    }
    if (context.flows.length > 0) {
        markdown.appendMarkdown(`Flow: \`${context.flows[0].chain.slice(0, 6).join(' -> ')}\`\n\n`);
    }

    const links = [
        commandLink('storyteller.usages', symbol.id, 'Call sites', 'Every resolved call site'),
        commandLink('storyteller.mindmap', symbol.id, 'Show in map', 'Open the architecture map here'),
        commandLink('storyteller.context', symbol.id, 'Details', 'Insight, callers and source'),
    ];
    markdown.appendMarkdown(`${links.join(' | ')}\n\n`);
    markdown.appendMarkdown(`*${file}*`);
    return markdown;
}

export class ArchitectureHoverProvider implements vscode.HoverProvider {
    /** The client is resolved lazily: hover must stay harmless without an engine. */
    constructor(private readonly client: () => EngineClient | undefined) {}

    public async provideHover(
        document: vscode.TextDocument,
        position: vscode.Position,
        token: vscode.CancellationToken
    ): Promise<vscode.Hover | null> {
        const configuration = vscode.workspace.getConfiguration('storyteller');
        if (!configuration.get<boolean>('enableHover', true)) {
            return null;
        }

        const wordRange = document.getWordRangeAtPosition(position, /[A-Za-z_$][\w$]*/);
        if (!wordRange) {
            return null;
        }
        const name = document.getText(wordRange).trim();
        if (!name || name.length < 3 || IGNORED_KEYWORDS.has(name.toLowerCase())) {
            return null;
        }

        const client = this.client();
        if (!client) {
            return null;
        }
        try {
            const context = await client.context(name, 0);
            if (token.isCancellationRequested) {
                return null;
            }
            return new vscode.Hover(markdownFor(context, context.symbol.file), wordRange);
        } catch {
            // Not indexed, ambiguous or engine unavailable: stay quiet.
            return null;
        }
    }
}

export function registerArchitectureHoverProvider(
    context: vscode.ExtensionContext,
    client: () => EngineClient | undefined
): void {
    const selector: vscode.DocumentSelector = SUPPORTED_LANGUAGES.map((language) => ({
        scheme: 'file',
        language,
    }));
    context.subscriptions.push(
        vscode.languages.registerHoverProvider(selector, new ArchitectureHoverProvider(client))
    );
}
