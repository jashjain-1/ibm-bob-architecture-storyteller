/**
 * shell.ts
 * --------
 * The HTML shell for every storyteller webview.
 *
 * It is a pure string builder (no vscode imports) so the same shell can be
 * rendered by the extension host and by the offline preview script used to
 * verify the map UI in a plain browser.
 */

export interface ShellOptions {
    title: string;
    payload: unknown;
    scriptUri?: string;
    styleUri?: string;
    cspSource?: string;
    nonce?: string;
    bodyClass?: string;
    inlineScript?: string;
    /** Load the UI as an ES module (required for the compiled map bundle). */
    moduleScript?: boolean;
}

function safeJson(value: unknown): string {
    return JSON.stringify(value)
        .replace(/</g, '\\u003c')
        .replace(/>/g, '\\u003e')
        .replace(/\u2028/g, '\\u2028')
        .replace(/\u2029/g, '\\u2029');
}

function csp(options: ShellOptions): string {
    const source = options.cspSource ? `${options.cspSource} ` : '';
    const nonce = options.nonce ? `'nonce-${options.nonce}' ` : "'unsafe-inline' ";
    return [
        "default-src 'none'",
        `style-src ${source}'unsafe-inline'`,
        `img-src ${source}data:`,
        `font-src ${source}`,
        `script-src ${nonce}${source}`,
        'connect-src http://127.0.0.1:*',
    ].join('; ');
}

export function shellHtml(options: ShellOptions): string {
    const styleTag = options.styleUri
        ? `<link rel="stylesheet" href="${options.styleUri}">`
        : '';
    const scriptAttrs = [
        options.nonce ? `nonce="${options.nonce}"` : '',
        options.moduleScript ? 'type="module"' : '',
    ].filter(Boolean).join(' ');
    const attrs = scriptAttrs ? `${scriptAttrs} ` : '';
    const scriptTag = options.scriptUri
        ? `<script ${attrs}src="${options.scriptUri}"></script>`
        : '';
    const inline = options.inlineScript
        ? `<script ${scriptAttrs}>${options.inlineScript}</script>`
        : '';

    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${csp(options)}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(options.title)}</title>
${styleTag}
</head>
<body class="${options.bodyClass ?? 'storyteller'}">
<div id="app" class="app" data-state="loading">
  <header id="toolbar" class="toolbar"></header>
  <section class="identity-banner" aria-label="Architecture Storyteller project banner">
    <h1>Architecture Storyteller 2.0 &amp; Ripple-Agent</h1>
    <p>
      Multi-agent architecture intelligence for AST ripple analysis, semantic impact mapping,
      and security-conscious local tooling.
    </p>
    <ul class="identity-pills" aria-label="Core capabilities">
      <li>Multi-Agent Workflow</li>
      <li>Polyglot AST &amp; Ripple Analysis</li>
      <li>Semantic Impact Mapping</li>
      <li>Hardened Localhost Tooling</li>
    </ul>
  </section>
  <div id="banner" class="banner" hidden></div>
  <main class="layout">
    <section id="tree-pane" class="pane pane-tree" aria-label="Repository tree"><div class="empty">Starting the architecture map...</div></section>
    <section id="detail-pane" class="pane pane-detail" aria-label="Symbol detail"></section>
  </main>
  <div id="graph-overlay" class="graph-overlay" hidden>
    <div class="graph-head">
      <span id="graph-title">Dependency graph</span>
      <button type="button" id="graph-close" class="ghost">Close</button>
    </div>
    <div id="graph-canvas" class="graph-canvas"></div>
  </div>
  <footer id="status" class="status" aria-live="polite"></footer>
</div>
<script ${scriptAttrs}>window.__STORYTELLER__ = ${safeJson(options.payload)};</script>
${inline}
${scriptTag}
</body>
</html>`;
}

export interface DocumentShellOptions {
    title: string;
    bodyHtml: string;
    styleUri?: string;
    cspSource?: string;
    nonce?: string;
}

/** A read-only shell for the context and dossier preview panels. */
export function documentShell(options: DocumentShellOptions): string {
    const source = options.cspSource ? `${options.cspSource} ` : '';
    const nonce = options.nonce ? `'nonce-${options.nonce}' ` : "'unsafe-inline' ";
    const policy = [
        "default-src 'none'",
        `style-src ${source}'unsafe-inline'`,
        `img-src ${source}data:`,
        `font-src ${source}`,
        `script-src ${nonce}`,
    ].join('; ');
    const styleTag = options.styleUri ? `<link rel="stylesheet" href="${options.styleUri}">` : '';
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${policy}">
<title>${escapeHtml(options.title)}</title>
${styleTag}
</head>
<body class="storyteller">
<main class="document">${options.bodyHtml}</main>
</body>
</html>`;
}

export function escapeHtml(value: unknown): string {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
