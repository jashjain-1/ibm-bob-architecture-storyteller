/**
 * contextPanel.ts
 * ---------------
 * Renders the symbol context and call-site documents.
 *
 * Everything shown comes from the engine payload: no canned classification, no
 * invented authorship. AI-written summaries stay labelled with their source.
 */

import * as vscode from 'vscode';

import { EngineClient } from '../engine/client';
import { SymbolBrief, SymbolContext, UsagesPayload } from '../engine/types';
import { escapeHtml } from '../webview/shell';
import { showDocumentPanel } from './documentPanel';

function locationLink(brief: SymbolBrief, label?: string): string {
    const args = encodeURIComponent(JSON.stringify([{ file: brief.file, line: brief.line }]));
    return `<a href="command:storyteller.openLocation?${args}">${escapeHtml(label ?? brief.qualified ?? brief.name)}</a>`;
}

function locationCommand(file: string, line: number, label: string): string {
    const args = encodeURIComponent(JSON.stringify([{ file, line }]));
    return `<a href="command:storyteller.openLocation?${args}">${escapeHtml(label)}</a>`;
}

function insightSourceLabel(context: SymbolContext): string {
    const source = context.insight.source ?? 'auto';
    if (source === 'bob') {
        return context.insight.model ? `IBM Bob (${context.insight.model})` : 'IBM Bob';
    }
    if (source === 'llm') {
        return context.insight.model ? `local LLM (${context.insight.model})` : 'local LLM';
    }
    return 'deterministic fallback';
}

function briefList(items: SymbolBrief[], emptyText: string): string {
    if (items.length === 0) {
        return `<p class="muted">${escapeHtml(emptyText)}</p>`;
    }
    const rows = items
        .slice(0, 60)
        .map((brief) => `<li>${locationLink(brief)} <span class="path">${escapeHtml(brief.file)}:${brief.line}</span></li>`)
        .join('');
    return `<ul class="links">${rows}</ul>`;
}

export function contextBody(context: SymbolContext): string {
    const symbol = context.symbol;
    const parts: string[] = [];

    parts.push('<div class="detail-head">');
    parts.push(`<h2>${escapeHtml(symbol.qualified)}</h2>`);
    parts.push(`<div class="where">${escapeHtml(symbol.kind)} at ${locationCommand(
        symbol.file, symbol.line, `${symbol.file}:${symbol.line}-${symbol.end ?? symbol.line}`
    )}</div>`);
    parts.push('</div>');

    const facts = [
        `<b>${symbol.complexity}</b> complexity`,
        `<b>${context.callers.length}</b> callers`,
        `<b>${context.calls.length}</b> resolved calls`,
        `<b>${symbol.language || 'unknown'}</b> language`,
        `<b>${symbol.is_test ? 'test' : 'production'}</b> layer`,
    ];
    parts.push(`<div class="metrics">${facts.map((fact) => `<span>${fact}</span>`).join('')}</div>`);

    if (symbol.flags.length > 0) {
        parts.push('<div class="metrics">' + symbol.flags
            .map((flag) => `<span class="tag ${flag.startsWith('dynamic:') ? 'danger' : 'warn'}">${escapeHtml(flag)}</span>`)
            .join('') + '</div>');
    }

    if (context.insight.micro || context.insight.why) {
        parts.push('<div class="callout">');
        if (context.insight.micro) {
            parts.push(`<div>${escapeHtml(context.insight.micro)}</div>`);
        }
        if (context.insight.why) {
            parts.push(`<div>${escapeHtml(context.insight.why)}</div>`);
        }
        parts.push(`<span class="src">Summary source: ${escapeHtml(insightSourceLabel(context))}</span>`);
        parts.push('</div>');
    } else if (symbol.doc) {
        parts.push(`<div class="callout"><div>${escapeHtml(symbol.doc.split('\n')[0].trim())}</div>` +
            '<span class="src">Summary source: docstring</span></div>');
    }

    if (context.parent) {
        parts.push(`<h4>Parent</h4>${briefList([context.parent], 'none')}`);
    }
    parts.push(`<h4>Called from (${context.callers.length})</h4>${briefList(context.callers, 'no resolved call sites')}`);
    parts.push(`<h4>Calls (${context.calls.length})</h4>${briefList(context.calls, 'no resolved calls')}`);
    if (context.children.length > 0) {
        parts.push(`<h4>Members (${context.children.length})</h4>${briefList(context.children, '')}`);
    }
    if (context.flows.length > 0) {
        const flows = context.flows
            .map((flow) => `<li class="subject">${escapeHtml(flow.chain.join(' -> '))}</li>`)
            .join('');
        parts.push(`<h4>Appears in flows</h4><ul class="links">${flows}</ul>`);
    }
    if (context.source) {
        parts.push('<h4>Source</h4>');
        parts.push(`<pre class="source">${escapeHtml(context.source)}</pre>`);
    }
    return parts.join('\n');
}

export function usagesBody(usages: UsagesPayload): string {
    const symbol = usages.symbol;
    const rows = usages.callers
        .map((caller) => `<tr>
            <td>${locationLink(caller)}</td>
            <td class="path">${escapeHtml(caller.file)}:${caller.line}</td>
            <td class="subject">${escapeHtml(caller.raw_calls.join(', '))}</td>
        </tr>`)
        .join('');
    const table = usages.callers.length === 0
        ? '<p class="muted">No resolved call sites. The symbol may only be referenced dynamically.</p>'
        : `<table><thead><tr><th>Calls from</th><th>Location</th><th>Call expression</th></tr></thead><tbody>${rows}</tbody></table>`;
    return `<div class="detail-head"><h2>${escapeHtml(symbol.qualified)}</h2>
        <div class="where">${escapeHtml(symbol.kind)} at ${escapeHtml(symbol.file)}:${symbol.line}</div></div>
        <div class="metrics"><span><b>${usages.call_site_count}</b> resolved call site(s)</span></div>
        ${table}`;
}

export async function showContext(
    context: vscode.ExtensionContext,
    client: EngineClient,
    symbol: string
): Promise<void> {
    const payload = await client.context(symbol, 60);
    showDocumentPanel(context, {
        key: 'context',
        title: `Context - ${payload.symbol.name}`,
        bodyHtml: contextBody(payload),
    });
}

export async function showUsages(
    context: vscode.ExtensionContext,
    client: EngineClient,
    symbol: string
): Promise<void> {
    const payload = await client.usages(symbol);
    showDocumentPanel(context, {
        key: 'usages',
        title: `Call sites - ${payload.symbol.name}`,
        bodyHtml: usagesBody(payload),
    });
}
